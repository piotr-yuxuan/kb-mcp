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
from kb_mcp.cli.commands.download import targets_of
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.cli.domain.sync import chosen
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.mirror.app.worklog import Planned
from kb_mcp.sources.atlassian.domain.period import PeriodError

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from kb_mcp.cli.app.sync import Synced
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.mirror.app.worklog import Outcome


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
            settings,
            Pandoc.find(),
            lambda: datetime.now(UTC),
            time.sleep,
            dry_run=arguments.dry_run,
        )
        steps: list[Atlassian | Worklog | Index] = []
        if spaces or projects:
            steps.append(Atlassian(targets_of(arguments, spaces, projects, context.now())))
        if folder is not None:
            steps.append(Worklog(folder, sources.worklog.archives))
        steps.append(Index(indexing_of(arguments, settings)))
        synced = sync(context, steps)
    except (PeriodError, RepresentationError, SyncRefusedError) as error:
        structlog.get_logger().error("sync.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    except PandocMissingError as error:
        structlog.get_logger().error("sync.pandoc_missing", reason=str(error))
        return ExitStatus.FAILED, None
    return synced.exit_status, synced


def worklog_text(result: Outcome | Planned, summary: Summary) -> str:
    """Write the work log's counts: of documents, files, HTML transcripts left out, problems.

    A dry run's are those it would convert and remove. In detail, each warning comes
    before the problems.
    """
    if isinstance(result, Planned):
        counts = [("to convert", result.to_convert), ("files to remove", result.to_remove)]
    else:
        changes = result.changes
        counts = [
            ("files written", changes.written),
            ("files unchanged", changes.unchanged),
            ("files removed", changes.removed),
        ]
    warnings = result.warnings if summary == "detailed" else ()
    return (
        f"documents: {result.documents}\n"
        + "".join(f"{what}: {number}\n" for what, number in counts)
        + f"HTML left out: {result.html}\n"
        + "".join(f"warning: {warning}\n" for warning in warnings)
        + f"problems: {len(result.problems)}\n"
    )


# How each step's result is written, as its own command writes it.
TEXTS: dict[str, Callable[..., str]] = {
    "download": download_command.text,
    "mirror": mirror_command.text,
    "worklog": worklog_text,
    "index": index_command.text,
}


def text(synced: Synced, summary: Summary) -> str:
    """Write a row per step, how it ended, then its result as its command writes it."""
    written: list[str] = []
    for row in synced.steps:
        written.append(f"{row.step}: {row.outcome}\n")
        if row.result is not None:
            shown = TEXTS[row.step](row.result, summary).splitlines()
            written.extend(f"  {line}\n" for line in shown)
    return "".join(written)
