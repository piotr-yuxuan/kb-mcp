"""``check``'s declaration; ``cli.commands.check`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import add_output_options, add_settings_options

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``check`` to the command."""
    parser = subparsers.add_parser("check", help="validate the settings and the data directory")
    flags = add_settings_options(parser)
    add_output_options(parser)
    parser.set_defaults(
        command=Command(
            "check", "atlassian_offline_mcp.cli.commands.check", flags, with_layers=True
        )
    )
