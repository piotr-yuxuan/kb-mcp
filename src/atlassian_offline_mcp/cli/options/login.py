"""``login``'s declaration; ``cli.commands.login`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import add_settings_options

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``login`` to the command."""
    parser = subparsers.add_parser("login", help="sign in once, in a Chrome window")
    flags = add_settings_options(parser)
    parser.add_argument("--chrome", help="Chrome's executable, where the chrome channel fails")
    parser.add_argument(
        "--keep-extensions", action="store_true", help="let Chrome load extensions, for SSO"
    )
    parser.set_defaults(command=Command("login", "atlassian_offline_mcp.cli.commands.login", flags))
