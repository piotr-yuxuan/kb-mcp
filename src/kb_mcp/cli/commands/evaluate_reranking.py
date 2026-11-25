"""``eval-rerank``: measure search reranked at each depth on golden questions, by the bar."""

from __future__ import annotations

import functools
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.commands._embedding import open_endpoint
from kb_mcp.evaluation.app.agents import AgentsError, chosen
from kb_mcp.evaluation.app.evaluation import (
    EvaluatedIndex,
    EvaluationError,
    GoldenError,
    read_golden,
)
from kb_mcp.evaluation.app.reranked import (
    Arm,
    Arms,
    Counted,
    depth_verdict,
    measured,
    recorded,
)
from kb_mcp.evaluation.domain.evaluation import Verdict
from kb_mcp.kernel.names import BAR_DEPTHS, RERANKING, STAMP, ExitStatus
from kb_mcp.kernel.records import Record
from kb_mcp.mcp.app.tools import Library, UnanswerableError
from kb_mcp.search.adapters.embedding import connect
from kb_mcp.search.adapters.model_api import ModelError, endpoint
from kb_mcp.search.adapters.reranking import EVALUATION, rerank, served
from kb_mcp.search.adapters.sqlite_index import SqliteIndex

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.settings import Loaded
    from kb_mcp.kernel.names import Detail

HEADER = (
    "| Depth | Group | Recall@10 | MRR@10 | nDCG@10 | Success@1 | Section@10 | Found@ask"
    " | Evidence@ask | Tokens | Search, median | Search, 95th |"
)
DIVIDER = "|---|---|---|---|---|---|---|---|---|---|---|---|"


class DepthsEvaluated(Record):
    """Each arm measured, the bar's verdict, the mode, and the results file."""

    arms: list[Arm]
    decision: Verdict
    mode: str
    results: Path


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, DepthsEvaluated | None]:
    """Measure each depth; exit 1 on a failure, 2 for a refused golden file or sample.

    The setting's model, chunking and search mode are measured, reranked by the setting's
    reranker, on the golden file's questions or the sample of them that --sample chooses,
    as ``eval-agents prepare`` does. The results, ids and numbers only, go to
    ``<data>/eval/results/<UTC time>-rerank.json``.
    """
    settings = loaded.settings
    try:
        golden = arguments.golden.read_text(encoding="utf-8")
        read = read_golden(golden, Library(SqliteIndex(settings.index), settings.docs).resolve)
        questions = chosen(read, arguments.sample, arguments.seed)
    except (GoldenError, OSError, UnanswerableError, AgentsError) as error:
        structlog.get_logger().error("eval.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    built_at = datetime.now(UTC)
    reranker = settings.rerank
    depths = tuple(sorted(set(arguments.depth or BAR_DEPTHS)))
    try:
        with (
            open_endpoint(arguments, settings) as opened,
            endpoint(reranker.url, None, RERANKING, remote_allowed=False) as server,
        ):
            listed = served(server)
            score = Counted(functools.partial(rerank, server, reranker.model, bounds=EVALUATION))
            evaluated = EvaluatedIndex(connect(opened, settings.model), settings.chunking)
            arms = Arms(settings.search_mode, depths, score, built_at)
            found = measured(evaluated, settings, questions, arms, time.perf_counter)
    except (ModelError, EvaluationError) as error:
        structlog.get_logger().error("eval.not_evaluated", reason=str(error))
        return ExitStatus.FAILED, None
    decision = depth_verdict(found, questions)
    about: dict[str, object] = {
        "built_at": built_at.isoformat(),
        "mode": settings.search_mode,
        "model": settings.model,
        "chunking": settings.chunking,
        "reranker": reranker.model,
        "served": listed,
        "sample": None
        if arguments.sample is None
        else {"questions": arguments.sample, "seed": arguments.seed},
    }
    results = settings.evaluations / "results" / f"{built_at.strftime(STAMP)}-rerank.json"
    results.parent.mkdir(parents=True, exist_ok=True)
    kept = recorded(found, decision, golden, about)
    results.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    return ExitStatus.OK, DepthsEvaluated(
        arms=found, decision=decision, mode=settings.search_mode, results=results
    )


def arm_row(arm: Arm, group: str) -> str:
    """Write an arm's measures of a group as a row under ``HEADER``, with its times."""
    each, asked = arm.groups[group], arm.asked[group]
    section = "n/a" if each.section is None else f"{each.section:.3f}"
    evidence = "n/a" if asked.evidence is None else f"{asked.evidence:.3f}"
    tokens = "n/a" if arm.tokens is None else f"{arm.tokens:,}"
    median_s, tail_s = arm.times
    return (
        f"| {arm.depth or 'none'} | {group} | {each.recall:.3f} | {each.reciprocal_rank:.3f} |"
        f" {each.ndcg:.3f} | {each.success:.3f} | {section} | {asked.found:.3f} | {evidence} |"
        f" {tokens} | {median_s * 1000:.0f} ms | {tail_s * 1000:.0f} ms |"
    )


def text(evaluated: DepthsEvaluated, detail: Detail) -> str:
    """Write each arm's row, every group's in detail; the first ranking's recall; the bar.

    The bar's verdict says the depth kept, or why there is none; then each depth's
    clauses, by this machine's times, and the depths of the bar not run.
    """
    arms = evaluated.arms
    plain = arms[0]
    groups = sorted(plain.groups, key=lambda name: (name != "all", name))
    lines = [f"## Reranking, {evaluated.mode} mode", "", HEADER, DIVIDER]
    lines += [
        arm_row(arm, group)
        for arm in arms
        for group in (groups if detail == "detailed" else ["all"])
    ]
    recall = ", ".join(f"@{size} {share:.3f}" for size, share in plain.recall.items())
    lines += ["", f"Recall of the order not reranked: {recall}", ""]
    lines += evaluated.decision.lines()
    return "\n".join([*lines, f"Results: {evaluated.results}", ""])
