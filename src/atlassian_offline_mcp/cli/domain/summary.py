"""What a run says on stderr before it acts: the values that it ignores.

Pure: the entry gives it the arguments, the settings loaded and how the run reports, and
writes what it returns.
"""

from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING

from atlassian_offline_mcp.config.domain.settings import SETTING_PATHS, Ignored

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.cli.domain.command import Command
    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Output


def before(arguments: argparse.Namespace, loaded: Loaded, output: Output) -> str:
    """Give what a run writes on stderr before it acts: each value ignored, on its line.

    They are the values that a stronger layer replaced and the variables that name no
    setting or are empty, as loaded; then, of the values that a layer gave, those that
    the run does not apply, by its command's ``unapplied``, and in detail those of the
    settings that the command never reads. Each names its setting, if any, and its
    layer, never its value. -q leaves them out.
    """
    if output.quiet:
        return ""
    command: Command = arguments.command
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
            if output.summary == "detailed" and setting not in command.reads
        ),
    ]
    return "".join(
        f"ignored: {each.layer}: {each.why}\n"
        if each.setting is None
        else f"ignored: {each.setting} ({each.layer}): {each.why}\n"
        for each in ignored
    )
