"""``check``: validate the settings and where the data directory is, and show them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.echo import setting_line
from kb_mcp.kernel.names import ExitStatus

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.settings import Loaded
    from kb_mcp.kernel.names import Detail


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Loaded]:
    """Give the settings, which the entry checked, with the layer of each and those ignored."""
    return ExitStatus.OK, loaded


def text(loaded: Loaded, detail: Detail) -> str:
    """Write each setting that a layer gave, and its value; in detail, every one and its layer.

    A secret is said to be set or not, never shown.
    """
    lines = []
    for path, kind in loaded.paths.items():
        setting = ".".join(path)
        if kind == "table" or (detail == "short" and setting not in loaded.layers):
            continue
        lines.append(setting_line(loaded, setting, detailed=detail == "detailed"))
    return "".join(f"{line}\n" for line in lines)
