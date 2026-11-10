"""``embed``: give the index's chunks their vectors, by the setting's model, then prune."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._embedding import indexing_of, open_endpoint, prefixes_said
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.search.app.indexing import fill_and_prune

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Detail
    from kb_mcp.search.app.indexing import Filled
    from kb_mcp.search.app.pruning import Pruned

# Bytes in a megabyte, as the result says the vector cache's size.
MB = 1_000_000
# A vector cache made by an earlier version, converted to give freed space back.
CONVERTED = "; converted, as made by an earlier version, so that it gives freed space back"
# One whose conversion failed, its reason given, which the next prune tries again.
SHRINKS_NOT = (
    "; made by an earlier version, it is not yet converted to give freed space back ({}):"
    " the next prune tries again, given about the vector cache's size free on disk"
)


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Filled | None]:
    """Fill the index's chunks; exit 1 when a chunk was refused, a file lacks, or none written.

    The endpoint must answer with the setting's model, whatever ``search_mode`` says,
    which this run does not read; when it does not, the index in place stays, with its
    vectors, and nothing is given. Nothing filled is an error, the index named by
    ``kb-mcp index``; each document with a chunk that the endpoint refused is a
    warning. A mirror changed since the index is a warning, whose exit status stays.
    """
    settings = loaded.settings
    opening = partial(open_endpoint, arguments, settings)
    filled = fill_and_prune(indexing_of(settings, opening))
    return ExitStatus.OK if filled and filled.whole else ExitStatus.FAILED, filled


def prune_text(pruned: Pruned | None, summary: Detail) -> str:
    """Say what the prune that followed the build did.

    Short gives the vectors deleted and the vector cache's size. Detailed gives the
    vectors kept, of which for the evaluation alone, those deleted, the vector cache's size
    before and after, and whether it gives space back; or why it did not prune.
    """
    if pruned is None:
        return ""
    if summary == "short":
        if pruned.outcome != "pruned":
            return f"vectors pruned: none, {pruned.outcome}\n"
        return f"vectors pruned: {pruned.deleted}\nvector cache: {pruned.bytes_after / MB:.1f} MB\n"
    if pruned.outcome != "pruned":
        place = f" ({pruned.file})" if pruned.file else ""
        return f"vector cache not pruned, {pruned.outcome}: {pruned.reason}{place}\n"
    written = (
        f"kept {pruned.kept} vectors ({pruned.kept_for_evaluation} for the evaluation"
        f" alone), pruned {pruned.deleted}; the vector cache from"
        f" {pruned.bytes_before / MB:.1f} to {pruned.bytes_after / MB:.1f} MB in"
        f" {pruned.seconds:.1f} s"
    )
    if pruned.converted:
        written += CONVERTED
    if not pruned.shrinks:
        written += SHRINKS_NOT.format(pruned.reason)
    elif not pruned.reclaimed:
        written += f"; space not reclaimed: {pruned.reason}"
    return f"{written}\n"


def text(filled: Filled, summary: Detail) -> str:
    """Write the chunks that the index holds and what changed of them, then the prune.

    Short gives the chunks, those added and removed, or that nothing was written, and
    the texts embedded now; detailed, the texts found in the vector cache, the documents
    with a chunk refused, the index, and the model with its prefixes too.
    """
    if summary == "short":
        written = f"chunks: {filled.chunks}\n"
        written += (
            "nothing written\n"
            if filled.unchanged
            else f"added: {filled.added}\nremoved: {filled.removed}\n"
        )
        written += f"embedded now: {filled.embedded}\n"
    else:
        model = f"{filled.model} ({prefixes_said(filled.model)})"
        holds = f"{filled.index} holds {filled.chunks} chunks by meaning, with {model}"
        written = (
            f"nothing changed: {holds}\n"
            if filled.unchanged
            else f"{filled.chunks} chunks by meaning in {filled.index}, with {model}:"
            f" {filled.added} added, {filled.removed} removed; {filled.embedded} texts embedded"
            f" now, {filled.found} found in the vector cache;"
            f" {len(filled.refused)} documents with a chunk refused\n"
        )
    return written + prune_text(filled.pruned, summary)
