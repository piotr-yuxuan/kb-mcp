"""``check``: validate the settings and where the data directory is, and show them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.echo import setting_line
from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Detail


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Loaded]:
    """Give the effective settings, which the entry checked, the data directory included.

    With them come the layer of each and the values ignored.
    """
    return ExitStatus.OK, loaded


def text(loaded: Loaded, summary: Detail) -> str:
    """Write each setting that a layer gave, and its value; in detail, every one and its layer.

    A setting is named by its path, its names joined by dots; a secret is said to be set
    or not, never shown. The layer is the settings file's name, a variable's, a flag, or
    default.
    """
    lines = []
    for path, kind in loaded.paths.items():
        setting = ".".join(path)
        if kind == "table" or (summary == "short" and setting not in loaded.layers):
            continue
        lines.append(setting_line(loaded, setting, detailed=summary == "detailed"))
    return "".join(f"{line}\n" for line in lines)
