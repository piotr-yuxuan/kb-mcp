"""``login``'s declaration; ``cli.commands.login`` runs it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    SIGN_IN,
    add_output_options,
    add_settings_options,
    add_yes_option,
    site_not_set,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping


def in_the_browser(
    _arguments: argparse.Namespace, _settings: Mapping[str, object]
) -> dict[str, str]:
    """``login`` signs in in a browser, whatever the email and the API token say."""
    return dict.fromkeys(SIGN_IN, "login signs in in a browser")


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``login`` to the command."""
    parser = subparsers.add_parser(
        "login",
        help="sign in once, in a Chrome window",
        epilog=(
            "With --format json: site, the site signed in to; session, the folder that"
            " keeps the session."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    chrome = parser.add_argument(
        "--chrome", type=Path, help="Chrome's executable, where the chrome channel fails"
    )
    extensions = parser.add_argument(
        "--keep-extensions", action="store_true", help="let Chrome load extensions, for SSO"
    )
    parser.set_defaults(
        command=Command(
            "login",
            "atlassian_offline_mcp.cli.commands.login",
            reads=("site", "data_dir"),
            flags=flags,
            actions=(*actions, chrome, extensions),
            writes=True,
            unapplied=in_the_browser,
            refused=site_not_set,
        )
    )
