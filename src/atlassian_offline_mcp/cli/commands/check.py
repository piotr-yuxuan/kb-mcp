"""``check``: validate the settings and the data directory, and show them."""

from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING

from atlassian_offline_mcp.config.domain.settings import DEFAULT_LAYER, SETTING_PATHS
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
        layer = loaded.layer(setting)
        if kind == "table" or (summary == "short" and layer == DEFAULT_LAYER):
            continue
        value = reduce(getattr, path, loaded.settings)
        if kind == "secret":
            shown = "not set" if value is None else "set"
        elif kind == "list":
            shown = ", ".join(value) or "(none)"
        else:
            shown = "(not set)" if value is None else str(value)
        lines.append(f"{setting}: {shown}" + ("" if summary == "short" else f" [{layer}]"))
    return "".join(f"{line}\n" for line in lines)
