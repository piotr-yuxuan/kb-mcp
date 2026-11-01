"""``sync``: bring the configured sources up to date, each role in turn, then the index."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.app.sync import Index, SyncRefusedError, sync
from kb_mcp.cli.commands import index as index_command
from kb_mcp.cli.commands._embedding import indexing_of
from kb_mcp.cli.commands._rows import rows_text
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.cli.domain.sync import chosen, given
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.roles import Run

if TYPE_CHECKING:
    import argparse

    from kb_mcp.cli.domain.rows import Synced
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Synced | None]:
    """Sync the sources chosen, then index the mirror; exit as the rows rank, 2 when refused.

    The entry refused what it could before asking. Each source taken is run with its
    table, its account's, and its options' values by flag. A role that does not load, or
    what a role's ``preflight`` refuses, such as an --until before --since, or a work
    log that is not a folder, is refused here, before any row runs, an error,
    ``sync.refused``. Each row's problems are said as it runs, by place and reason,
    never content.
    """
    settings = loaded.settings
    taken, _ = chosen(arguments, values_of(loaded))
    runs = [
        Run(
            declared=declared,
            settings=settings,
            table=getattr(settings.sources, declared.name),
            account=(
                None
                if declared.account is None
                else getattr(settings.accounts, declared.account.name)
            ),
            options=given(arguments, declared.options),
            now=lambda: datetime.now(UTC),
            sleep=time.sleep,
            dry_run=arguments.dry_run,
        )
        for declared in taken
    ]
    step = Index(indexing=indexing_of(arguments, settings))
    try:
        synced = sync(runs, step, lambda: datetime.now(UTC), dry_run=arguments.dry_run)
    except SyncRefusedError as error:
        structlog.get_logger().error("sync.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    return synced.exit_status, synced


def text(synced: Synced, summary: Summary) -> str:
    """Write a row per step and source, how it ended, then its result's own text, or index's."""
    return rows_text(synced, summary, {"index": index_command.text})
