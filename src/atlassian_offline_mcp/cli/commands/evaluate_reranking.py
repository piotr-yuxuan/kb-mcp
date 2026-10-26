"""``eval-rerank``: measure search reranked at each depth on golden questions, by the bar."""

from __future__ import annotations

import functools
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from atlassian_offline_mcp.cli.commands._embedding import open_endpoint
from atlassian_offline_mcp.evaluation.app.evaluation import (
    EvaluationError,
    GoldenError,
    Target,
    read_golden,
)
from atlassian_offline_mcp.evaluation.app.reranked import (
    Arms,
    Counted,
    decided,
    measured,
    recorded,
)
from atlassian_offline_mcp.evaluation.domain.reranking import GROUPS
from atlassian_offline_mcp.kernel.endpoint import RERANKING
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.reranking import BAR_DEPTHS, BOUND_S
from atlassian_offline_mcp.mcp.app.tools import Library, UnanswerableError
from atlassian_offline_mcp.search.adapters.embedding import connect
from atlassian_offline_mcp.search.adapters.model_api import ModelError, endpoint
from atlassian_offline_mcp.search.adapters.reranking import EVALUATION, rerank, served

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.evaluation.app.reranked import Arm
    from atlassian_offline_mcp.evaluation.domain.reranking import Decision
    from atlassian_offline_mcp.kernel.output import Summary

STAMP = "%Y%m%dT%H%M%SZ"
HEADER = (
    "| Depth | Group | Recall@10 | MRR@10 | nDCG@10 | Success@1 | Section@10 | Found@ask"
    " | Evidence@ask | Tokens | Search, median | Search, 95th |"
)
DIVIDER = "|---|---|---|---|---|---|---|---|---|---|---|---|"


@dataclass(frozen=True)
class Evaluated:
    """Each arm measured, the bar's decision, the mode, and the results file."""

    arms: list[Arm]
    decision: Decision | None
    mode: str
    results: Path


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Evaluated | None]:
    """Measure each depth; exit 1 on a failure, 2 for a refused golden file.

    The setting's model, chunking and search mode are measured, reranked by the setting's
    reranker. The results, ids and numbers only, go to
    ``<data>/eval/results/<UTC time>-rerank.json``.
    """
    settings = loaded.settings
    try:
        golden = arguments.golden.read_text(encoding="utf-8")
        questions = read_golden(golden, Library(settings.index, settings.docs).resolve)
    except (GoldenError, OSError, UnanswerableError) as error:
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
            target = Target(connect(opened, settings.model), settings.chunking)
            arms = Arms(settings.search_mode, depths, score, built_at)
            found = measured(target, settings, questions, arms, time.perf_counter)
    except (ModelError, EvaluationError) as error:
        structlog.get_logger().error("eval.not_evaluated", reason=str(error))
        return ExitStatus.FAILED, None
    decision = decided(found, questions)
    about: dict[str, object] = {
        "built_at": built_at.isoformat(),
        "mode": settings.search_mode,
        "model": settings.model,
        "chunking": settings.chunking,
        "reranker": reranker.model,
        "served": listed,
    }
    results = settings.evaluations / "results" / f"{built_at.strftime(STAMP)}-rerank.json"
    results.parent.mkdir(parents=True, exist_ok=True)
    kept = recorded(found, decision, golden, about)
    results.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    return ExitStatus.OK, Evaluated(found, decision, settings.search_mode, results)


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


def text(evaluated: Evaluated, summary: Summary) -> str:
    """Write each arm's row, every group's in detail; the first stage's recall; the bar.

    The bar's verdicts come depth by depth, each clause said with the groups' losses,
    then each qualifying depth's p-value against the best, then the default depth or
    that reranking stays off, by this machine's times; with depths other than the bar's,
    that there is no verdict.
    """
    arms = evaluated.arms
    plain = arms[0]
    groups = sorted(plain.groups, key=lambda name: (name != "all", name))
    lines = [f"## Reranking, {evaluated.mode} mode", "", HEADER, DIVIDER]
    lines += [
        arm_row(arm, group)
        for arm in arms
        for group in (groups if summary == "detailed" else ["all"])
    ]
    recall = ", ".join(f"@{size} {share:.3f}" for size, share in plain.recall.items())
    lines += ["", f"Recall of the order not reranked: {recall}", ""]
    decision = evaluated.decision
    if decision is None:
        bar = ", ".join(map(str, BAR_DEPTHS))
        lines.append(f"No verdict: the bar decides on depths {bar} alone.")
    else:
        losses = {
            each.depth: ", ".join(
                f"{name} {each.losses[name]:.3f}" if name in each.losses else f"{name} n/a"
                for name in GROUPS
            )
            for each in decision.verdicts
        }
        lines += [
            f"Depth {each.depth}: MRR@10 adjusted p = {each.adjusted:.4f}; gains"
            f" {'yes' if each.beats else 'no'}; groups lose {losses[each.depth]},"
            f" hold {'yes' if each.holds else 'no'};"
            f" within {BOUND_S:g} s here {'yes' if each.fast else 'no'}"
            for each in decision.verdicts
        ]
        lines += [
            f"Depth {depth} against the best qualifying: MRR@10 p = {pvalue:.4f}"
            for depth, pvalue in decision.against_best.items()
        ]
        chosen = decision.depth
        lines.append(
            f"By the bar, with this machine's times: rerank {chosen} documents."
            if chosen
            else "By the bar, with this machine's times: reranking stays off."
        )
    return "\n".join([*lines, f"Results: {evaluated.results}", ""])
