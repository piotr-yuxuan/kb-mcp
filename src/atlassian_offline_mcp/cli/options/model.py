"""``model``'s declaration; ``cli.commands.model`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_settings_options,
    model_name,
)

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``model`` to the command."""
    parser = subparsers.add_parser("model", help="check the embedding model and its endpoint")
    flags = add_settings_options(parser)
    add_embedding_options(parser)
    parser.add_argument("action", choices=("check",))
    parser.add_argument(
        "name", nargs="?", type=model_name, help="the model to check; by default, the setting"
    )
    parser.set_defaults(command=Command("model", "atlassian_offline_mcp.cli.commands.model", flags))
