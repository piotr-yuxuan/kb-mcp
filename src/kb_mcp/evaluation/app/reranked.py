"""Reranking measured on golden questions: one mode not reranked, then at each depth.

Each arm searches every question as ``search`` does, timed, then asks it as ``ask``
does; the arm not reranked gives the first ranking, whose Recall@N says the most that a
depth of N could bring into the first ten. The reranking depth's default rule then reads
the arms.
"""

from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass
from statistics import fmean, median
from typing import TYPE_CHECKING

from opentelemetry import trace

from kb_mcp.evaluation.app.evaluation import TAIL, EvaluationError, prepared, running
from kb_mcp.evaluation.domain.evaluation import (
    CUTOFF,
    NOT_RERANKED,
    RULES,
    SAMPLES,
    SEED,
    Measures,
    Quoted,
    averages,
    measure,
    percentile,
    quoting,
    verdict,
)
from kb_mcp.kernel.records import Record
from kb_mcp.mcp.app.tools import UNRERANKED
from kb_mcp.observability.progress import task
from kb_mcp.search.adapters.reranking import RerankError
from kb_mcp.search.app.reranking import Reranking

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from kb_mcp.config.settings import SearchMode, Settings
    from kb_mcp.evaluation.app.evaluation import EvaluatedIndex, IndexMeasures
    from kb_mcp.evaluation.domain.evaluation import Question, Verdict
    from kb_mcp.search.adapters.reranking import Reranked

# The most questions, as a share, whose reranking may fail in an arm of a verdict.
FAILING = 0.05


class Counted:
    """A server's scores, a query's texts asked once, the tokens that it counted summed.

    ``ask`` sends what the search before it sent: kept, it costs no second request, and
    the search's time alone is a reranking's. A failure is kept as an answer is, so that
    a question's search, ranking and answer are all not reranked alike.
    """

    def __init__(self, score: Callable[[str, Sequence[str]], Reranked]) -> None:
        """Score through ``score``."""
        self._score = score
        self._kept: dict[tuple[str, tuple[str, ...]], Reranked | RerankError] = {}
        self.tokens: int | None = 0  # None once an answer counts none

    def __call__(self, query: str, texts: Sequence[str]) -> Reranked:
        """Give the texts' scores, asking the server unless they were asked already.

        Raises the RerankError of the texts' request, whenever they are asked again.
        """
        key = (query, tuple(texts))
        if key not in self._kept:
            try:
                answer = self._kept[key] = self._score(query, texts)
            except RerankError as error:
                self._kept[key] = error
                raise
            if answer.tokens is None or self.tokens is None:
                self.tokens = None
            else:
                self.tokens += answer.tokens
        kept = self._kept[key]
        if isinstance(kept, RerankError):
            raise kept
        return kept


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
    failed: int  # questions whose reranking failed, measured in their order not reranked


def measured(
    evaluated: EvaluatedIndex,
    settings: Settings,
    questions: Sequence[Question],
    arms: Arms,
    clock: Callable[[], float],
) -> tuple[IndexMeasures, list[Arm]]:
    """Build the evaluated index as ``eval`` does; measure the arm not reranked, then each depth.

    Give what the index holds and cost, and the arms. A search is timed as the server
    answers it, given the question alone; then every arm ranks as deep as the deepest,
    untimed, to give Recall@N, and measures its first ten. A question whose reranking
    fails keeps its order not reranked, and is counted. Raises EvaluationError when a
    search falls back by words, which would measure another arm, and ModelError for a
    model that fails. Each question in each arm is the progress task ``questions``, each
    named by ``running``.
    """
    of_index, plain = prepared(evaluated, settings, questions, clock, arms.built_at)
    deepest = max(arms.depths)
    # The search's own attributes stay off the run's span; its spans stay in its trace.
    hidden = trace.NonRecordingSpan(trace.get_current_span().get_span_context())
    found: list[Arm] = []
    with task("questions", (1 + len(arms.depths)) * len(questions)) as asking:
        for depth in (0, *arms.depths):
            reranking = Reranking(arms.score, depth) if depth else None
            library = plain.in_mode(arms.mode).rerank_with(reranking)
            tokens = arms.score.tokens
            per, quoted, ranked, spent, failed = {}, {}, {}, [], 0
            naming = functools.partial(running, arm=f"depth {depth}", per=per)
            for question in asking.each(questions, naming):
                started = clock()
                with trace.use_span(hidden):
                    library.search(question.text)
                spent.append(clock() - started)
                shown, note = library.ranked(question.text, arms.mode, limit=deepest)
                words, unreranked, _ = note.partition(UNRERANKED)
                if words:
                    message = f"depth {depth}, {question.id}:{words}"
                    raise EvaluationError(message)
                failed += bool(unreranked)
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
                    failed=failed,
                )
            )
    return of_index, found


def depth_verdict(found: Sequence[Arm], questions: Sequence[Question]) -> Verdict:
    """Apply the reranking depth's default rule to the arms measured, each named by its depth.

    No verdict when an arm's reranking failed on more than FAILING of the questions.
    """
    ruled = verdict(
        RULES["reranking depth"],
        NOT_RERANKED,
        {
            str(arm.depth) if arm.depth else NOT_RERANKED: (
                [arm.per[question.id].reciprocal_rank for question in questions],
                {group: each.reciprocal_rank for group, each in arm.groups.items()},
                round(arm.times[1] * 1000),
            )
            for arm in found
        },
        {},
    )
    failing = ", ".join(
        f"{arm.failed} of {len(questions)} at depth {arm.depth}"
        for arm in found
        if arm.failed > FAILING * len(questions)
    )
    if failing:
        reason = f"the reranking failed on more than {FAILING:.0%} of the questions: {failing}"
        return ruled.model_copy(update={"kept": None, "reason": reason})
    return ruled


def recorded(
    found: Sequence[Arm], ruled: Sequence[Verdict], golden: str, about: dict[str, object]
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
                "failed": arm.failed,
            }
            for arm in found
        ],
        "verdicts": [each.model_dump() for each in ruled],
    }
