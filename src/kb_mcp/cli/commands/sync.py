"""``sync``: bring the configured sources up to date, each step in turn."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.app.sync import (
    Atlassian,
    Context,
    Index,
    SyncRefusedError,
    Worklog,
    sync,
)
from kb_mcp.cli.commands import download as download_command
from kb_mcp.cli.commands import index as index_command
from kb_mcp.cli.commands import mirror as mirror_command
from kb_mcp.cli.commands._embedding import indexing_of
from kb_mcp.cli.commands._rows import rows_text
from kb_mcp.cli.commands.download import targets_of
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.cli.domain.sync import chosen
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.fetch.domain.period import PeriodError
from kb_mcp.sources.atlassian.prepare.app.prepare import PREPARED

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from kb_mcp.cli.domain.rows import Synced
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.worklog.prepare.app.prepare import Outcome, Planned


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Synced | None]:
    """Sync the sources chosen, then index the mirror; exit as the rows rank, 2 when refused.

    The entry refused what it could before asking. An --until before --since, or a work
    log that is not a folder, is refused here, before any step runs, an error,
    ``sync.refused``, as is pandoc gone from PATH since, ``sync.pandoc_missing``. Each
    step's problems are said as it runs, by place and reason, never content.
    """
    settings = loaded.settings
    taken, _ = chosen(arguments, values_of(loaded))
    names = {source.name for source in taken}
    sources = settings.sources
    spaces = sources.confluence.spaces if "confluence" in names else ()
    projects = sources.jira.projects if "jira" in names else ()
    folder = sources.worklog.path if "worklog" in names else None
    try:
        context = Context(
            settings=settings,
            pandoc=Pandoc.find(),
            now=lambda: datetime.now(UTC),
            sleep=time.sleep,
            dry_run=arguments.dry_run,
        )
        steps: list[Atlassian | Worklog | Index] = []
        if spaces or projects:
            targets = targets_of(arguments, spaces, projects, context.now())
            prepared = tuple(source for source in PREPARED if source in names)
            steps.append(Atlassian(targets=targets, sources=prepared))
        if folder is not None:
            steps.append(Worklog(folder=folder, archives=sources.worklog.archives))
        steps.append(Index(indexing=indexing_of(arguments, settings)))
        synced = sync(context, steps)
    except (PeriodError, RepresentationError, SyncRefusedError) as error:
        structlog.get_logger().error("sync.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    except PandocMissingError as error:
        structlog.get_logger().error("sync.pandoc_missing", reason=str(error))
        return ExitStatus.FAILED, None
    return synced.exit_status, synced


def worklog_text(result: Outcome | Planned, summary: Summary) -> str:
    """Write the work log's counts, or a dry run's, as the result's own ``text`` does."""
    return result.text(summary)


# How each step's result is written, as its own command writes it.
TEXTS: dict[str, Callable[..., str]] = {
    "download": download_command.text,
    "mirror": mirror_command.outcome_text,
    "worklog": worklog_text,
    "index": index_command.text,
}


def text(synced: Synced, summary: Summary) -> str:
    """Write a row per step and source, how it ended, then its result as its command does."""
    return rows_text(synced, summary, TEXTS)
