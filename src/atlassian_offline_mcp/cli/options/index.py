"""``index``'s declaration; ``cli.commands.index`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping


def by_words_alone(
    _arguments: argparse.Namespace, settings: Mapping[str, object]
) -> dict[str, str]:
    """By words alone, the lexical mode embeds nothing: the model and its endpoint go unused."""
    if settings["search_mode"] != "lexical":
        return {}
    return dict.fromkeys(
        ("model", "embedding_url", "embedding_api_key"), "the lexical mode embeds nothing"
    )


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``index`` to the command."""
    parser = subparsers.add_parser("index", help="build the search index from the mirror")
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    remote = add_embedding_options(parser)
    parser.set_defaults(
        command=Command(
            "index",
            "atlassian_offline_mcp.cli.commands.index",
            reads=("data_dir", "model", "search_mode", "embedding_url", "embedding_api_key"),
            flags=flags,
            actions=(*actions, remote),
            writes=True,
            unapplied=by_words_alone,
        )
    )
