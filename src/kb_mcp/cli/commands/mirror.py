"""``mirror``: write the Markdown mirror from the raw store, offline, a source at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.commands._rows import rows_text
from kb_mcp.cli.domain.rows import Synced, SyncRow
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.prepare.app.prepare import PREPARED
from kb_mcp.sources.atlassian.prepare.app.preparer import prepare_kinds

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Synced | None]:
    """Mirror Confluence, then Jira, a row each; exit 0, or 1 when a row failed or pandoc went.

    The entry refuses a run without pandoc on PATH, exit 2, before anything is asked:
    this run finds it again for its path, and exits 1 only if it went in between, an
    error. Each source mirrors as ``prepare_kinds`` does, through its rows of the data
    folder's cache, with the site of the Atlassian account. What was not mirrored is a
    warning, by its place in the raw store and the reason, never its content, as is that
    its source then removed none of its files. The rows are given, None without pandoc.
    """
    settings = loaded.settings
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        structlog.get_logger().error("mirror.pandoc_missing", reason=str(error))
        return ExitStatus.FAILED, None
    site = settings.accounts.atlassian.site
    prepared = {
        source: prepare_kinds(settings, site, pandoc, source, kinds)
        for source, kinds in PREPARED.items()
    }
    rows = tuple(
        SyncRow(step="mirror", source=source, outcome=each.outcome, result=each.mirrored)
        for source, each in prepared.items()
    )
    status = ExitStatus.FAILED if any(row.outcome == "failed" for row in rows) else ExitStatus.OK
    return status, Synced(exit_status=status, steps=rows)


def text(synced: Synced, summary: Summary) -> str:
    """Write a row per source, as ``sync`` writes its rows: how it ended, then its counts."""
    return rows_text(synced, summary, {})
