"""``eval``: measure lexical, semantic and hybrid search on golden questions, by model."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.embedding import ModelError, connect
from atlassian_offline_mcp.app.evaluation import (
    EvaluationError,
    GoldenError,
    evaluate,
    read_golden,
    record,
    table,
)
from atlassian_offline_mcp.app.tools import Library, UnanswerableError
from atlassian_offline_mcp.commands._options import (
    add_embedding_options,
    add_settings_options,
    model_name,
    open_endpoint,
    settings_of,
)
from atlassian_offline_mcp.config.domain.settings import SettingsError

if TYPE_CHECKING:
    import argparse

SOME_FAILED = 1
BAD_ARGUMENTS = 2
STAMP = "%Y%m%dT%H%M%SZ"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``eval`` to the command."""
    parser = subparsers.add_parser(
        "eval", help="measure lexical, semantic and hybrid search on golden questions"
    )
    add_settings_options(parser)
    add_embedding_options(parser)
    parser.add_argument("golden", type=Path, help="a YAML file of golden questions")
    parser.add_argument(
        "--model",
        action="append",
        type=model_name,
        help="a model to evaluate, as the endpoint names it; by default, the setting",
    )
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> int:
    """Evaluate; exit 1 when something failed, 2 for bad settings or a refused golden file.

    The tables go to standard output, and the results, ids and numbers only, to
    ``<data>/eval/results/<UTC time>.json``.
    """
    try:
        settings = settings_of(arguments)
        golden = arguments.golden.read_text(encoding="utf-8")
        questions = read_golden(golden, Library(settings.index, settings.docs).resolve)
        opened = open_endpoint(arguments, settings)
    except (SettingsError, GoldenError, OSError, UnanswerableError) as error:
        sys.stderr.write(f"refused: {error}\n")
        return BAD_ARGUMENTS
    built_at = datetime.now(UTC)
    try:
        with opened:
            embedders = [connect(opened, name) for name in arguments.model or [settings.model]]
            runs = evaluate(settings, questions, embedders, time.perf_counter, built_at)
    except (ModelError, EvaluationError) as error:
        sys.stderr.write(f"not evaluated: {error}\n")
        return SOME_FAILED
    results = settings.evaluations / "results" / f"{built_at.strftime(STAMP)}.json"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(json.dumps(record(runs, golden, built_at), indent=1), encoding="utf-8")
    sys.stdout.write(f"{table(runs)}\nResults: {results}\n")
    return 0
