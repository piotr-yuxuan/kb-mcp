"""``index``: build the search index from the Markdown mirror, with the setting's model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._embedding import indexing_of, prefixes_said
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.search.app.indexing import index_mirror

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary
    from atlassian_offline_mcp.search.app.indexing import Indexed


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Indexed | None]:
    """Build the index; exit 1 when a file or a piece was left out, or nothing was built.

    By words alone in the lexical mode, which never calls the embedding endpoint. In the
    other modes the endpoint must answer with the setting's model; when it does not,
    the index in place stays, with its vectors, and nothing is given. Nothing built is
    an error; each file skipped and each piece that the endpoint refused is a warning,
    as is the count of files that the index lacks.
    """
    indexed = index_mirror(indexing_of(arguments, loaded.settings), datetime.now(UTC))
    return ExitStatus.OK if indexed and indexed.report.whole else ExitStatus.FAILED, indexed


def text(indexed: Indexed, summary: Summary) -> str:
    """Write the documents indexed and their sections; then the pieces by meaning, if any.

    Short gives their counts and the texts embedded now. Detailed gives the documents by
    type, the index, and the model with its prefixes.
    """
    report = indexed.report
    if summary == "short":
        written = f"documents: {report.types.total()}\nsections: {report.sections}\n"
        if indexed.model is not None:
            written += f"pieces: {report.pieces}\nembedded now: {report.embedded}\n"
        return written
    types = ", ".join(f"{name}: {count}" for name, count in sorted(report.types.items()))
    written = (
        f"indexed {report.types.total()} documents ({types or 'none'}),"
        f" {report.sections} sections, into {indexed.index}\n"
    )
    if indexed.model is not None:
        written += (
            f"{report.pieces} pieces by meaning, with {indexed.model}"
            f" ({prefixes_said(indexed.model)}); {report.embedded} embedded now,"
            " the others kept\n"
        )
    return written
