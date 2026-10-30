"""``download``: fetch the documents of spaces and projects updated in a period."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.domain.sync import PERIOD
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import StoreBusyError
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import sign_in
from kb_mcp.sources.atlassian.fetch.app.download import download, plan, read_targets
from kb_mcp.sources.atlassian.fetch.domain.period import PeriodError

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.atlassian.fetch.app.download import Outcome, Targets


def targets_of(
    arguments: argparse.Namespace, spaces: Sequence[str], projects: Sequence[str], now: datetime
) -> Targets:
    """Read what a run downloads of these spaces and projects from the period's options.

    The options were checked before the run, and read as ``read_targets`` reads them.
    """
    options = {option: getattr(arguments, dest) for dest, option in PERIOD.items()}
    return read_targets(spaces, projects, options, now)


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
    """Write the outcome as its own ``text`` does: counts, failures, and each window."""
    return outcome.text(summary)
