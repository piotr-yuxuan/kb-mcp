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

# Bytes in a megabyte, as the summary says the vector store's size.
MB = 1_000_000
# What a vector store made before plan 023 does with the pages that a prune frees.
SHRINKS_NOT = (
    "; made before plan 023, it never shrinks: its free pages serve later writes, and"
    " deleting it once, at the cost of a full embedding, gives a store that does"
)


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

    Short gives their counts and the texts embedded now, then the vectors that the prune
    deleted and the vector store's size. Detailed gives the documents by type, the index,
    the model with its prefixes, then what the prune kept and deleted, or why it did not.
    """
    report, pruned = indexed.report, indexed.pruned
    briefly = (
        ""
        if pruned is None
        else f"vectors pruned: none, {pruned.outcome}\n"
        if pruned.outcome != "pruned"
        else f"vectors pruned: {pruned.deleted}\nvector store: {pruned.bytes_after / MB:.1f} MB\n"
    )
    fully = (
        ""
        if pruned is None
        else (
            f"vector store not pruned, {pruned.outcome}: {pruned.reason}"
            + (f" ({pruned.file})\n" if pruned.file else "\n")
        )
        if pruned.outcome != "pruned"
        else (
            f"kept {pruned.kept} vectors ({pruned.kept_for_evaluation} for the evaluation"
            f" alone), pruned {pruned.deleted}; the vector store from"
            f" {pruned.bytes_before / MB:.1f} to {pruned.bytes_after / MB:.1f} MB in"
            f" {pruned.seconds:.1f} s"
            + ("" if pruned.shrinks else SHRINKS_NOT)
            + (
                ""
                if pruned.reclaimed or not pruned.shrinks
                else f"; space not reclaimed: {pruned.reason}"
            )
            + "\n"
        )
    )
    if summary == "short":
        written = f"documents: {report.types.total()}\nsections: {report.sections}\n"
        if indexed.model is not None:
            written += f"pieces: {report.pieces}\nembedded now: {report.embedded}\n"
        return written + briefly
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
    return written + fully
