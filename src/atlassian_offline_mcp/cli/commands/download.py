"""``download``: fetch the documents of spaces and projects updated in a period."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.fields import RepresentationError
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import StoreBusyError
from atlassian_offline_mcp.sources.atlassian.adapters.sign_in import sign_in
from atlassian_offline_mcp.sources.atlassian.app.download import Targets, download, plan
from atlassian_offline_mcp.sources.atlassian.domain.period import PeriodError, length, moment

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded, Settings
    from atlassian_offline_mcp.kernel.output import Summary
    from atlassian_offline_mcp.sources.atlassian.app.download import Outcome

MEBIBYTE = 1024 * 1024
# The counts that a short summary shows: the documents fetched, or to fetch, of each kind,
# and the files downloaded, or to download; then how a run stopped, if it did.
SHORT_COUNTS = (": fetched", ": to fetch", "files: downloaded", "files: to download")
STOPPED = "runs: "


def targets_of(arguments: argparse.Namespace, settings: Settings, now: datetime) -> Targets:
    """Read what a run downloads from the options and the settings, checked before the run.

    --space and --project are settings' flags, which replace the settings' lists.
    """
    return Targets(
        list(settings.sources.confluence.spaces),
        list(settings.sources.jira.projects),
        arguments.max_file_mb * MEBIBYTE,
        since=moment(arguments.since, now, "--since") if arguments.since else None,
        back=length(arguments.back, "--back") if arguments.back else None,
        until=moment(arguments.until, now, "--until") if arguments.until else None,
    )


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Outcome | None]:
    """Download; exit 0, 1 when something failed, 2 for bad input, 3 to sign in again.

    Spaces and projects not named on the command line come from the settings; without
    --since, each catches up from the start of what earlier runs covered. The outcome
    is given once a run ends, None when none could start or one was stopped. Why a run
    could not start or go on is an error; an interruption, or a space or a project that
    failed, a warning.
    """
    settings = loaded.settings
    try:
        targets = targets_of(arguments, settings, datetime.now(UTC))
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

    Short also says how a run stopped, if it did; detailed gives every count of what the
    run did, or would do. The failures come last.
    """
    shown = [
        (what, number)
        for what, number in sorted(outcome.report.counts.items())
        if summary == "detailed" or what.endswith(SHORT_COUNTS) or what.startswith(STOPPED)
    ]
    return "".join(f"{what}: {number}\n" for what, number in shown) + (
        f"failures: {outcome.report.failures}\n"
    )
