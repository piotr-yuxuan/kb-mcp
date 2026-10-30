"""``download``: fetch the documents of spaces and projects updated in a period."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.options.download import DEFAULT_MAX_FILE_MB
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.sources.atlassian.adapters.raw_store import StoreBusyError
from kb_mcp.sources.atlassian.adapters.sign_in import sign_in
from kb_mcp.sources.atlassian.app.download import Targets, download, plan
from kb_mcp.sources.atlassian.domain.period import PeriodError, moment

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.atlassian.app.download import Outcome

MEBIBYTE = 1024 * 1024
# The counts that a short summary shows: the documents fetched, or to fetch, of each kind,
# and the files downloaded, or to download; then how a run stopped, if it did.
SHORT_COUNTS = (": fetched", ": to fetch", "files: downloaded", "files: to download")
STOPPED = "runs: "


def targets_of(
    arguments: argparse.Namespace, spaces: Sequence[str], projects: Sequence[str], now: datetime
) -> Targets:
    """Read what a run downloads of these spaces and projects from the period's options.

    The options were checked before the run; --max-file-mb not given is the default.
    """
    return Targets(
        spaces=list(spaces),
        projects=list(projects),
        max_file_bytes=(arguments.max_file_mb or DEFAULT_MAX_FILE_MB) * MEBIBYTE,
        since=moment(arguments.since, now, "--since") if arguments.since else None,
        until=moment(arguments.until, now, "--until") if arguments.until else None,
    )


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Outcome | None]:
    """Download; exit 0, 1 when something failed, 2 for bad input, 3 to sign in again.

    --space and --project are settings' flags, which replace the settings' lists; without
    --since, each catches up on what changed since its last fetch. The outcome
    is given once a run ends, None when none could start or one was stopped. Why a run
    could not start or go on is an error; an interruption, or a space or a project that
    failed, a warning.
    """
    settings = loaded.settings
    try:
        sources = settings.sources
        spaces, projects = sources.confluence.spaces, sources.jira.projects
        targets = targets_of(arguments, spaces, projects, datetime.now(UTC))
        act = plan if arguments.dry_run else download
        outcome = act(settings, targets, lambda: datetime.now(UTC), time.sleep)
    except (PeriodError, RepresentationError) as error:
        structlog.get_logger().error("download.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    except StoreBusyError:
        structlog.get_logger().error(
            "download.store_busy",
            store=str(settings.raw),
            hint="another run is writing it; try again once that run ends",
        )
        return ExitStatus.FAILED, None
    except KeyboardInterrupt:
        structlog.get_logger().warning("download.interrupted", counts=str(settings.runs))
        return ExitStatus.INTERRUPTED, None
    for target in outcome.failed_targets:
        structlog.get_logger().warning("download.target_failed", target=target)
    if outcome.status == ExitStatus.SIGN_IN_AGAIN:
        structlog.get_logger().error("download.sign_in_needed", hint=sign_in(settings).again)
    return outcome.status or ExitStatus.OK, outcome


def text(outcome: Outcome, summary: Summary) -> str:
    """Write the documents fetched by kind and the files, or those a dry run would; then failures.

    Detailed, and a dry run, begin with each target's window, why it starts there, and
    what became of its coverage. Short also says how a run stopped, if it did; detailed
    gives every count of what the run did, or would do. The failures come last.
    """
    windows = outcome.windows if summary == "detailed" or outcome.dry_run else ()
    said = [
        f"{each.target}: "
        + (
            f"skipped, {each.reason}"
            if each.start is None or each.end is None
            else f"from {each.start.isoformat()} to {each.end.isoformat()}, {each.reason}"
        )
        + ("" if each.coverage is None else f"; coverage {each.coverage}")
        for each in windows
    ]
    shown = [
        (what, number)
        for what, number in sorted(outcome.report.counts.items())
        if summary == "detailed" or what.endswith(SHORT_COUNTS) or what.startswith(STOPPED)
    ]
    return (
        "".join(f"{line}\n" for line in said)
        + "".join(f"{what}: {number}\n" for what, number in shown)
        + f"failures: {outcome.report.failures}\n"
    )
