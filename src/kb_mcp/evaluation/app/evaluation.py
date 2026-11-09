"""Evaluating the search strategies on golden questions, for each model and chunking.

Each evaluated index, a model connected and a chunking, gets its own file, built from the
mirror like any other with the vector cache, so a second evaluation embeds nothing new.
Every question is ranked by ``Library.ranked``, as ``search`` ranks, and answered by
``Library.quoted``, as ``ask`` answers, in each mode; the measures and the paired tests
of ``evaluation.domain.evaluation`` say how the modes compare, and its rule which
chunking each model's index should be cut by. Each evaluated index is a span; each
question is timed and logged, and each mode's scores measured, as
``docs/reference/telemetry/eval.md`` lists it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING, get_args

import structlog
import yaml
from opentelemetry import metrics, trace
from pydantic import ConfigDict, Field, ValidationError

from kb_mcp.config.domain.settings import SearchMode
from kb_mcp.evaluation.domain.evaluation import (
    CONTROL,
    CUTOFF,
    SAMPLES,
    SEED,
    Measures,
    Question,
    Quoted,
    Scored,
    averages,
    default_chunking,
    holm,
    measure,
    paired_test,
    percentile,
    quoting,
)
from kb_mcp.evaluation.domain.golden import Golden
from kb_mcp.kernel.chunking import CHARACTERS_PER_TOKEN
from kb_mcp.kernel.record import Record
from kb_mcp.mcp.app.tools import Library
from kb_mcp.observability.adapters.progress import task
from kb_mcp.search.adapters.sqlite_index import SqliteIndex
from kb_mcp.search.app.indexing import Embedding, build_index
from kb_mcp.search.app.meaning import Meaning

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.evaluation.domain.evaluation import Choice
    from kb_mcp.kernel.chunking import Chunking
    from kb_mcp.search.adapters.embedding import Embedder

MODES: tuple[SearchMode, ...] = get_args(SearchMode.__value__)
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
TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# How long each question took to rank, by chunking and mode; each mode's measures on
# all the questions, as the tables' first rows of the mode have them, by model, chunking,
# mode and measure.
QUESTION_DURATION = METER.create_histogram(
    "kb_mcp.eval.question.duration", unit="s", description="How long a question took to rank"
)
SCORE = METER.create_gauge(
    "kb_mcp.eval.score", unit="1", description="A mode's measure on all the golden questions"
)
ASK_HEADER = "| Mode | Group | Found@ask | Evidence@ask | Ask, median | Ask, 95th |"
ASK_DIVIDER = "|---|---|---|---|---|---|"


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
            id=given.id,
            text=given.question,
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
    """Resolve a golden file's ref to a path of the mirror, or refuse it, naming ``where`` it is."""
    path = resolve(ref)
    if path is None:
        message = f"{where}: {ref!r} is not mirrored"
        raise GoldenError(message)
    return path


@dataclass(frozen=True)
class EvaluatedIndex:
    """What one index under evaluation is built with: a model connected, and a chunking."""

    embedder: Embedder
    chunking: Chunking


class Costs(Record):
    """What an evaluated index holds and cost, whatever the vector cache held before."""

    chunks: int
    characters: int  # of the texts that the chunks embed
    tokens: int | None  # that the endpoint reported for the texts embedded in this run
    bytes: int  # of the index file

    @property
    def estimated(self) -> int:
        """The tokens of the texts that the chunks embed, at the characters of a token."""
        return self.characters // CHARACTERS_PER_TOKEN


class IndexMeasures(Record):
    """How one evaluated index ranked the golden questions, and ask answered, mode by mode."""

    model_config = ConfigDict(frozen=False)

    model: str
    fingerprint: str
    embedded: int  # texts that the model embedded for this run
    seconds: float  # how long the index took to build, embedding included
    chunking: str = CONTROL
    costs: Costs = Costs(chunks=0, characters=0, tokens=None, bytes=0)
    per: dict[str, dict[str, Measures]] = Field(default_factory=dict)  # mode, then question
    groups: dict[str, dict[str, Measures]] = Field(default_factory=dict)  # mode, then group
    ranks: dict[str, dict[str, list[int | None]]] = Field(default_factory=dict)  # mode, question
    times: dict[str, tuple[float, float]] = Field(default_factory=dict)  # median, 95th, in s
    pvalues: dict[str, float] = Field(default_factory=dict)  # mode against lexical
    adjusted: dict[str, float] = Field(default_factory=dict)  # by Holm, over the whole run
    asked: dict[str, dict[str, Quoted]] = Field(default_factory=dict)  # mode, then question
    asked_groups: dict[str, dict[str, Quoted]] = Field(default_factory=dict)  # mode, group
    ask_times: dict[str, tuple[float, float]] = Field(default_factory=dict)  # median, 95th


def evaluate(
    settings: Settings,
    questions: Sequence[Question],
    indexes: Sequence[EvaluatedIndex],
    clock: Callable[[], float],
    built_at: datetime,
) -> list[IndexMeasures]:
    """Rank and answer every question in every mode on each evaluated index; compare the modes.

    Each evaluated index is ``prepared``. Raises EvaluationError when a mode by meaning
    falls back to words, which would measure words twice, and ModelError for a model
    that fails. For each, its index's build reports its own tasks, then the task
    ``questions`` every question in every mode, each by its id.

    Each is the span ``eval.model``; each question, timed in
    ``kb_mcp.eval.question.duration`` and said at DEBUG by ``eval.question``; each mode's
    measures on all the questions, ask's among them, are set in ``kb_mcp.eval.score``, but
    Section@10, and Evidence@ask when no question has evidence; ``eval.evaluated`` says
    at INFO each index evaluated. Each names its chunking.
    """
    log = structlog.get_logger()
    runs: list[IndexMeasures] = []
    for evaluated in indexes:
        name = evaluated.embedder.name
        named = {"gen_ai.request.model": name, "kb_mcp.chunking": evaluated.chunking}
        with TRACER.start_as_current_span("eval.model", attributes=named):
            run, library = prepared(evaluated, settings, questions, clock, built_at)
            with task("questions", len(MODES) * len(questions)) as asked:
                for mode in MODES:
                    run.per[mode], run.ranks[mode], run.asked[mode] = {}, {}, {}
                    spent, asking = [], []
                    for question in asked.each(questions, lambda one: one.id):
                        started = clock()
                        shown, note = library.ranked(question.text, mode, limit=CUTOFF)
                        spent.append(clock() - started)
                        QUESTION_DURATION.record(
                            spent[-1], {"kb_mcp.chunking": evaluated.chunking, "kb_mcp.mode": mode}
                        )
                        if note:
                            message = f"{name}, {mode}:{note}"
                            raise EvaluationError(message)
                        paths = [each.path for each in shown]
                        texts = {each.path: each.text for each in shown}
                        run.per[mode][question.id] = measure(paths, question, texts)
                        run.ranks[mode][question.id] = [
                            paths.index(path) + 1 if path in paths else None
                            for path in question.expected
                        ]
                        started = clock()
                        quoted = library.quoted(question.text, mode)
                        asking.append(clock() - started)
                        passages = [(each.path, each.text) for each in quoted]
                        run.asked[mode][question.id] = quoting(passages, question)
                        log.debug(
                            "eval.question",
                            id=question.id,
                            chunking=evaluated.chunking,
                            mode=mode,
                            seconds=round(spent[-1], 3),
                            reciprocal_rank=run.per[mode][question.id].reciprocal_rank,
                        )
                    run.groups[mode] = averages(run.per[mode], questions, Measures.mean)
                    run.asked_groups[mode] = averages(run.asked[mode], questions, Quoted.mean)
                    run.times[mode] = (median(spent), percentile(spent, TAIL))
                    run.ask_times[mode] = (median(asking), percentile(asking, TAIL))
                    lexical = [
                        run.per["lexical"][question.id].reciprocal_rank for question in questions
                    ]
                    moded = [run.per[mode][question.id].reciprocal_rank for question in questions]
                    run.pvalues[mode] = paired_test(lexical, moded)
                    every = run.groups[mode]["all"]
                    scored = {**named, "kb_mcp.mode": mode}
                    SCORE.set(every.recall, {**scored, "kb_mcp.measure": f"recall@{CUTOFF}"})
                    SCORE.set(every.reciprocal_rank, {**scored, "kb_mcp.measure": f"mrr@{CUTOFF}"})
                    SCORE.set(every.ndcg, {**scored, "kb_mcp.measure": f"ndcg@{CUTOFF}"})
                    SCORE.set(every.success, {**scored, "kb_mcp.measure": "success@1"})
                    answered = run.asked_groups[mode]["all"]
                    SCORE.set(answered.found, {**scored, "kb_mcp.measure": "found@ask"})
                    if answered.evidence is not None:
                        SCORE.set(answered.evidence, {**scored, "kb_mcp.measure": "evidence@ask"})
            log.info(
                "eval.evaluated",
                model=name,
                chunking=evaluated.chunking,
                questions=len(questions),
                embedded=run.embedded,
                index_seconds=round(run.seconds, 3),
            )
        runs.append(run)
    tests = [(run, mode) for run in runs for mode in MODES[1:]]
    adjusted = holm([run.pvalues[mode] for run, mode in tests])
    for (run, mode), value in zip(tests, adjusted, strict=True):
        run.adjusted[mode] = value
    return runs


def prepared(
    evaluated: EvaluatedIndex,
    settings: Settings,
    questions: Sequence[Question],
    clock: Callable[[], float],
    built_at: datetime,
) -> tuple[IndexMeasures, Library]:
    """Build an evaluated index, and give its run, costs counted, and a library over it.

    The index is ``<evaluation_indexes>/<chunking>/<model>.sqlite``, its model's ``/``
    and ``:`` written ``_``. Raises EvaluationError when a document that a question names
    is not in it, and ModelError for a model that fails. The library has read the
    index's vectors already, so that no question's time holds the reading.
    """
    embedder, name = evaluated.embedder, evaluated.embedder.name
    safe = name.replace("/", "_").replace(":", "_")
    index = settings.evaluation_indexes / evaluated.chunking / f"{safe}.sqlite"
    index.parent.mkdir(parents=True, exist_ok=True)
    started = clock()
    embedding = Embedding(embedder, settings.vectors, chunking=evaluated.chunking)
    report = build_index(settings.docs, index, built_at, embedding)
    seconds = clock() - started
    costs = Costs(
        chunks=report.chunks,
        characters=report.characters,
        tokens=embedder.tokens,
        bytes=index.stat().st_size,
    )
    run = IndexMeasures(
        model=name,
        fingerprint=embedder.fingerprint,
        embedded=report.embedded,
        seconds=seconds,
        chunking=evaluated.chunking,
        costs=costs,
    )
    # The model that the index names is this embedder's.
    meaning = Meaning({name: embedder}.__getitem__)
    library = Library(SqliteIndex(index), settings.docs, meaning, "lexical")
    refs = ((question.id, path) for question in questions for path in question.paths)
    missing = next(((id_, path) for id_, path in refs if not library.resolve(path)), None)
    if missing:
        message = f"{name}: {missing[0]}: {missing[1]} is not in its index; run embed again"
        raise EvaluationError(message)
    # Untimed: the first search by meaning reads the index's vectors.
    library.ranked(questions[0].text, "hybrid")
    return run, library


def compared(runs: Sequence[IndexMeasures], questions: Sequence[Question]) -> dict[str, Choice]:
    """Choose each model's default chunking by the rule, from its runs in hybrid mode.

    Only a model whose runs include the control's gets a choice.
    """
    scored: dict[str, dict[str, Scored]] = {}
    for run in runs:
        asked = (run.asked["hybrid"][question.id].evidence for question in questions)
        scored.setdefault(run.model, {})[run.chunking] = Scored(
            reciprocal_ranks=tuple(
                run.per["hybrid"][question.id].reciprocal_rank for question in questions
            ),
            evidence=tuple(each for each in asked if each is not None),
            tokens=run.costs.estimated,
        )
    return {
        model: default_chunking(chunkings)
        for model, chunkings in scored.items()
        if CONTROL in chunkings
    }


def record(
    runs: Sequence[IndexMeasures], golden: str, built_at: datetime, choices: Mapping[str, Choice]
) -> dict[str, object]:
    """Give what a results file keeps: ids, models and numbers, never a question's text."""
    return {
        "golden_sha256": hashlib.sha256(golden.encode()).hexdigest(),
        "built_at": built_at.isoformat(),
        "test": {"kind": "paired randomisation, two-sided", "samples": SAMPLES, "seed": SEED},
        "indexes": [
            {
                "model": run.model,
                "chunking": run.chunking,
                "fingerprint": run.fingerprint,
                "embedded": run.embedded,
                "seconds": run.seconds,
                "costs": run.costs.model_dump() | {"estimated": run.costs.estimated},
                "times": run.times,
                "ask_times": run.ask_times,
                "pvalues": run.pvalues,
                "adjusted": run.adjusted,
                "groups": {
                    mode: {group: each.model_dump() for group, each in groups.items()}
                    for mode, groups in run.groups.items()
                },
                "asked": {
                    mode: {group: each.model_dump() for group, each in groups.items()}
                    for mode, groups in run.asked_groups.items()
                },
                "ranks": run.ranks,
            }
            for run in runs
        ],
        "chunking": {model: choice.model_dump() for model, choice in choices.items()},
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


def ask_row(mode: str, group: str, each: Quoted, times: tuple[float, float]) -> str:
    """Write a mode's ask measures of a group as a row under ``ASK_HEADER``, with its times."""
    median_s, tail_s = times
    evidence = "n/a" if each.evidence is None else f"{each.evidence:.3f}"
    return (
        f"| {mode} | {group} | {each.found:.3f} | {evidence} |"
        f" {median_s * 1000:.0f} ms | {tail_s * 1000:.0f} ms |"
    )


def heading(run: IndexMeasures) -> str:
    """Name a run: its model, and its chunking."""
    return f"## {run.model}, {run.chunking}"


def built(run: IndexMeasures) -> str:
    """Say how a run's index was built and what it costs."""
    costs = run.costs
    reported = "none" if costs.tokens is None else f"{costs.tokens:,}"
    return (
        f"Index built in {run.seconds:.1f} s, {run.embedded} texts embedded for it;"
        f" {costs.chunks:,} chunks of {costs.characters:,} characters, about"
        f" {costs.estimated:,} tokens; tokens reported: {reported}; {costs.bytes:,} bytes."
    )


def table(runs: Sequence[IndexMeasures]) -> str:
    """Write the measures of each run as Markdown: search's table, ask's, then the tests.

    Lexical search ignores the model and the chunking: its rows come with the first run
    alone.
    """
    lines: list[str] = []
    for run in runs:
        modes = [mode for mode in run.groups if mode != "lexical" or run is runs[0]]
        lines += [heading(run), "", built(run), "", HEADER, DIVIDER]
        for mode in modes:
            lines += [
                row(mode, group, run.groups[mode][group], run.times[mode])
                for group in sorted(run.groups[mode], key=lambda name: (name != "all", name))
            ]
        lines += ["", ASK_HEADER, ASK_DIVIDER]
        lines += [
            ask_row(mode, group, run.asked_groups[mode][group], run.ask_times[mode])
            for mode in modes
            for group in sorted(run.asked_groups[mode], key=lambda name: (name != "all", name))
        ]
        lines.append("")
        lines += [
            f"MRR@10, {mode} against lexical: p = {run.pvalues[mode]:.4f},"
            f" adjusted (Holm) {run.adjusted[mode]:.4f}"
            for mode in MODES[1:]
        ]
        lines.append("")
    return "\n".join(lines)
