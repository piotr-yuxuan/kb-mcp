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
from kb_mcp.cli.domain.preview import before, ignored_lines, values_of
from kb_mcp.config.app.settings import load_settings
from kb_mcp.config.domain.settings import SettingsError, settings_model
from kb_mcp.kernel.exit_status import ExitStatus
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
    """Load the settings, with the flags given, run the chosen subcommand, write its result.

    The settings are loaded for every command observed, which reads those of
    ``OBSERVING`` whatever else it reads, by the model that holds the table of each
    source of the registry, ``sources``, and of each account that a source names, each
    loaded by the module path that its declaration names. Refused settings exit 2 before
    the run is imported, as does what the command refuses of them and of its arguments, a program
    that it needs missing from PATH, or a file that it reads missing or a folder, a pipe
    being read: each is an error, the event ``settings.refused`` or ``run.refused`` with
    its reason, on stderr alone, as a run that never started has no log file. Before
    ``run.refused`` go the values that the settings loaded ignored, one of which may be
    why, such as a variable that names no setting, unless at the level error, as for a
    run. Else the values ignored go to stderr, after the summary of a command that writes
    and before the command to copy. Such a command then asks, unless told not to, and is
    refused where no one can answer: declined, it exits 1, refused, 2, both before the
    run is imported. The run gets the settings loaded, with each one's layer, a flag's
    being its option. It returns its status, then its result, or None when it has none to
    write, such as ``serve``, whose output is the protocol. The result goes to stdout as
    one JSON document, secrets masked, or as its module's ``text`` writes it, unless -q.
    The run's status is returned.

    From the run's import to its result written, the run is ``observed``: its logs go to
    stderr at its level and to its log file, in the settings' log folder, where every
    command's files past 30 days go, as the parser's ``commands`` name them; its start
    names the arguments ``given``, the settings as one JSON document, secrets masked,
    and the layer of telemetry's endpoint, which says what turned telemetry on, or off;
    its telemetry goes to the settings' endpoint, if any, as one trace unless its
    command says it is not ``traced``, saying whether it is a dry run. The values of the
    command's ``unlogged`` arguments read ``[not logged]`` among those given, each in its
    place. An exception
    that the run lets through, or Ctrl-C, ends it with the status that ``observed``
    gives.
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
        sys.stderr.write(ignored_lines(loaded.ignored if output.level != "error" else ()))
        structlog.get_logger().error("run.refused", reason=refusal)
        return ExitStatus.REFUSED
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
            sys.stdout.write(module.text(result, output.summary))
        run.status = int(status)
    return run.status
