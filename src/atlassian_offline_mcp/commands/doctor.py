"""``doctor``: check the machine, the data directory and the saved session."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.app.doctor import SIGN_IN_AGAIN, doctor
from atlassian_offline_mcp.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.domain.settings import SettingsError

if TYPE_CHECKING:
    import argparse

BAD_SETTINGS = 2
NOT_SIGNED_IN = 3


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``doctor`` to the command."""
    parser = subparsers.add_parser("doctor", help="check the machine and the saved session")
    add_settings_options(parser)
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> int:
    """Print each check and its verdict; exit 2 for refused settings, 3 to sign in again."""
    try:
        settings = settings_of(arguments)
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return BAD_SETTINGS
    verdicts = doctor(settings)
    for name, verdict in verdicts:
        sys.stdout.write(f"{name}: {verdict}\n")
    return NOT_SIGNED_IN if any(SIGN_IN_AGAIN in verdict for _, verdict in verdicts) else 0
