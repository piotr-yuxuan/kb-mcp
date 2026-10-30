"""What a run says on stderr before it acts, and whether it asks first.

Its summary, the values it ignores and its command to copy. Pure: the entry gives it the
arguments, the settings loaded and how the run reports, writes what it returns, and asks
the question if one follows.
"""

from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING, Literal

from kb_mcp.cli.domain.command import OBSERVING
from kb_mcp.cli.domain.command_line import command_line
from kb_mcp.config.domain.settings import Ignored

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from pathlib import Path

    from kb_mcp.cli.domain.command import Command
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Output

# What follows what a run says before it acts: the run, a question first, or a refusal,
# since no one could answer one.
type Then = Literal["run", "ask", "refuse"]


def values_of(loaded: Loaded) -> dict[str, object]:
    """Give every setting's value by its path joined by dots, as a command's functions take them."""
    return {
        ".".join(path): reduce(getattr, path, loaded.settings)
        for path, kind in loaded.paths.items()
        if kind != "table"
    }


def setting_line(loaded: Loaded, setting: str, *, detailed: bool) -> str:
    """Write a setting, by its path joined by dots, and its value; in detail, its layer too.

    A secret is said to be set or not, never shown; a list is joined.
    """
    path = tuple(setting.split("."))
    value = reduce(getattr, path, loaded.settings)
    kind = loaded.paths[path]
    if kind == "secret":
        shown = "not set" if value is None else "set"
    elif kind == "list":
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
    its value, in detail its layer too, and why the run does not apply it, by its
    ``unapplied``, whatever its layer, followed in detail by the entry's own of
    ``OBSERVING``; then the lines of its ``described``. Every command then says, when
    telemetry is on, whatever layer turned it on, ``telemetry: on, to <endpoint>
    (<layer>)``, since a variable that other programs share may have done so unseen,
    such as in ``serve``, which an agent starts with its own environment; then it
    gives each value ignored: those that a stronger layer replaced and the variables
    that name no setting or are empty, as loaded; then, of the values that a layer
    gave, those that the run does not apply, by its ``unapplied``, and in detail those
    of the settings that neither the command nor the entry reads, unless ``unapplied``
    said why. Each names its setting, if any, and its layer, never its value. A command
    that writes ends with the command to copy, its paths made ``absolute``, which carries
    the values that a layer gave and the run applies, or names those it cannot carry.

    A command that only reads runs, as does one given --yes, or --dry-run where it takes
    one. Another asks when stdin and stderr are both terminals, where someone can
    answer; else it is refused. -q leaves all this out, unless a question follows; at
    the level error, from -q or --log-level, the values ignored, which are warnings, are
    left out alike.
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
    values = values_of(loaded)
    unapplied = command.unapplied(arguments, values) if command.unapplied else {}
    read = dict.fromkeys((*command.reads, *OBSERVING))
    ignored = [
        *loaded.ignored,
        *(
            Ignored(setting=setting, layer=loaded.layers[setting], why=why)
            for setting, why in unapplied.items()
            if setting in loaded.layers
        ),
        *(
            Ignored(setting=setting, layer=layer, why=f"not read by {command.name}")
            for setting, layer in loaded.layers.items()
            if detailed and setting not in read and setting not in unapplied
        ),
    ]
    warned = ignored if output.level != "error" or then == "ask" else []
    noted = "".join(
        f"ignored: {each.layer}: {each.why}\n"
        if each.setting is None
        else f"ignored: {each.setting} ({each.layer}): {each.why}\n"
        for each in warned
    )
    endpoint = loaded.settings.telemetry.endpoint
    telemetry = (
        ""
        if endpoint is None
        else f"telemetry: on, to {endpoint} ({loaded.layer('telemetry.endpoint')})\n"
    )
    if not command.writes:
        return telemetry + noted, then
    described = command.described(arguments, values) if command.described else ()
    applied = {
        setting: layer for setting, layer in loaded.layers.items() if setting not in unapplied
    }
    copied = command_line(arguments, values, applied, loaded.replaced, absolute)
    return (
        f"{command.name}, with these settings:\n"
        + "".join(
            f"  {setting_line(loaded, setting, detailed=detailed)}"
            + (f" (not applied: {unapplied[setting]})" if setting in unapplied else "")
            + "\n"
            for setting in (read if detailed else command.reads)
        )
        + "".join(f"  {line}\n" for line in described)
        + telemetry
        + noted
        + copied.emptied
        + copied.command
        + copied.unflagged
    ), then
