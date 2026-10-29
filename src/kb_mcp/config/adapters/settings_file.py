"""The settings file, and the git working tree that may hold a path."""

from __future__ import annotations

import tomllib
from pathlib import Path

SETTINGS_PATH = Path("~/.config/kb-mcp/config.toml")


def read_settings_file(path: Path) -> dict[str, object]:
    """Read the settings file as TOML; a missing file holds no settings.

    Raises ValueError for a file that is not TOML (tomllib's TOMLDecodeError) or not
    text, and OSError for one that cannot be read, such as a folder.
    """
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
