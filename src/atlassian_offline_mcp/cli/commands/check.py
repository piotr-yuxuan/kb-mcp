"""``check``: validate the settings and the data directory, and show them."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.config.app.settings import (
    SETTINGS_PATH,
    UnsafeDataDirError,
    load_settings,
)
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``check`` to the command."""
    parser = subparsers.add_parser("check", help="validate the settings and the data directory")
    parser.add_argument("--config", type=Path, default=SETTINGS_PATH, help="the settings file")
    parser.add_argument("--data-dir", help="the data directory, overriding the settings")
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> ExitStatus:
    """Print the effective settings; exit 2 for bad settings or a refused directory."""
    try:
        settings = load_settings(arguments.config, {"data_dir": arguments.data_dir})
    except UnsafeDataDirError as error:
        sys.stderr.write(f"data directory refused: {error}\n")
        return ExitStatus.REFUSED
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return ExitStatus.REFUSED
    sys.stdout.write(
        f"site: {settings.site or '(not set)'}\n"
        f"data directory: {settings.data_dir}\n"
        f"spaces: {', '.join(settings.spaces) or '(none)'}\n"
        f"projects: {', '.join(settings.projects) or '(none)'}\n"
    )
    return ExitStatus.OK
