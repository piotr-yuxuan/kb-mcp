"""The entry of every run: it loads the settings, runs the chosen subcommand, writes its result."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_core import to_json

from atlassian_offline_mcp.config.app.settings import load_settings
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.output import Output

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.cli.domain.command import Command


def enter(arguments: argparse.Namespace) -> int:
    """Load the settings, with the flags given, run the chosen subcommand, write its result.

    Refused settings exit 2 before the run is imported. A subcommand that reads no
    settings gets None. A flag's layer is its option, named after its ``dest``. The run
    returns its status, then its result, or None when it has none to write, such as
    ``serve``, whose output is the protocol. The result goes to stdout as one JSON
    document, secrets masked, or as its module's ``text`` writes it, unless -q. The
    run's status is returned.
    """
    command: Command = arguments.command
    output = Output(
        arguments.level,
        arguments.summary,
        arguments.format,
        stdin_terminal=sys.stdin.isatty(),
        stderr_terminal=sys.stderr.isatty(),
    )
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
    module = importlib.import_module(command.run)
    status, result = module.run(arguments, settings)
    if result is not None and output.format == "json":
        sys.stdout.write(f"{to_json(result, indent=2, inf_nan_mode='null').decode()}\n")
    elif result is not None and not output.quiet:
        sys.stdout.write(module.text(result, output.summary))
    return int(status)
