"""``mirror``: write the Markdown mirror from the raw store, offline, a source at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.cli.app.sync import Synced, prepare_source
from kb_mcp.cli.commands._rows import rows_text
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.sources.atlassian.prepare.app.prepare import PREPARED

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.atlassian.prepare.app.prepare import Outcome


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Synced | None]:
    """Mirror Confluence, then Jira, a row each; exit 0, or 1 when a row failed or pandoc went.

    The entry refuses a run without pandoc on PATH, exit 2, before anything is asked:
    this run finds it again for its path, and exits 1 only if it went in between, an
    error. Each source's conversions are its rows of the data folder's cache, open for
    its mirror alone. What was not mirrored is a warning, by its place in the raw store
    and the reason, never its content, as is that its source then removed none of its
    files. The rows are given, None without pandoc.
    """
    settings = loaded.settings
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        structlog.get_logger().error("mirror.pandoc_missing", reason=str(error))
        return ExitStatus.FAILED, None
    rows = tuple(prepare_source(settings, pandoc, source) for source in PREPARED)
    status = ExitStatus.FAILED if any(row.outcome == "failed" for row in rows) else ExitStatus.OK
    return status, Synced(exit_status=status, steps=rows)


def outcome_text(outcome: Outcome, summary: Summary) -> str:
    """Write one source's counts under its row, as the outcome's own ``text`` does."""
    return outcome.text(summary)


def text(synced: Synced, summary: Summary) -> str:
    """Write a row per source, as ``sync`` writes its rows: how it ended, then its counts."""
    return rows_text(synced, summary, {"mirror": outcome_text})
