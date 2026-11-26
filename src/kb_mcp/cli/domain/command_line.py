"""The command to copy: a run written as the command line that runs it again."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from kb_mcp.kernel.names import PROGRAM
from kb_mcp.kernel.records import Record

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Collection, Mapping

    from kb_mcp.cli.domain.command import Command

# What ends a line but the last, so that the shell reads one command, and indents the next.
CONTINUED = " \\\n  "


class Copy(Record):
    """The command to copy, and the lines that name what it cannot carry, said around it.

    ``command`` holds an option to a line; ``emptied``, said before it, and ``unflagged``,
    after it, hold their lines or nothing; every line ends with a newline.
    """

    emptied: str
    command: str
    unflagged: str


def command_line(
    arguments: argparse.Namespace,
    values: Mapping[str, object],
    given: Mapping[str, str],
    replaced: Collection[str],
    absolute: Callable[[Path], Path],
) -> Copy:
    """Write the command that runs this run again, and what it cannot carry.

    The program and the subcommand come first, then each option of the command's
    ``actions`` in order, its repeats on its line, then the positionals. A flag carries
    its setting's value only when the command reads the setting and a layer gave it;
    another option, when it is not its default. Paths are made ``absolute``, and values
    quoted for the shell; what is not among the actions is never written. A list that a
    layer emptied, which no flag says, is named in ``emptied``; each setting read and
    given that no flag sets, in ``unflagged``, with its layer, never its value.
    """
    command: Command = arguments.command
    settings = {dest: setting for dest, (_, setting) in command.setting_flags(arguments).items()}
    options: list[str] = []
    positionals: list[str] = []
    emptied: list[str] = []
    for action in command.actions:
        if action.dest in settings:
            setting = settings[action.dest]
            carried = setting in given and setting in command.reads
            value = values[setting] if carried else None
            if value == () and setting in replaced:  # a list that a layer emptied
                option = max(action.option_strings, key=len)
                why = f"empty, which {option} cannot say"
                emptied.append(f"not in the command: {setting} ({given[setting]}): {why}\n")
        else:
            value = getattr(arguments, action.dest)
            value = None if value == action.default else value
        items = value if isinstance(value, list | tuple) else [value]
        texts = [
            shlex.quote(str(absolute(item) if isinstance(item, Path) else item))
            for item in items
            if item is not None
        ]
        if not action.option_strings:
            positionals += texts
        elif value is True:
            options.append(max(action.option_strings, key=len))
        elif texts:
            option = max(action.option_strings, key=len)
            options.append(" ".join(f"{option} {text}" for text in texts))
    written = CONTINUED.join([f"{PROGRAM} {command.name}", *options, *positionals])
    unflagged = "".join(
        f"not in the command: {setting} ({given[setting]}): no flag sets it\n"
        for setting in command.reads
        if setting in given and setting not in settings.values()
    )
    return Copy(emptied="".join(emptied), command=written + "\n", unflagged=unflagged)
