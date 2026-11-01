"""``index``: build the search index of the mirror's words, never asking any endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._embedding import indexing_of
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.search.app.indexing import refresh

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.search.app.indexing import Indexed


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Indexed | None]:
    """Build the index by words alone; exit 1 when a file was left out, or nothing was built.

    Nothing built is an error, and the index in place stays; each file skipped is a
    warning, as is the count of files that the index lacks. ``vectors.sqlite`` stays as
    it is.
    """
    indexed = refresh(indexing_of(loaded.settings, None), datetime.now(UTC))
    return ExitStatus.OK if indexed and indexed.report.whole else ExitStatus.FAILED, indexed


def text(indexed: Indexed, summary: Summary) -> str:
    """Write the documents indexed and their sections; in detail, by type, and the index."""
    report = indexed.report
    if summary == "short":
        return f"documents: {report.types.total()}\nsections: {report.sections}\n"
    types = ", ".join(f"{name}: {count}" for name, count in sorted(report.types.items()))
    return (
        f"indexed {report.types.total()} documents ({types or 'none'}),"
        f" {report.sections} sections, into {indexed.index}\n"
    )
