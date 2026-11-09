"""``eval``: measure search and ask on golden questions, by mode, model and chunking."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.commands._embedding import open_endpoint
from kb_mcp.evaluation.app.evaluation import (
    ASK_DIVIDER,
    ASK_HEADER,
    DIVIDER,
    HEADER,
    EvaluatedIndex,
    EvaluationError,
    GoldenError,
    IndexMeasures,
    ask_row,
    built,
    compared,
    evaluate,
    heading,
    read_golden,
    record,
    row,
    table,
)
from kb_mcp.evaluation.domain.evaluation import CONTROL, Choice
from kb_mcp.kernel.chunking import CHUNKINGS
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record
from kb_mcp.mcp.app.tools import Library, UnanswerableError
from kb_mcp.observability.domain.log_files import STAMP
from kb_mcp.search.adapters.embedding import connect
from kb_mcp.search.adapters.model_api import ModelError
from kb_mcp.search.adapters.sqlite_index import SqliteIndex

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary


class IndexesEvaluated(Record):
    """How each target served the golden questions, each model's chunking, the results file."""

    runs: list[IndexMeasures]
    choices: dict[str, Choice]
    results: Path


def run(
    arguments: argparse.Namespace, loaded: Loaded
) -> tuple[ExitStatus, IndexesEvaluated | None]:
    """Evaluate each model and chunking; exit 1 on a failure, 2 for a refused golden file.

    Each target connects anew, so that the tokens reported are its own. The results,
    ids and numbers only, go to ``<data>/eval/results/<UTC time>.json``.
    """
    settings = loaded.settings
    try:
        golden = arguments.golden.read_text(encoding="utf-8")
        questions = read_golden(golden, Library(SqliteIndex(settings.index), settings.docs).resolve)
    except (GoldenError, OSError, UnanswerableError) as error:
        structlog.get_logger().error("eval.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    built_at = datetime.now(UTC)
    try:
        with open_endpoint(arguments, settings) as opened:
            targets = [
                EvaluatedIndex(connect(opened, name), chunking)
                for name in arguments.model or [settings.model]
                for chunking in arguments.chunking or CHUNKINGS
            ]
            runs = evaluate(settings, questions, targets, time.perf_counter, built_at)
    except (ModelError, EvaluationError, TimeoutError) as error:
        structlog.get_logger().error("eval.not_evaluated", reason=str(error))
        return ExitStatus.FAILED, None
    results = settings.evaluations / "results" / f"{built_at.strftime(STAMP)}.json"
    results.parent.mkdir(parents=True, exist_ok=True)
    choices = compared(runs, questions)
    kept = record(runs, golden, built_at, choices)
    results.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    return ExitStatus.OK, IndexesEvaluated(runs=runs, choices=choices, results=results)


def text(evaluated: IndexesEvaluated, summary: Summary) -> str:
    """Write each run's measures, each model's choice of chunking, then the results file.

    Short gives each run's row of all the questions, mode by mode, for search and for
    ask, and its costs; detailed, its tables of every group and the tests of each mode
    against words. Both end with each model's default chunking by the rule, and its
    tests against the control. Lexical search's rows come with the first run alone.
    """
    choices = [
        line
        for model, choice in evaluated.choices.items()
        for line in (
            f"Default chunking for {model}, by the rule: {choice.chunking}",
            *(
                f"  {name}, {measure} against {CONTROL}: p = {value:.4f},"
                f" adjusted (Holm) {choice.adjusted[name][measure]:.4f}"
                for name, tested in choice.pvalues.items()
                for measure, value in tested.items()
            ),
        )
    ]
    closing = "\n".join([*choices, f"Results: {evaluated.results}", ""])
    if summary == "detailed":
        return f"{table(evaluated.runs)}\n{closing}"
    lines = []
    for run in evaluated.runs:
        modes = [mode for mode in run.groups if mode != "lexical" or run is evaluated.runs[0]]
        lines += [heading(run), "", built(run), "", HEADER, DIVIDER]
        lines += [row(mode, "all", run.groups[mode]["all"], run.times[mode]) for mode in modes]
        lines += ["", ASK_HEADER, ASK_DIVIDER]
        lines += [
            ask_row(mode, "all", run.asked_groups[mode]["all"], run.ask_times[mode])
            for mode in modes
        ]
        lines.append("")
    return "\n".join(lines) + closing
