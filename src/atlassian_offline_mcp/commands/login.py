"""``login``: sign in once in a Chrome window, and keep the session for later runs."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.browser import SIGN_IN_TIMEOUT_S, SignInTimeoutError
from atlassian_offline_mcp.app.login import login
from atlassian_offline_mcp.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.domain.settings import SettingsError

if TYPE_CHECKING:
    import argparse

BAD_SETTINGS = 2
NOT_SIGNED_IN = 3


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``login`` to the command."""
    parser = subparsers.add_parser("login", help="sign in once, in a Chrome window")
    add_settings_options(parser)
    parser.add_argument("--chrome", help="Chrome's executable, where the chrome channel fails")
    parser.add_argument(
        "--keep-extensions", action="store_true", help="let Chrome load extensions, for SSO"
    )
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> int:
    """Sign in; exit 2 for bad settings, 3 when no sign-in completes in time."""
    try:
        settings = settings_of(arguments)
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return BAD_SETTINGS
    if settings.site is None:
        sys.stderr.write("settings refused: site: not set; add it to the settings or pass --site\n")
        return BAD_SETTINGS
    sys.stdout.write(f"Sign in to {settings.site} in the Chrome window that opens.\n")
    try:
        login(settings, settings.site, arguments.chrome, extensions=arguments.keep_extensions)
    except SignInTimeoutError:
        sys.stderr.write(f"no sign-in within {SIGN_IN_TIMEOUT_S} s\n")
        return NOT_SIGNED_IN
    sys.stdout.write("Signed in; the session is saved.\n")
    return 0
