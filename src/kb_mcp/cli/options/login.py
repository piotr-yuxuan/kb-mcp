"""``login``'s declaration, from the registry's accounts; ``cli.commands.login`` runs it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options, add_yes_option
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


def in_the_browser(
    arguments: argparse.Namespace, _settings: Mapping[str, object]
) -> dict[str, str]:
    """``login`` signs in in a browser, whatever the account's other settings say."""
    account = accounts_of(arguments.sources)[arguments.account]
    return dict.fromkeys(account.paths[1:], "login signs in in a browser")


def site_not_set(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse a sign-in without the first setting of the account named: where it signs in."""
    site = accounts_of(arguments.sources)[arguments.account].paths[0]
    if settings[site] is not None:
        return None
    return f"{site}: not set; add it to the settings or pass --site"


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Declared],
) -> None:
    """Add ``login`` to the command, naming a sign-in that the registered sources declare."""
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
    accounts = accounts_of(sources)
    account = parser.add_argument("account", choices=list(accounts), help="the sign-in")
    chrome = parser.add_argument(
        "--chrome", type=Path, help="Chrome's executable, where the chrome channel fails"
    )
    extensions = parser.add_argument(
        "--keep-extensions", action="store_true", help="let Chrome load extensions, for SSO"
    )
    parser.set_defaults(
        command=Command(
            "login",
            "kb_mcp.cli.commands.login",
            reads=(*(each.paths[0] for each in accounts.values()), "data_dir"),
            flags=flags,
            actions=(*actions, chrome, extensions, account),
            writes=True,
            unapplied=in_the_browser,
            refused=site_not_set,
        )
    )
