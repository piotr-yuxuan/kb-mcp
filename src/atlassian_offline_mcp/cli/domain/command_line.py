"""The command to copy: a run written as the command line that runs it again.

Pure: the entry gives it the arguments, the settings' values and the layers of those that
a layer gave, and writes what it returns, so that it can be copied, or kept in the shell's
history.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import PROGRAM

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping

    from atlassian_offline_mcp.cli.domain.command import Command

# What ends a line but the last, so that the shell reads one command, and indents the next.
CONTINUED = " \\\n  "


def command_line(
    arguments: argparse.Namespace,
    values: Mapping[str, object],
    given: Mapping[str, str],
    absolute: Callable[[Path], Path],
) -> str:
    """Write the command that runs this run again, an option to a line, then a newline.

    The program and the subcommand come first, then each option among the command's
    ``actions``, its repeats on its line, then the positionals. A flag carries its
    setting's value, from ``values`` by the setting's path, when the command reads the
    setting and a layer gave it, the file included (``given``, by the layer's name, for
    each value that the run applies); another option carries its value when it is not
    its default. A path is made ``absolute``; each value is quoted for the shell. What
    is not among the actions is never written: the output's options, the question's, and
    the settings that no flag sets, such as the model or the secrets. No flag says an
    empty list: a line before the command names such a setting and its layer. A line
    after the command names each setting that it reads, that a layer gave and that no
    flag of it sets, with its layer, never its value. The command, run again, takes
    these from the settings file, the environment or their defaults.
    """
    command: Command = arguments.command
    settings = {dest: setting for dest, (_, setting) in command.setting_flags().items()}
    options: list[str] = []
    positionals: list[str] = []
    unsaid: list[str] = []
    for action in command.actions:
        if action.dest in settings:
            setting = settings[action.dest]
            carried = setting in given and setting in command.reads
            value = values[setting] if carried else None
            if value == ():  # a list of the settings, empty
                option = max(action.option_strings, key=len)
                why = f"empty, which {option} cannot say"
                unsaid.append(f"not in the command: {setting} ({given[setting]}): {why}\n")
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
    return "".join(unsaid) + written + "\n" + unflagged
