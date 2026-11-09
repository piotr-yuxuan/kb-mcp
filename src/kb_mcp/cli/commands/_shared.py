"""The entry of every observed run: it loads the settings, runs the command, writes its result."""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from pydantic_core import to_json, to_jsonable_python

from kb_mcp.cli.adapters.confirmation import ask
from kb_mcp.cli.domain.echo import before, ignored_lines, values_of
from kb_mcp.config.app.settings import load_settings
from kb_mcp.config.domain.settings import SettingsError, settings_model
from kb_mcp.kernel.exit_status import ENDED
from kb_mcp.kernel.output import Output
from kb_mcp.observability.app.observed import Invocation, observed
from kb_mcp.sources.registry import tables

# What run.start names in place of an argument's value that the command keeps out of logs.
UNLOGGED = "[not logged]"

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.cli.domain.command import Command
    from kb_mcp.sources.declaration import Source


def enter(arguments: argparse.Namespace, given: Sequence[str], sources: Sequence[Source]) -> int:
    """Load the settings, run the chosen command, write its result; return the exit status.

    The settings are loaded with the flags given, by the model of the registry's
    ``sources`` and of the accounts they name. Before the command's module is imported,
    the run ends refused, 2, for refused settings, ``settings.refused``, and for what the
    command refuses of them or of its arguments, a program missing from PATH or a file
    that it reads missing or a folder, ``run.refused``, after the values that the settings
    ignored: each on stderr alone, as such a run has no log file. A command that writes
    then says its echo and asks, unless given --yes: declined, the run ends 1; with no
    terminal to ask on, refused, 2.

    The run is then ``observed``, its start naming the arguments ``given``, each of the
    command's ``unlogged`` ones as ``[not logged]``, the settings, secrets masked, and the
    layer of telemetry's endpoint. The module's ``run`` gives its status and its result,
    None when it has none to write, such as ``serve``'s: the result goes to stdout as one
    JSON document, secrets masked, or as the module's ``text`` writes it, unless -q. An
    exception or Ctrl-C ends the run as ``observed`` says.
    """
    command: Command = arguments.command
    output = Output(
        arguments.level,
        arguments.detail,
        arguments.format,
        quiet=arguments.quiet,
        stdin_terminal=sys.stdin.isatty(),
        stderr_terminal=sys.stderr.isatty(),
    )
    flags = {
        option: (setting, getattr(arguments, dest))
        for dest, (option, setting) in command.setting_flags().items()
    }
    model = settings_model(*tables(sources))
    try:
        loaded = load_settings(arguments.config, flags, Path.home().resolve(), model)
    except SettingsError as error:
        structlog.get_logger().error("settings.refused", reason=str(error))
        sys.stderr.write(error.advice)
        return ENDED["refused"]
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
        sys.stderr.write(ignored_lines(loaded.ignored if output.level != "error" else ()))
        structlog.get_logger().error("run.refused", reason=refusal)
        return ENDED["refused"]
    said, then = before(arguments, loaded, output, lambda path: path.expanduser().absolute())
    # Each unlogged argument is a positional string, given as the last token equal to it.
    hidden = {
        len(given) - 1 - list(reversed(given)).index(getattr(arguments, dest))
        for dest in command.unlogged
    }
    sys.stderr.write(said)
    stopped = ask(then, sys.stdin, sys.stderr)
    if stopped is not None:
        return stopped
    with observed(
        output,
        loaded.settings.logs.dir,
        loaded.settings.telemetry.endpoint,
        Invocation(
            # A step, such as eval-agents' call, is observed as its command: their log
            # files, root spans and kb_mcp.command share its name, as its pattern has it.
            command=command.name.partition(" ")[0],
            described={
                "arguments": [UNLOGGED if at in hidden else each for at, each in enumerate(given)],
                "settings": to_jsonable_python(loaded),
                "telemetry_layer": loaded.layer("telemetry.endpoint"),
            },
            dry_run=command.dry_run and arguments.dry_run,
            traced=command.traced,
            commands=arguments.commands,
        ),
    ) as run:
        module = importlib.import_module(command.run)
        status, result = module.run(arguments, loaded)
        if result is not None and output.format == "json":
            sys.stdout.write(f"{to_json(result, indent=2, inf_nan_mode='null').decode()}\n")
        elif result is not None and not output.quiet:
            sys.stdout.write(module.text(result, output.detail))
        run.status = int(status)
    return run.status
