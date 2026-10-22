"""The entry of every run: it loads the settings, runs the chosen subcommand, writes its result."""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_core import to_json, to_jsonable_python

from atlassian_offline_mcp.cli.adapters.question import ask
from atlassian_offline_mcp.cli.domain.summary import before, values_of
from atlassian_offline_mcp.config.app.settings import load_settings
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.output import Output
from atlassian_offline_mcp.observability.app.observed import observed

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from atlassian_offline_mcp.cli.domain.command import Command


def enter(arguments: argparse.Namespace, given: Sequence[str]) -> int:
    """Load the settings, with the flags given, run the chosen subcommand, write its result.

    Refused settings exit 2 before the run is imported, as does what the command refuses
    of them and of its arguments, a program that it needs missing from PATH, or a file
    that it reads missing or a folder, a pipe being read; else the values ignored go to
    stderr, after the summary of a command that writes and before the command to copy.
    Such a command then asks, unless told not to, and is refused where no one can
    answer: declined, it exits 1, refused, 2, both before the run is imported. The run
    gets the settings loaded, with each one's layer, a flag's being its option; one that
    reads no setting gets None, and nothing is said. It returns its status, then its
    result, or None when it has none to write, such as ``serve``, whose output is the
    protocol. The result goes to stdout as one JSON document, secrets masked, or as its
    module's ``text`` writes it, unless -q. The run's status is returned.

    From the run's import to its result written, the run is ``observed``: its logs go to
    stderr at its level and to its log file, in the settings' log folder, none for a run
    that reads no settings, and its start names the arguments ``given`` and the settings
    as one JSON document, secrets masked. An exception that the run lets through, or
    Ctrl-C, ends it with the status that ``observed`` gives.
    """
    command: Command = arguments.command
    output = Output(
        arguments.level,
        arguments.summary,
        arguments.format,
        quiet=arguments.quiet,
        stdin_terminal=sys.stdin.isatty(),
        stderr_terminal=sys.stderr.isatty(),
    )
    loaded = None
    if command.reads:
        flags = {
            option: (setting, getattr(arguments, dest))
            for dest, (option, setting) in command.setting_flags().items()
        }
        try:
            loaded = load_settings(arguments.config, flags, Path.home().resolve())
        except SettingsError as error:
            sys.stderr.write(f"settings refused: {error}\n")
            return ExitStatus.REFUSED
        refusal = command.refused(arguments, values_of(loaded)) if command.refused else None
        refusal = refusal or next(
            (f"{name}: not found on PATH" for name in command.programs if not shutil.which(name)),
            None,
        )
        refusal = refusal or next(
            (
                f"{path}: not a file"
                for path in (Path(getattr(arguments, dest)) for dest in command.files)
                if not path.exists() or path.is_dir()
            ),
            None,
        )
        if refusal is not None:
            sys.stderr.write(f"refused: {refusal}\n")
            return ExitStatus.REFUSED
        said, then = before(arguments, loaded, output, lambda path: path.expanduser().absolute())
        sys.stderr.write(said)
        stopped = ask(then, sys.stdin, sys.stderr)
        if stopped is not None:
            return stopped
    with observed(
        output,
        None if loaded is None else loaded.settings.logs.dir,
        None if loaded is None else loaded.settings.telemetry.endpoint,
        command.name,
        {
            "arguments": list(given),
            "settings": None if loaded is None else to_jsonable_python(loaded),
        },
    ) as run:
        module = importlib.import_module(command.run)
        status, result = module.run(arguments, loaded)
        if result is not None and output.format == "json":
            sys.stdout.write(f"{to_json(result, indent=2, inf_nan_mode='null').decode()}\n")
        elif result is not None and not output.quiet:
            sys.stdout.write(module.text(result, output.summary))
        run.status = int(status)
    return run.status
