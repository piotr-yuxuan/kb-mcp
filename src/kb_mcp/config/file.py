"""The settings file, the sources that it and the environment name, the git tree of a path.

Standard library alone (contract G): the entry reads the sources before it parses.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from kb_mcp.kernel.names import CONNECTOR, NESTING, PREFIX

if TYPE_CHECKING:
    from collections.abc import Mapping

SETTINGS_PATH = Path("~/.config/kb-mcp/config.toml")
# The table of the sources.
SOURCES = "sources"


def read_settings_file(path: Path) -> dict[str, object]:
    """Read the settings file as TOML, a missing one empty; ValueError or OSError for another."""
    path = path.expanduser()
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def git_root(path: Path) -> Path | None:
    """Return the git working tree that holds a path, existing or not, if there is one."""
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            return folder
    return None


def decoded(text: str) -> object:
    """Read a variable's JSON; give None for one that does not read, which names nothing."""
    try:
        return json.loads(text)
    except ValueError:
        return None


def named_sources(path: Path, environ: Mapping[str, str]) -> dict[str, str | None]:
    """Give each source that the settings file and the environment name, and its connector.

    The connector as the strongest writes it, else None; what does not read names nothing.
    """
    try:
        tables = [read_settings_file(path).get(SOURCES)]
    except ValueError, OSError:
        tables = []
    top = f"{PREFIX}{SOURCES}".lower()
    for name, value in sorted((name, value) for name, value in environ.items() if value):
        match name.lower().split(NESTING):
            case [first] if first == top:
                tables.append(decoded(value))
            case [first, source] if first == top:
                tables.append({source: decoded(value)})
            case [first, source, setting] if first == top and setting == CONNECTOR:
                tables.append({source: {CONNECTOR: value}})
            case [first, source, *_] if first == top:
                tables.append({source: {}})
    named: dict[str, str | None] = {}
    for table in tables:
        for source, inner in (table if isinstance(table, dict) else {}).items():
            connector = inner.get(CONNECTOR) if isinstance(inner, dict) else None
            named[source] = connector if isinstance(connector, str) else named.get(source)
    return named
