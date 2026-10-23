"""``eval-agents``: prepare runs for agents, bridge their calls, keep their answers, grade.

Each step's run is the one that ``run`` dispatches to by the step parsed. ``call`` and
``answer``, which the agents run, read no settings but where their logs and telemetry
go, and ask nothing; ``call`` writes the tool's answer alone on stdout.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from atlassian_offline_mcp.cli.domain.eval_agents import (
    CALL_S,
    CALLS,
    HANDED,
    INPUT,
    OUTPUT,
    PAST,
)
from atlassian_offline_mcp.evaluation.adapters.mcp_client import ServerError
from atlassian_offline_mcp.evaluation.app.agents import (
    AgentsError,
    Asking,
    Called,
    Results,
    answer,
    call,
    chosen,
    concluded,
    judged,
    prepare,
    readied,
)
from atlassian_offline_mcp.evaluation.app.evaluation import GoldenError, read_golden
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.tools import TOOLS
from atlassian_offline_mcp.mcp.app.tools import Library, UnanswerableError
from atlassian_offline_mcp.mirror.adapters import markdown
from atlassian_offline_mcp.observability.adapters.progress import task

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.evaluation.domain.grading import Answer
    from atlassian_offline_mcp.kernel.output import Summary

# The command line that reaches this program, from the agents and for the server.
PROGRAM = (sys.executable, "-m", "atlassian_offline_mcp")


@dataclass(frozen=True)
class Prepared:
    """The runs that ``prepare`` wrote, or would write with --dry-run, and where."""

    runs: int
    directory: Path
    written: bool


def prepared(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Prepared | None]:
    """Write the runs' directory; exit 2 for a refused golden file, sample or directory.

    Exit 1 when a surface's server lists nothing.
    """
    settings = loaded.settings
    try:
        golden = arguments.golden.read_text(encoding="utf-8")
        questions = read_golden(golden, Library(settings.index, settings.docs).resolve)
        asked = chosen(questions, arguments.sample, arguments.seed)
    except (GoldenError, OSError, UnanswerableError, AgentsError) as error:
        structlog.get_logger().error("eval.agent.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    if arguments.dry_run:
        return ExitStatus.OK, Prepared(2 * len(asked), arguments.out, written=False)
    # The server reads the settings as this run did: the same file, the same variables,
    # and the data directory given here, if one was.
    given = ("--data-dir", str(settings.data_dir)) if arguments.data_dir else ()
    remote = ("--allow-remote-embeddings",) if arguments.allow_remote_embeddings else ()
    config = arguments.config.expanduser().absolute()
    asking = Asking(
        model=arguments.model,
        golden_sha256=hashlib.sha256(golden.encode()).hexdigest(),
        program=(*PROGRAM, "eval-agents"),
        server=(
            *PROGRAM,
            "serve",
            "--config",
            str(config),
            *given,
            *remote,
        ),
        calls=CALLS,
        call_s=CALL_S,
        home=Path.home().resolve(),
    )
    try:
        runs = prepare(asked, arguments.out, asking, TOOLS)
    except AgentsError as error:
        structlog.get_logger().error("eval.agent.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    except (TimeoutError, ServerError) as error:
        structlog.get_logger().error(
            "eval.agent.not_prepared", reason=f"a surface's server listed nothing ({error!r})"
        )
        return ExitStatus.FAILED, None
    return ExitStatus.OK, Prepared(len(runs.runs), arguments.out, written=True)


def bridged(arguments: argparse.Namespace, _loaded: Loaded) -> tuple[ExitStatus, Called | None]:
    """Make one call of a run; exit 2 for a refused call, 1 when the server did not answer."""
    try:
        done = call(arguments.directory, arguments.run, arguments.tool, arguments.arguments)
    except AgentsError as error:
        structlog.get_logger().error("eval.agent.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    failed = done.status in {"timeout", "failed"}
    return ExitStatus.FAILED if failed else ExitStatus.OK, done


def answered(arguments: argparse.Namespace, _loaded: Loaded) -> tuple[ExitStatus, Answer | None]:
    """Keep a run's answer; exit 2 when it is refused, or one is kept already."""
    try:
        kept = answer(arguments.directory, arguments.run, arguments.answer)
    except AgentsError as error:
        structlog.get_logger().error("eval.agent.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    return ExitStatus.OK, kept


def graded(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Results | None]:
    """Grade the runs and judge ask; exit 2 for a refused file, 1 past twice the estimates.

    Refs resolve as read resolves them, and quotes are sought in the mirror's bodies.
    The task ``runs`` reports the runs judged, each by its id.
    """
    settings = loaded.settings
    library = Library(settings.index, settings.docs)

    def body(path: str) -> str:
        text = (settings.docs / path).read_text(encoding="utf-8", newline="")
        return markdown.load(text, path)[1]

    try:
        runs = readied(arguments.directory)
        with task("runs", len(runs.runs)) as judging:
            outcomes = [
                judged(arguments.directory, run, runs.question(run.question), library.resolve, body)
                for run in judging.each(runs.runs, lambda one: one.id)
            ]
    except (AgentsError, UnanswerableError) as error:
        structlog.get_logger().error("eval.agent.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    results = concluded(arguments.directory, runs, outcomes)
    done = [outcome for outcome in outcomes if outcome.result != "pending"]
    handed = sum(outcome.handed for outcome in done)
    spent = sum(outcome.model_tokens or 0 for outcome in done)
    if handed > PAST * HANDED * len(done) or spent > PAST * (INPUT + OUTPUT) * len(done):
        structlog.get_logger().error(
            "eval.agent.past_estimates",
            times=PAST,
            handed=handed,
            model_tokens=spent,
            hint="stop the runs, and set the estimates from these",
        )
        return ExitStatus.FAILED, results
    return ExitStatus.OK, results


STEPS: dict[str, Callable[[argparse.Namespace, Loaded], tuple[ExitStatus, object]]] = {
    "prepare": prepared,
    "call": bridged,
    "answer": answered,
    "grade": graded,
}


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, object]:
    """Run the step parsed."""
    return STEPS[arguments.step](arguments, loaded)


def text(result: object, summary: Summary) -> str:
    """Write a step's result: the runs prepared, a tool's answer alone, an answer kept, a grading.

    A grading gives the runs counted, B against A on each measure, the verdict on ask,
    and in detail each run.
    """
    match result:
        case Prepared(written=True):
            return f"{result.runs} runs prepared in {result.directory}: runs.json, prompts/\n"
        case Prepared():
            return f"{result.runs} runs would be prepared in {result.directory}\n"
        case Results():
            counted = ", ".join(f"{name} {count}" for name, count in result.counted.items())
            lines = [
                (
                    f"runs: {counted or 'none'}; questions in the tests: {result.pairs}; left"
                    f" out, a run without a result: {result.left_out}"
                ),
                *(
                    f"{name}, B with ask against A without: {each.difference:+.3f}"
                    f" [{each.interval[0]:+.3f}, {each.interval[1]:+.3f}], p = {each.pvalue:.4f},"
                    f" adjusted (Holm) {each.adjusted:.4f}"
                    for name, each in result.verdict.differences.items()
                ),
                "ask stays among the default tools"
                if result.verdict.keeps_ask
                else "ask leaves the default tools: B's success is lower",
            ]
            lines += [
                f"{each.run} {each.question} {each.surface}: {each.result}"
                f"{f' ({each.reason})' if each.reason else ''}; calls: {made or 'none'};"
                f" {each.handed:,} tokens handed over; {each.seconds:.1f} s"
                for each in result.outcomes
                if summary == "detailed"
                for made in [", ".join(f"{tool} {count}" for tool, count in each.calls.items())]
            ]
            return "\n".join([*lines, ""])
        case Called():
            return f"{result.text}\n"
        case _:
            return "the answer is kept\n"
