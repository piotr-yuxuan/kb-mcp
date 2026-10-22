"""``eval``: measure lexical, semantic and hybrid search on golden questions, by model."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._embedding import open_endpoint
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.evaluation.app.evaluation import (
    DIVIDER,
    HEADER,
    EvaluationError,
    GoldenError,
    evaluate,
    read_golden,
    record,
    row,
    table,
)
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.mcp.app.tools import Library, UnanswerableError
from atlassian_offline_mcp.search.adapters.embedding import ModelError, connect

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from atlassian_offline_mcp.config.domain.settings import Settings
    from atlassian_offline_mcp.evaluation.app.evaluation import Run
    from atlassian_offline_mcp.kernel.output import Summary

STAMP = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class Evaluated:
    """How each model's search ranked the golden questions, and the file of the results."""

    runs: list[Run]
    results: Path


def run(arguments: argparse.Namespace, settings: Settings) -> tuple[ExitStatus, Evaluated | None]:
    """Evaluate; exit 1 when something failed, 2 for bad settings or a refused golden file.

    The results, ids and numbers only, go to ``<data>/eval/results/<UTC time>.json``.
    """
    try:
        golden = arguments.golden.read_text(encoding="utf-8")
        questions = read_golden(golden, Library(settings.index, settings.docs).resolve)
        opened = open_endpoint(arguments, settings)
    except (SettingsError, GoldenError, OSError, UnanswerableError) as error:
        sys.stderr.write(f"refused: {error}\n")
        return ExitStatus.REFUSED, None
    built_at = datetime.now(UTC)
    try:
        with opened:
            embedders = [connect(opened, name) for name in arguments.model or [settings.model]]
            runs = evaluate(settings, questions, embedders, time.perf_counter, built_at)
    except (ModelError, EvaluationError) as error:
        sys.stderr.write(f"not evaluated: {error}\n")
        return ExitStatus.FAILED, None
    results = settings.evaluations / "results" / f"{built_at.strftime(STAMP)}.json"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(json.dumps(record(runs, golden, built_at), indent=1), encoding="utf-8")
    return ExitStatus.OK, Evaluated(runs, results)


def text(evaluated: Evaluated, summary: Summary) -> str:
    """Write each model's measures, then the results file.

    Short gives each model's row of all the questions, mode by mode; detailed, its table
    of every group, how its index was built, and the tests of each mode against words.
    """
    if summary == "detailed":
        return f"{table(evaluated.runs)}\nResults: {evaluated.results}\n"
    lines = []
    for run in evaluated.runs:
        lines += [f"## {run.model}", "", HEADER, DIVIDER]
        lines += [
            row(mode, "all", groups["all"], run.times[mode]) for mode, groups in run.groups.items()
        ]
        lines.append("")
    return "\n".join([*lines, f"Results: {evaluated.results}", ""])
