"""The entry of every run: it loads the settings, then runs the chosen subcommand."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.config.app.settings import load_settings
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.cli.domain.command import Command


def enter(arguments: argparse.Namespace) -> int:
    """Load the settings, with the flags given, then run the chosen subcommand.

    Refused settings exit 2 before the run is imported; else the run's status is
    returned. A subcommand that reads no settings gets None. A flag's layer is its
    option, named after its ``dest``.
    """
    command: Command = arguments.command
    settings = None
    if command.reads_settings:
        flags = {
            f"--{dest.replace('_', '-')}": (setting, getattr(arguments, dest))
            for dest, setting in command.flags.items()
        }
        try:
            loaded = load_settings(arguments.config, flags, Path.home().resolve())
        except SettingsError as error:
            sys.stderr.write(f"settings refused: {error}\n")
            return ExitStatus.REFUSED
        settings = loaded if command.with_layers else loaded.settings
    return int(importlib.import_module(command.run).run(arguments, settings))
