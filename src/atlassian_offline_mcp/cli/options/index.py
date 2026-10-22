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


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``index`` to the command."""
    parser = subparsers.add_parser("index", help="build the search index from the mirror")
    flags = add_settings_options(parser)
    add_output_options(parser)
    add_embedding_options(parser)
    parser.set_defaults(command=Command("index", "atlassian_offline_mcp.cli.commands.index", flags))
