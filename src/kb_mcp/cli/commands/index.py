"""``index``: update the search index of the mirror's words, never asking any endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._embedding import indexing_of
from kb_mcp.kernel.exit_status import ENDED, ExitStatus
from kb_mcp.search.app.indexing import update_index

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.outcome import Outcome
    from kb_mcp.kernel.output import Detail
    from kb_mcp.search.app.indexing import IndexCounts


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Outcome[IndexCounts]]:
    """Update the index by words alone; exit as its outcome ends, 1 for a file left out.

    Nothing built is an error, and the index in place stays; each file skipped is a
    problem, as is the count of files that the index lacks, even when nothing changed.
    ``vectors.sqlite`` stays as it is.
    """
    indexing = indexing_of(loaded.settings, None)
    outcome = update_index(indexing, datetime.now(UTC), rebuild=arguments.rebuild)
    return ENDED[outcome.ending], outcome


def text(outcome: Outcome[IndexCounts], detail: Detail) -> str:
    """Write the outcome: its counts, then its problems and warnings."""
    return outcome.text(detail)
