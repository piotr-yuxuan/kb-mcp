"""``check``: validate the settings and the data directory, and show them."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.config.app.settings import SETTINGS_PATH
from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Settings


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``check`` to the command."""
    parser = subparsers.add_parser("check", help="validate the settings and the data directory")
    parser.add_argument("--config", type=Path, default=SETTINGS_PATH, help="the settings file")
    parser.add_argument("--data-dir", help="the data directory, overriding the settings")
    parser.set_defaults(command=Command(__name__, {"data_dir": "data_dir"}))


def run(_arguments: argparse.Namespace, settings: Settings) -> ExitStatus:
    """Print the effective settings, which the entry checked, the data directory included."""
    sys.stdout.write(
        f"site: {settings.site or '(not set)'}\n"
        f"data directory: {settings.data_dir}\n"
        f"spaces: {', '.join(settings.spaces) or '(none)'}\n"
        f"projects: {', '.join(settings.projects) or '(none)'}\n"
    )
    return ExitStatus.OK
