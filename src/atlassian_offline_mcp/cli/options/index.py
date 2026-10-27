"""``index``'s declaration; ``cli.commands.index`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    add_yes_option,
    endpoint_by_meaning,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

# What the index's build reads, beside the data directory; sync's index step reads them too.
INDEX_SETTINGS = ("model", "search_mode", "chunking", "embedding_url", "embedding_api_key")


def by_words_alone(
    _arguments: argparse.Namespace, settings: Mapping[str, object]
) -> dict[str, str]:
    """By words alone, the lexical mode embeds nothing: model, endpoint, chunking unused."""
    if settings["search_mode"] != "lexical":
        return {}
    return dict.fromkeys(
        ("model", "embedding_url", "embedding_api_key", "chunking"),
        "the lexical mode embeds nothing",
    )


def pruning_said(_arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """By meaning, the build is followed by a prune of the vector store: say it first."""
    if settings["search_mode"] == "lexical":
        return ()
    return ("then: the vector store keeps only the vectors that the index and eval's read",)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``index`` to the command."""
    parser = subparsers.add_parser(
        "index",
        help="build the search index from the mirror",
        epilog=(
            "With --format json: report, the documents by type, the sections, the files"
            " skipped, the pieces by meaning, the texts embedded now and the files with a"
            " piece refused; index, its path; model, the one that embedded, null by words"
            " alone; pruned, what the prune of the vector store kept and deleted, or why it"
            " did not prune, null by words alone."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    remote = add_embedding_options(parser)
    parser.set_defaults(
        command=Command(
            "index",
            "atlassian_offline_mcp.cli.commands.index",
            reads=("data_dir", *INDEX_SETTINGS),
            flags=flags,
            actions=(*actions, remote),
            writes=True,
            unapplied=by_words_alone,
            refused=endpoint_by_meaning,
            described=pruning_said,
        )
    )
