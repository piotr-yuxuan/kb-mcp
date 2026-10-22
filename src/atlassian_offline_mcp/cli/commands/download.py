"""``download``: fetch the documents of spaces and projects updated in a period."""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.fields import RepresentationError
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import StoreBusyError
from atlassian_offline_mcp.sources.atlassian.app.download import Targets, download, plan
from atlassian_offline_mcp.sources.atlassian.domain.period import PeriodError, length, moment

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Settings
    from atlassian_offline_mcp.kernel.output import Summary
    from atlassian_offline_mcp.sources.atlassian.app.download import Outcome

MEBIBYTE = 1024 * 1024
# The counts that a short summary shows: the documents fetched, or to fetch, of each kind,
# and the files downloaded, or to download.
SHORT_COUNTS = (": fetched", ": to fetch", "files: downloaded", "files: to download")


class RefusedOptionsError(ValueError):
    """Options that cannot make a run; the message names the option or setting."""


def targets_of(arguments: argparse.Namespace, settings: Settings, now: datetime) -> Targets:
    """Read what a run downloads from the options and the settings; refuse what cannot run.

    --space and --project are settings' flags, which replace the settings' lists.
    Raises RefusedOptionsError or PeriodError, naming the option at fault.
    """
    spaces = list(settings.sources.confluence.spaces)
    projects = list(settings.sources.jira.projects)
    for problem, refused in (
        ("site: not set; add it to the settings or pass --site", settings.site is None),
        ("nothing to download: name a --space or a --project", not (spaces or projects)),
        ("--max-file-mb: at least 1", arguments.max_file_mb < 1),
    ):
        if refused:
            raise RefusedOptionsError(problem)
    return Targets(
        spaces,
        projects,
        arguments.max_file_mb * MEBIBYTE,
        since=moment(arguments.since, now, "--since") if arguments.since else None,
        back=length(arguments.back, "--back") if arguments.back else None,
        until=moment(arguments.until, now, "--until") if arguments.until else None,
    )


def run(arguments: argparse.Namespace, settings: Settings) -> tuple[ExitStatus, Outcome | None]:
    """Download; exit 0, 1 when something failed, 2 for bad input, 3 to sign in again.

    Spaces and projects not named on the command line come from the settings; without
    --since, each catches up from the start of what earlier runs covered. The outcome
    is given once a run ends, None when none could start or one was stopped.
    """
    try:
        targets = targets_of(arguments, settings, datetime.now(UTC))
        act = plan if arguments.plan else download
        outcome = act(settings, targets, lambda: datetime.now(UTC), time.sleep)
    except (PeriodError, RefusedOptionsError, RepresentationError) as error:
        sys.stderr.write(f"refused: {error}\n")
        return ExitStatus.REFUSED, None
    except StoreBusyError:
        sys.stderr.write("another run is writing the raw store; try again once it ends\n")
        return ExitStatus.FAILED, None
    except KeyboardInterrupt:
        sys.stderr.write(f"interrupted; the counts so far are in {settings.runs}\n")
        return ExitStatus.INTERRUPTED, None
    for target in outcome.failed_targets:
        sys.stderr.write(f"{target}\n")
    if outcome.status == ExitStatus.SIGN_IN_AGAIN:
        sys.stderr.write("sign-in needed: run atlassian-offline-mcp login\n")
    return outcome.status or ExitStatus.OK, outcome


def text(outcome: Outcome, summary: Summary) -> str:
    """Write the documents fetched by kind and the files, or those a dry run would; then failures.

    In detail, every count of what the run did, or would do, comes before the failures.
    """
    shown = [
        (what, number)
        for what, number in sorted(outcome.report.counts.items())
        if summary == "detailed" or what.endswith(SHORT_COUNTS)
    ]
    return "".join(f"{what}: {number}\n" for what, number in shown) + (
        f"failures: {outcome.report.failures}\n"
    )
