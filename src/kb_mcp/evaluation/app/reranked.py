"""Reranking measured on golden questions: one mode not reranked, then at each depth.

Each arm searches every question as ``search`` does, timed, then asks it as ``ask``
does; the arm not reranked gives the first ranking, whose Recall@N says the most that a
depth of N could bring into the first ten. Plan 022's bar then reads the arms.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from statistics import fmean, median
from typing import TYPE_CHECKING

from kb_mcp.evaluation.app.evaluation import TAIL, EvaluationError, prepared
from kb_mcp.evaluation.domain.evaluation import (
    CUTOFF,
    SAMPLES,
    SEED,
    Measures,
    Quoted,
    averages,
    measure,
    percentile,
    quoting,
)
from kb_mcp.evaluation.domain.reranking import Decision, Depthed, default_reranking
from kb_mcp.kernel.record import Record
from kb_mcp.observability.adapters.progress import task
from kb_mcp.search.app.reranking import Reranking

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from kb_mcp.config.domain.settings import SearchMode, Settings
    from kb_mcp.evaluation.app.evaluation import EvaluatedIndex
    from kb_mcp.evaluation.domain.evaluation import Question
    from kb_mcp.search.adapters.reranking import Reranked


class Counted:
    """A server's scores, a query's texts asked once, the tokens that it counted summed.

    ``ask`` sends what the search before it sent: kept, it costs no second request, and
    the search's time alone is a reranking's.
    """

    def __init__(self, score: Callable[[str, Sequence[str]], Reranked]) -> None:
        """Score through ``score``."""
        self._score = score
        self._kept: dict[tuple[str, tuple[str, ...]], Reranked] = {}
        self.tokens: int | None = 0  # None once an answer counts none

    def __call__(self, query: str, texts: Sequence[str]) -> Reranked:
        """Give the texts' scores, asking the server unless they were asked already."""
        key = (query, tuple(texts))
        if key not in self._kept:
            answer = self._kept[key] = self._score(query, texts)
            if answer.tokens is None or self.tokens is None:
                self.tokens = None
            else:
                self.tokens += answer.tokens
        return self._kept[key]


@dataclass(frozen=True)
class Arms:
    """What to measure: the mode, the depths, the scores counted, and the build's time."""

    mode: SearchMode
    depths: tuple[int, ...]
    score: Counted
    built_at: datetime


class Arm(Record):
    """How one depth served the golden questions; depth 0, the order not reranked."""

    depth: int
    per: dict[str, Measures]  # by question
    groups: dict[str, Measures]
    asked: dict[str, Quoted]  # by group
    ranks: dict[str, list[int | None]]  # each expected document's rank to the tenth
    times: tuple[float, float]  # a search's median and 95th percentile, in seconds
    tokens: int | None  # that the server counted for this arm's requests
    recall: dict[int, float]  # the share of expected documents in the first N, for each depth


def measured(
    target: EvaluatedIndex,
    settings: Settings,
    questions: Sequence[Question],
    arms: Arms,
    clock: Callable[[], float],
) -> list[Arm]:
    """Build the target's index as ``eval`` does; measure the arm not reranked, then each depth.

    Every arm ranks as deep as the deepest, to give Recall@N, and measures its first ten.
    Raises EvaluationError when a search falls back, by words or not reranked, which
    would measure another arm, and ModelError for a model that fails. Each question in
    each arm is the progress task ``questions``.
    """
    _, plain = prepared(target, settings, questions, clock, arms.built_at)
    deepest = max(arms.depths)
    found: list[Arm] = []
    with task("questions", (1 + len(arms.depths)) * len(questions)) as asking:
        for depth in (0, *arms.depths):
            library = plain.rerank_with(Reranking(arms.score, depth) if depth else None)
            tokens = arms.score.tokens
            per, quoted, ranked, spent = {}, {}, {}, []
            for question in asking.each(questions, lambda one: one.id):
                started = clock()
                shown, note = library.ranked(question.text, arms.mode, limit=deepest)
                spent.append(clock() - started)
                if note:
                    message = f"depth {depth}, {question.id}:{note}"
                    raise EvaluationError(message)
                ranked[question.id] = [each.path for each in shown]
                per[question.id] = measure(
                    ranked[question.id], question, {each.path: each.text for each in shown}
                )
                passages = [
                    (each.path, each.text) for each in library.quoted(question.text, arms.mode)
                ]
                quoted[question.id] = quoting(passages, question)
            tops = {question.id: ranked[question.id][:CUTOFF] for question in questions}
            ranks = {
                question.id: [
                    tops[question.id].index(path) + 1 if path in tops[question.id] else None
                    for path in question.expected
                ]
                for question in questions
            }
            recall = {
                size: fmean(
                    len(set(question.expected) & set(ranked[question.id][:size]))
                    / len(question.expected)
                    for question in questions
                )
                for size in arms.depths
            }
            now = arms.score.tokens
            counted = None if tokens is None or now is None else now - tokens
            times = (median(spent), percentile(spent, TAIL))
            groups = averages(per, questions, Measures.mean)
            asked = averages(quoted, questions, Quoted.mean)
            found.append(
                Arm(
                    depth=depth,
                    per=per,
                    groups=groups,
                    asked=asked,
                    ranks=ranks,
                    times=times,
                    tokens=counted,
                    recall=recall,
                )
            )
    return found


def decided(found: Sequence[Arm], questions: Sequence[Question]) -> Decision | None:
    """Apply plan 022's bar to the arms measured: the first, not reranked, against the rest."""
    read = {
        arm.depth: Depthed(
            reciprocal=tuple(arm.per[question.id].reciprocal_rank for question in questions),
            groups={group: each.reciprocal_rank for group, each in arm.groups.items()},
            tail_ms=round(arm.times[1] * 1000),
        )
        for arm in found
    }
    plain = read.pop(0)
    return default_reranking(plain, read)


def recorded(
    found: Sequence[Arm], decision: Decision | None, golden: str, about: dict[str, object]
) -> dict[str, object]:
    """Give what a results file keeps: ids, models and numbers, never a question's text.

    ``about`` names what was measured: the mode, the models, the chunking, the server.
    """
    return {
        "golden_sha256": hashlib.sha256(golden.encode()).hexdigest(),
        "test": {"kind": "paired randomisation, two-sided", "samples": SAMPLES, "seed": SEED},
        **about,
        "arms": [
            {
                "depth": arm.depth,
                "groups": {group: each.model_dump() for group, each in arm.groups.items()},
                "asked": {group: each.model_dump() for group, each in arm.asked.items()},
                "times": arm.times,
                "tokens": arm.tokens,
                "recall": arm.recall,
                "ranks": arm.ranks,
            }
            for arm in found
        ],
        "decision": None if decision is None else decision.model_dump(),
    }
