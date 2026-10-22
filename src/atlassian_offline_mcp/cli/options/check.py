"""``check``'s declaration; ``cli.commands.check`` runs it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from argcomplete.completers import DirectoriesCompleter, FilesCompleter

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.config.adapters.settings_file import SETTINGS_PATH

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``check`` to the command."""
    parser = subparsers.add_parser("check", help="validate the settings and the data directory")
    parser.add_argument(
        "--config", type=Path, default=SETTINGS_PATH, help="the settings file"
    ).completer = FilesCompleter(["toml"])
    parser.add_argument(
        "--data-dir", help="the data directory, overriding the settings"
    ).completer = DirectoriesCompleter()
    parser.set_defaults(
        command=Command("atlassian_offline_mcp.cli.commands.check", {"data_dir": "data_dir"})
    )
