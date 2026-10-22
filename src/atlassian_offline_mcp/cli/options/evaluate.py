"""``eval``'s declaration; ``cli.commands.evaluate`` runs it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from argcomplete.completers import FilesCompleter

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_settings_options,
    model_name,
)

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``eval`` to the command."""
    parser = subparsers.add_parser(
        "eval", help="measure lexical, semantic and hybrid search on golden questions"
    )
    flags = add_settings_options(parser)
    add_embedding_options(parser)
    parser.add_argument(
        "golden", type=Path, help="a YAML file of golden questions"
    ).completer = FilesCompleter(["yaml", "yml"])
    parser.add_argument(
        "--model",
        action="append",
        type=model_name,
        help="a model to evaluate, as the endpoint names it; by default, the setting",
    )
    parser.set_defaults(command=Command("atlassian_offline_mcp.cli.commands.evaluate", flags))
