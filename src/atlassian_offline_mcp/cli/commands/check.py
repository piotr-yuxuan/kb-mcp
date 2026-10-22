"""``check``: validate the settings and the data directory, and show them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.summary import setting_line
from atlassian_offline_mcp.config.domain.settings import SETTING_PATHS
from atlassian_offline_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Loaded]:
    """Give the effective settings, which the entry checked, the data directory included.

    With them come the layer of each and the values ignored.
    """
    return ExitStatus.OK, loaded


def text(loaded: Loaded, summary: Summary) -> str:
    """Write each setting that a layer gave, and its value; in detail, every one and its layer.

    A setting is named by its path, its names joined by dots; a secret is said to be set
    or not, never shown. The layer is the settings file's name, a variable's, a flag, or
    default.
    """
    lines = []
    for path, kind in SETTING_PATHS.items():
        setting = ".".join(path)
        if kind == "table" or (summary == "short" and setting not in loaded.layers):
            continue
        lines.append(setting_line(loaded, setting, detailed=summary == "detailed"))
    return "".join(f"{line}\n" for line in lines)
