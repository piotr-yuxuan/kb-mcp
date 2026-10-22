"""Evaluating the search strategies on golden questions, for each model connected.

Each model gets its own index, built from the mirror like any other with the vector
store, so a second evaluation embeds nothing new. Every question is ranked by
``Library.ranked``, as ``search`` ranks, in each mode; the measures and the paired
tests of ``domain.evaluation`` say how the modes compare.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import TYPE_CHECKING

import yaml

from atlassian_offline_mcp.app.indexing import Embedding, build_index
from atlassian_offline_mcp.app.meaning import Meaning
from atlassian_offline_mcp.app.tools import Library
from atlassian_offline_mcp.domain.evaluation import (
    CUTOFF,
    SAMPLES,
    SEED,
    Measures,
    Question,
    averages,
    holm,
    measure,
    paired_test,
    percentile,
    plain,
)
from atlassian_offline_mcp.domain.search import WORD
from atlassian_offline_mcp.kernel.fields import Fields, RepresentationError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from atlassian_offline_mcp.adapters.embedding import Embedder
    from atlassian_offline_mcp.config.domain.settings import SearchMode, Settings

MODES: tuple[SearchMode, ...] = ("lexical", "semantic", "hybrid")
FIELDS = frozenset({"id", "question", "expected", "partial", "groups", "evidence"})
# What a question without these fields has.
DEFAULTS: dict[str, object] = {"partial": [], "groups": [], "evidence": {}}
LONGEST_QUESTION = 500
# The share of queries faster than the slow time reported: its 95th percentile.
TAIL = 0.95
HEADER = (
    "| Mode | Group | Recall@10 | MRR@10 | nDCG@10 | Success@1 | Section@10 |"
    " Query, median | Query, 95th |"
)


class GoldenError(ValueError):
    """A golden file that cannot be used; the message names the field at fault."""


class EvaluationError(Exception):
    """An evaluation that would not measure what it says; the message says why."""


def read_golden(text: str, resolve: Callable[[str], str | None]) -> list[Question]:
    """Read golden questions from YAML, each ref resolved to the path that it names.

    Every field is checked, and refused by name: an unknown or missing one, an id given
    twice, a question longer than search takes, no expected ref, evidence for a ref not
    expected, a group named twice or named "all" (which the averages use), a ref that
    the mirror does not hold, and a file without questions.
    """
    questions: list[Question] = []
    try:
        for given in Fields.each(yaml.safe_load(text), "golden"):
            item = Fields(DEFAULTS | given.value, given.path)
            evidence, expected, groups = (
                item.object("evidence"),
                item.texts("expected"),
                item.texts("groups"),
            )
            unknown = sorted(str(key) for key in set(item.value) - FIELDS)
            faults = {
                f"unknown field {', '.join(unknown)}": bool(unknown),
                f"question: at most {LONGEST_QUESTION} characters": (
                    len(item.text("question")) > LONGEST_QUESTION
                ),
                "expected: at least one ref": not expected,
                "evidence: refs as text, in quotes": not all(
                    isinstance(ref, str) for ref in evidence.value
                ),
                "evidence: only for an expected ref": not set(evidence.value) <= set(expected),
                "evidence: a phrase of a word or more": not all(
                    WORD.search(plain(evidence.text(ref))) for ref in evidence.value
                ),
                'groups: each once, and not "all"': len(set(groups)) != len(groups)
                or "all" in groups,
            }
            if fault := next((name for name, found in faults.items() if found), None):
                message = f"{item.path}: {fault}"
                raise GoldenError(message)
            questions.append(
                Question(
                    item.text("id"),
                    item.text("question"),
                    expected=tuple(path_of(ref, item, resolve) for ref in item.texts("expected")),
                    partial=tuple(path_of(ref, item, resolve) for ref in item.texts("partial")),
                    groups=item.texts("groups"),
                    evidence={
                        path_of(ref, item, resolve): evidence.text(ref) for ref in evidence.value
                    },
                )
            )
    except (yaml.YAMLError, RepresentationError) as error:
        message = f"not a golden file: {error}"
        raise GoldenError(message) from None
    if not questions or len({question.id for question in questions}) != len(questions):
        message = "golden: no question, or an id given twice"
        raise GoldenError(message)
    return questions


def path_of(ref: str, item: Fields, resolve: Callable[[str], str | None]) -> str:
    """Resolve a golden file's ref to a mirrored path, or refuse it, naming its question."""
    path = resolve(ref)
    if path is None:
        message = f"{item.path}: {ref!r} is not mirrored"
        raise GoldenError(message)
    return path


@dataclass
class Run:
    """How one model's search ranked the golden questions, mode by mode."""

    model: str
    fingerprint: str
    embedded: int  # texts that the model embedded for this run
    seconds: float  # how long the index took to build, embedding included
    per: dict[str, dict[str, Measures]] = field(default_factory=dict)  # mode, then question
    groups: dict[str, dict[str, Measures]] = field(default_factory=dict)  # mode, then group
    ranks: dict[str, dict[str, list[int | None]]] = field(default_factory=dict)  # mode, question
    times: dict[str, tuple[float, float]] = field(default_factory=dict)  # median, 95th, in s
    pvalues: dict[str, float] = field(default_factory=dict)  # mode against lexical
    adjusted: dict[str, float] = field(default_factory=dict)  # by Holm, over the whole run


def evaluate(
    settings: Settings,
    questions: Sequence[Question],
    embedders: Sequence[Embedder],
    clock: Callable[[], float],
    built_at: datetime,
) -> list[Run]:
    """Rank every question in every mode with each model given, and compare the modes.

    Each model's index is ``<evaluations>/indexes/<model>.sqlite``, its name's ``/``
    and ``:`` written ``_``. Raises EvaluationError when a mode by meaning falls back to
    words, which would measure words twice, and ModelError for a model that fails.
    """
    runs: list[Run] = []
    for embedder in embedders:
        name = embedder.name
        index = (
            settings.evaluations / "indexes" / f"{name.replace('/', '_').replace(':', '_')}.sqlite"
        )
        index.parent.mkdir(parents=True, exist_ok=True)
        started = clock()
        embedding = Embedding(embedder, settings.vectors)
        report = build_index(settings.docs, index, built_at, embedding)
        run = Run(name, embedder.fingerprint, report.embedded, clock() - started)
        # The model that the index names is this embedder's.
        meaning = Meaning({name: embedder}.__getitem__)
        library = Library(index, settings.docs, meaning, "lexical")
        refs = ((question.id, path) for question in questions for path in question.paths)
        if missing := next(((id_, path) for id_, path in refs if not library.resolve(path)), None):
            message = f"{name}: {missing[0]}: {missing[1]} is not in its index; run index again"
            raise EvaluationError(message)
        # Untimed: the first search by meaning reads the index's vectors.
        library.ranked(questions[0].text, "hybrid")
        for mode in MODES:
            run.per[mode], run.ranks[mode], spent = {}, {}, []
            for question in questions:
                started = clock()
                shown, note = library.ranked(question.text, mode, limit=CUTOFF)
                spent.append(clock() - started)
                if note:
                    message = f"{name}, {mode}:{note}"
                    raise EvaluationError(message)
                paths = [each.path for each in shown]
                texts = {each.path: each.text for each in shown}
                run.per[mode][question.id] = measure(paths, question, texts)
                run.ranks[mode][question.id] = [
                    paths.index(path) + 1 if path in paths else None for path in question.expected
                ]
            run.groups[mode] = averages(run.per[mode], questions)
            run.times[mode] = (median(spent), percentile(spent, TAIL))
            lexical = [run.per["lexical"][question.id].reciprocal_rank for question in questions]
            moded = [run.per[mode][question.id].reciprocal_rank for question in questions]
            run.pvalues[mode] = paired_test(lexical, moded)
        runs.append(run)
    tests = [(run, mode) for run in runs for mode in MODES[1:]]
    adjusted = holm([run.pvalues[mode] for run, mode in tests])
    for (run, mode), value in zip(tests, adjusted, strict=True):
        run.adjusted[mode] = value
    return runs


def record(runs: Sequence[Run], golden: str, built_at: datetime) -> dict[str, object]:
    """Give what a results file keeps: ids, models and numbers, never a question's text."""
    return {
        "golden_sha256": hashlib.sha256(golden.encode()).hexdigest(),
        "built_at": built_at.isoformat(),
        "test": {"kind": "paired randomisation, two-sided", "samples": SAMPLES, "seed": SEED},
        "runs": [
            {
                "model": run.model,
                "fingerprint": run.fingerprint,
                "embedded": run.embedded,
                "seconds": run.seconds,
                "times": run.times,
                "pvalues": run.pvalues,
                "adjusted": run.adjusted,
                "groups": {
                    mode: {group: asdict(each) for group, each in groups.items()}
                    for mode, groups in run.groups.items()
                },
                "ranks": run.ranks,
            }
            for run in runs
        ],
    }


def table(runs: Sequence[Run]) -> str:
    """Write the measures of each model's run as Markdown: one table, then the tests."""
    lines: list[str] = []
    for run in runs:
        lines += [
            f"## {run.model}",
            "",
            f"Index built in {run.seconds:.1f} s, {run.embedded} texts embedded for it.",
            "",
            HEADER,
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for mode, groups in run.groups.items():
            median_s, tail_s = run.times[mode]
            for group in sorted(groups, key=lambda name: (name != "all", name)):
                each = groups[group]
                section = "n/a" if each.section is None else f"{each.section:.3f}"
                lines.append(
                    f"| {mode} | {group} | {each.recall:.3f} | {each.reciprocal_rank:.3f} |"
                    f" {each.ndcg:.3f} | {each.success:.3f} | {section} |"
                    f" {median_s * 1000:.0f} ms | {tail_s * 1000:.0f} ms |"
                )
        lines.append("")
        lines += [
            f"MRR@10, {mode} against lexical: p = {run.pvalues[mode]:.4f},"
            f" adjusted (Holm) {run.adjusted[mode]:.4f}"
            for mode in MODES[1:]
        ]
        lines.append("")
    return "\n".join(lines)
