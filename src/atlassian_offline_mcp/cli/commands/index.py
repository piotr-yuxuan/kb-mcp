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
    from atlassian_offline_mcp.search.app.pruning import Pruned

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


def prune_text(pruned: Pruned | None, summary: Summary) -> str:
    """Say what the prune that followed a build by meaning did; nothing by words alone.

    Short gives the vectors deleted and the vector store's size. Detailed gives the
    vectors kept, of which for the evaluation alone, those deleted, the store's size
    before and after, and whether it gives space back; or why it did not prune.
    """
    if pruned is None:
        return ""
    if summary == "short":
        if pruned.outcome != "pruned":
            return f"vectors pruned: none, {pruned.outcome}\n"
        return f"vectors pruned: {pruned.deleted}\nvector store: {pruned.bytes_after / MB:.1f} MB\n"
    if pruned.outcome != "pruned":
        place = f" ({pruned.file})" if pruned.file else ""
        return f"vector store not pruned, {pruned.outcome}: {pruned.reason}{place}\n"
    written = (
        f"kept {pruned.kept} vectors ({pruned.kept_for_evaluation} for the evaluation"
        f" alone), pruned {pruned.deleted}; the vector store from"
        f" {pruned.bytes_before / MB:.1f} to {pruned.bytes_after / MB:.1f} MB in"
        f" {pruned.seconds:.1f} s"
    )
    if not pruned.shrinks:
        written += SHRINKS_NOT
    elif not pruned.reclaimed:
        written += f"; space not reclaimed: {pruned.reason}"
    return f"{written}\n"


def text(indexed: Indexed, summary: Summary) -> str:
    """Write the documents indexed and their sections; then the pieces by meaning, if any.

    Short gives their counts and the texts embedded now, detailed the documents by type,
    the index, and the model with its prefixes; then each what the prune did.
    """
    report = indexed.report
    if summary == "short":
        written = f"documents: {report.types.total()}\nsections: {report.sections}\n"
        if indexed.model is not None:
            written += f"pieces: {report.pieces}\nembedded now: {report.embedded}\n"
        return written + prune_text(indexed.pruned, summary)
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
    return written + prune_text(indexed.pruned, summary)
