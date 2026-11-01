"""``sync``: bring the configured sources up to date, each role in turn, then the index."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.app.sources import SourcesRefusedError
from kb_mcp.cli.app.sync import Index, sync
from kb_mcp.cli.commands import embed as embed_command
from kb_mcp.cli.commands import index as index_command
from kb_mcp.cli.commands._embedding import indexing_of, open_endpoint
from kb_mcp.cli.commands._rows import rows_text
from kb_mcp.cli.domain.sources import given
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.cli.domain.sync import chosen
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.roles import Run

if TYPE_CHECKING:
    import argparse

    from kb_mcp.cli.domain.rows import Synced
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.search.app.indexing import Indexed


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
    opening = (
        None if settings.search_mode == "lexical" else partial(open_endpoint, arguments, settings)
    )
    step = Index(indexing=indexing_of(settings, opening))
    try:
        synced = sync(runs, step, lambda: datetime.now(UTC))
    except SourcesRefusedError as error:
        structlog.get_logger().error("sync.refused", reason=str(error))
        return ExitStatus.REFUSED, None
    return synced.exit_status, synced


def index_text(indexed: Indexed, summary: Summary) -> str:
    """Write the index's row as the command that builds such an index does."""
    command = index_command if indexed.model is None else embed_command
    return command.text(indexed, summary)


def text(synced: Synced, summary: Summary) -> str:
    """Write a row per step and source, how it ended, then its result's own text, or index's."""
    return rows_text(synced, summary, {"index": index_text})
