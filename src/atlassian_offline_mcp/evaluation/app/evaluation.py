"""Evaluating the search strategies on golden questions, for each model connected.

Each model gets its own index, built from the mirror like any other with the vector
store, so a second evaluation embeds nothing new. Every question is ranked by
``Library.ranked``, as ``search`` ranks, in each mode; the measures and the paired
tests of ``evaluation.domain.evaluation`` say how the modes compare.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from atlassian_offline_mcp.evaluation.domain.evaluation import (
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
)
from atlassian_offline_mcp.evaluation.domain.golden import Golden
from atlassian_offline_mcp.mcp.app.tools import Library
from atlassian_offline_mcp.search.app.indexing import Embedding, build_index
from atlassian_offline_mcp.search.app.meaning import Meaning

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from atlassian_offline_mcp.config.domain.settings import SearchMode, Settings
    from atlassian_offline_mcp.search.adapters.embedding import Embedder

MODES: tuple[SearchMode, ...] = ("lexical", "semantic", "hybrid")
# What the refusal of a golden file says, by the type of Pydantic's error; of another
# type, Pydantic's message, which holds no input, or the rule's.
SAID = {
    "missing": "missing",
    "string_type": "expected a string",
    "list_type": "expected a list",
    "dict_type": "expected an object",
    "model_type": "expected an object",
}
# The types of Pydantic's error for a field that a question does not have.
UNKNOWN = frozenset({"extra_forbidden", "invalid_key"})
# The share of queries faster than the slow time reported: its 95th percentile.
TAIL = 0.95
HEADER = (
    "| Mode | Group | Recall@10 | MRR@10 | nDCG@10 | Success@1 | Section@10 |"
    " Query, median | Query, 95th |"
)
# The line under the header, one cell per column.
DIVIDER = "|---|---|---|---|---|---|---|---|---|"


class GoldenError(ValueError):
    """A golden file that cannot be used; the message names the field at fault."""


class EvaluationError(Exception):
    """An evaluation that would not measure what it says; the message says why."""


def read_golden(text: str, resolve: Callable[[str], str | None]) -> list[Question]:
    """Read golden questions from YAML, each ref resolved to the path that it names.

    ``Golden`` reads the file, strictly. Its refusals are given by where each is, as
    ``golden[i]`` and the field, never by what was found there: an unknown or missing
    field, one of another type, or a rule broken. A ref that the mirror does not hold is
    refused too, by its question.
    """
    try:
        golden = Golden.model_validate(yaml.safe_load(text))
    except yaml.YAMLError as error:
        message = f"not a golden file: {error}"
        raise GoldenError(message) from None
    except ValidationError as error:
        refusals = []
        for each in error.errors(include_input=False, include_url=False):
            unknown = each["type"] in UNKNOWN
            place = each["loc"][:-1] if unknown else each["loc"]
            where = "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in place)
            said = f"unknown field {each['loc'][-1]}" if unknown else SAID.get(each["type"])
            refusals.append(f"golden{where}: {said or each['msg']}")
        message = "; ".join(refusals)
        raise GoldenError(message) from None
    return [
        Question(
            given.id,
            given.question,
            expected=tuple(path_of(ref, f"golden[{index}]", resolve) for ref in given.expected),
            partial=tuple(path_of(ref, f"golden[{index}]", resolve) for ref in given.partial),
            groups=tuple(given.groups),
            evidence={
                path_of(ref, f"golden[{index}]", resolve): phrase
                for ref, phrase in given.evidence.items()
            },
        )
        for index, given in enumerate(golden.root)
    ]


def path_of(ref: str, where: str, resolve: Callable[[str], str | None]) -> str:
    """Resolve a golden file's ref to a mirrored path, or refuse it, naming ``where`` it is."""
    path = resolve(ref)
    if path is None:
        message = f"{where}: {ref!r} is not mirrored"
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


def row(mode: str, group: str, each: Measures, times: tuple[float, float]) -> str:
    """Write a mode's measures of a group as a row under ``HEADER``, with its query times."""
    median_s, tail_s = times
    section = "n/a" if each.section is None else f"{each.section:.3f}"
    return (
        f"| {mode} | {group} | {each.recall:.3f} | {each.reciprocal_rank:.3f} |"
        f" {each.ndcg:.3f} | {each.success:.3f} | {section} |"
        f" {median_s * 1000:.0f} ms | {tail_s * 1000:.0f} ms |"
    )


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
            DIVIDER,
        ]
        for mode, groups in run.groups.items():
            lines += [
                row(mode, group, groups[group], run.times[mode])
                for group in sorted(groups, key=lambda name: (name != "all", name))
            ]
        lines.append("")
        lines += [
            f"MRR@10, {mode} against lexical: p = {run.pvalues[mode]:.4f},"
            f" adjusted (Holm) {run.adjusted[mode]:.4f}"
            for mode in MODES[1:]
        ]
        lines.append("")
    return "\n".join(lines)
