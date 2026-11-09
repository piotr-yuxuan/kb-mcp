"""``index``: update the search index of the mirror's words, never asking any endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._embedding import indexing_of
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.search.app.indexing import OUTCOMES, update_index

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Detail
    from kb_mcp.search.app.indexing import Indexed

# Why an update kept nothing of the index in place, as the detailed summary says it.
WHOLE = {
    "unavailable": "there being none that this version reads",
    "another version": "written by another version",
    "damaged": "it being damaged",
    "--rebuild": "as --rebuild asks",
}


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Indexed | None]:
    """Update the index by words alone; exit 1 when a file is left out, or nothing was built.

    Nothing built is an error, and the index in place stays; each file skipped is a
    warning, as is the count of files that the index lacks, even when nothing changed.
    ``vectors.sqlite`` stays as it is.
    """
    indexing = indexing_of(loaded.settings, None)
    indexed = update_index(indexing, datetime.now(UTC), rebuild=arguments.rebuild)
    return ExitStatus.OK if indexed and indexed.report.whole else ExitStatus.FAILED, indexed


def text(indexed: Indexed, summary: Detail) -> str:
    """Write the documents and sections held, then what changed, or that nothing did.

    Short gives each count, the documents awaiting vectors when the index names a model,
    and why it was rebuilt whole, if it was; detailed says it in a line, as ``detailed``.
    """
    if summary != "short":
        return detailed(indexed)
    report = indexed.report
    lines = [f"documents: {report.types.total()}", f"sections: {report.sections}"]
    lines += (
        ["nothing written"]
        if report.unchanged
        else [f"{name}: {getattr(report, name)}" for name in OUTCOMES]
    )
    lines.append(f"skipped: {len(report.skipped)}")
    lines += [f"rebuilt whole: {report.rebuilt}"] if report.rebuilt else []
    lines += [] if report.awaiting is None else [f"awaiting vectors: {report.awaiting}"]
    return "".join(f"{line}\n" for line in lines)


def detailed(indexed: Indexed) -> str:
    """Say in a line what ``index`` did, with the documents by type, and the index.

    Nothing changed, updated with each count, or rebuilt whole and why; then the files
    skipped, if any, and the documents awaiting vectors, when the index names a model.
    """
    report = indexed.report
    types = ", ".join(f"{name}: {count}" for name, count in sorted(report.types.items()))
    holds = f"{report.types.total()} documents ({types or 'none'}), {report.sections} sections"
    done = ", ".join(f"{getattr(report, name)} {name}" for name in OUTCOMES)
    if report.unchanged:
        written = f"nothing changed: {indexed.index} holds {holds}"
    elif report.rebuilt:
        written = f"rebuilt {indexed.index} whole, {WHOLE[report.rebuilt]}: {holds}"
    else:
        written = f"updated {indexed.index}: documents {done}; it holds {holds}"
    if report.skipped:
        written += f"; {len(report.skipped)} files skipped"
    if report.awaiting is not None:
        written += f"; {report.awaiting} await vectors from kb-mcp embed"
    return f"{written}\n"
