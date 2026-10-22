"""``doctor``: check the machine, the data directory and the saved session."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.sources.atlassian.app.doctor import FAILED, SIGN_IN, doctor

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``doctor`` to the command."""
    parser = subparsers.add_parser("doctor", help="check the machine and the saved session")
    add_settings_options(parser)
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> ExitStatus:
    """Print each check's verdict; exit 1 if one fails, 2 for settings, 3 to sign in again."""
    try:
        settings = settings_of(arguments)
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return ExitStatus.REFUSED
    verdicts = doctor(settings)
    for verdict in verdicts:
        sys.stdout.write(f"{verdict.name}: {verdict.found}\n")
    states = {verdict.state for verdict in verdicts}
    if SIGN_IN in states:
        return ExitStatus.SIGN_IN_AGAIN
    return ExitStatus.FAILED if FAILED in states else ExitStatus.OK
