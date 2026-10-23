"""``serve``'s declaration; ``cli.commands.serve`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    endpoint_by_meaning,
)

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``serve`` to the command."""
    parser = subparsers.add_parser("serve", help="serve the mirror over MCP on stdio")
    actions, flags = add_settings_options(parser)
    add_output_options(parser, result=False)
    remote = add_embedding_options(parser)
    parser.set_defaults(
        command=Command(
            "serve",
            "atlassian_offline_mcp.cli.commands.serve",
            reads=("data_dir", "search_mode", "embedding_url", "embedding_api_key"),
            flags=flags,
            actions=(*actions, remote),
            refused=endpoint_by_meaning,
            traced=False,
        )
    )
