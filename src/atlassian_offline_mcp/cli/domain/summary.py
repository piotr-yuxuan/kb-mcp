"""What a run says on stderr before it acts, and whether it asks first.

Its summary, the values it ignores and its command to copy. Pure: the entry gives it the
arguments, the settings loaded and how the run reports, writes what it returns, and asks
the question if one follows.
"""

from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING, Literal

from atlassian_offline_mcp.cli.domain.command_line import command_line
from atlassian_offline_mcp.config.domain.settings import SETTING_PATHS, Ignored

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from pathlib import Path

    from atlassian_offline_mcp.cli.domain.command import Command
    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Output

# What follows what a run says before it acts: the run, a question first, or a refusal,
# since no one could answer one.
type Then = Literal["run", "ask", "refuse"]


def setting_line(loaded: Loaded, setting: str, *, detailed: bool) -> str:
    """Write a setting, by its path joined by dots, and its value; in detail, its layer too.

    A secret is said to be set or not, never shown; a list is joined.
    """
    path = tuple(setting.split("."))
    value = reduce(getattr, path, loaded.settings)
    if SETTING_PATHS[path] == "secret":
        shown = "not set" if value is None else "set"
    elif SETTING_PATHS[path] == "list":
        shown = ", ".join(value) or "(none)"
    else:
        shown = "(not set)" if value is None else str(value)
    return f"{setting}: {shown}" + (f" [{loaded.layer(setting)}]" if detailed else "")


def before(
    arguments: argparse.Namespace,
    loaded: Loaded,
    output: Output,
    absolute: Callable[[Path], Path],
) -> tuple[str, Then]:
    """Give what a run writes on stderr before it acts, in lines, and what follows.

    A command that writes begins with its summary: its name, each setting it reads and
    its value, in detail its layer too, then the lines of its ``described``. Every
    command then gives each value ignored: those that a stronger layer replaced and the
    variables that name no setting or are empty, as loaded; then, of the values that a
    layer gave, those that the run does not apply, by its ``unapplied``, and in detail
    those of the settings that the command never reads. Each names its setting, if any,
    and its layer, never its value. A command that writes ends with the command to copy,
    its paths made ``absolute``.

    A command that only reads runs, as does one given --yes, or --dry-run where it takes
    one. Another asks when stdin and stderr are both terminals, where someone can
    answer; else it is refused. -q leaves all this out, unless a question follows.
    """
    command: Command = arguments.command
    then: Then
    if not command.writes or arguments.yes or (command.dry_run and arguments.dry_run):
        then = "run"
    elif output.stdin_terminal and output.stderr_terminal:
        then = "ask"
    else:
        then = "refuse"
    if output.quiet and then != "ask":
        return "", then
    detailed = output.summary == "detailed"
    values = {
        ".".join(path): reduce(getattr, path, loaded.settings)
        for path, kind in SETTING_PATHS.items()
        if kind != "table"
    }
    unapplied = command.unapplied(arguments, values) if command.unapplied else {}
    ignored = [
        *loaded.ignored,
        *(
            Ignored(setting, loaded.layers[setting], why)
            for setting, why in unapplied.items()
            if setting in loaded.layers
        ),
        *(
            Ignored(setting, layer, f"not read by {command.name}")
            for setting, layer in loaded.layers.items()
            if detailed and setting not in command.reads
        ),
    ]
    noted = "".join(
        f"ignored: {each.layer}: {each.why}\n"
        if each.setting is None
        else f"ignored: {each.setting} ({each.layer}): {each.why}\n"
        for each in ignored
    )
    if not command.writes:
        return noted, then
    described = command.described(arguments, values) if command.described else ()
    return (
        f"{command.name}, with these settings:\n"
        + "".join(
            f"  {setting_line(loaded, setting, detailed=detailed)}\n" for setting in command.reads
        )
        + "".join(f"  {line}\n" for line in described)
        + noted
        + command_line(arguments, values, loaded.layers, absolute)
    ), then
