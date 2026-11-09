"""``embed``'s declaration; ``cli.commands.embed`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    add_yes_option,
    endpoint_elsewhere,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def pruning_said(
    _arguments: argparse.Namespace, _settings: Mapping[str, object]
) -> tuple[str, ...]:
    """Say first that the pieces are the index's, then that a prune of the store follows."""
    return (
        "then: the pieces of the index as kb-mcp index left it get their vectors",
        "then: the vector store keeps only the vectors that the index and eval's read",
    )


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Source],
) -> None:
    """Add ``embed`` to the command."""
    parser = subparsers.add_parser(
        "embed",
        help="give the index's pieces their vectors, then prune the vector store",
        epilog=(
            "With --format json: index, its path; model, the one that embedded; pieces, those"
            " that the index holds; documents, its documents; skipped, the files that it"
            " lacks; added and removed, the pieces; embedded, the texts embedded now; found,"
            " those that the vector store held; refused, the documents with a piece refused;"
            " unchanged, whether nothing was written; pruned, what the prune of the vector"
            " store kept and deleted, or why it did not prune."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    remote = add_embedding_options(parser)
    parser.set_defaults(
        command=Command(
            "embed",
            "kb_mcp.cli.commands.embed",
            reads=("data_dir", "model", "chunking", "embedding_url", "embedding_api_key"),
            flags=flags,
            actions=(*actions, remote),
            writes=True,
            refused=endpoint_elsewhere,
            described=pruning_said,
        )
    )
