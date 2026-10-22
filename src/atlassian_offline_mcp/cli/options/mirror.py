"""``mirror``'s declaration; ``cli.commands.mirror`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import add_settings_options

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``mirror`` to the command."""
    parser = subparsers.add_parser("mirror", help="write the Markdown mirror from the raw store")
    flags = add_settings_options(parser)
    parser.set_defaults(command=Command("atlassian_offline_mcp.cli.commands.mirror", flags))
