"""``download``: fetch the documents of spaces and projects updated in a period."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.commands._rows import rows_text
from kb_mcp.cli.domain.rows import Row, Synced
from kb_mcp.cli.domain.sync import PERIOD, RANKED
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.sources.atlassian.fetch.app.download import read_targets
from kb_mcp.sources.atlassian.fetch.app.fetcher import fetch_targets
from kb_mcp.sources.atlassian.fetch.domain.period import PeriodError

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.cli.domain.sync import Outcome as RowOutcome
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


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Synced | None]:
    """Download Confluence's spaces, then Jira's projects, a row each; exit as the rows rank.

    --space and --project are settings' flags, which replace the settings' lists; without
    --since, each catches up on what changed since its last fetch. Each source with
    targets is fetched on its own, as ``fetch_targets`` fetches, and says what went
    wrong; the exit status is the first of ``RANKED``'s outcomes that a row had: 3 to
    sign in again, 1 when something failed, else 0. A period that does not read, or a
    record of what is covered that does not, is refused by the first fetch before any
    request, exit 2, an error; Ctrl-C is a warning, exit 130. The rows are given once
    every fetch ends, None when refused or stopped.
    """
    settings = loaded.settings
    sources = settings.sources
    rows: list[Row] = []
    try:
        targets = targets_of(
            arguments, sources.confluence.spaces, sources.jira.projects, datetime.now(UTC)
        )
        for source, each in targets.by_source().items():
            fetched = fetch_targets(
                settings, each, lambda: datetime.now(UTC), time.sleep, dry_run=arguments.dry_run
            )
            rows.append(
                Row(
                    step="download",
                    source=source,
                    outcome=fetched.outcome,
                    result=fetched.downloaded,
                )
            )
    except (PeriodError, RepresentationError) as error:
        structlog.get_logger().error("download.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    except KeyboardInterrupt:
        structlog.get_logger().warning("download.interrupted", counts=str(settings.runs))
        return ExitStatus.INTERRUPTED, None
    outcomes: set[RowOutcome] = {row.outcome for row in rows}
    status = next((status for outcome, status in RANKED if outcome in outcomes), ExitStatus.OK)
    return status, Synced(exit_status=status, steps=tuple(rows))


def outcome_text(outcome: Outcome, summary: Summary) -> str:
    """Write one source's counts under its row, as the outcome's own ``text`` does."""
    return outcome.text(summary)


def text(synced: Synced, summary: Summary) -> str:
    """Write a row per source, as ``sync`` writes its rows: how it ended, then its counts."""
    return rows_text(synced, summary, {"download": outcome_text})
