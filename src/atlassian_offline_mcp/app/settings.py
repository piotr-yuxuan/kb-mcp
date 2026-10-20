"""Loading the settings, with the guard on where the data lives, for every command."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.settings_file import SETTINGS_PATH, git_root, read_settings_file
from atlassian_offline_mcp.domain.settings import (
    Settings,
    SettingsError,
    parse_settings,
    unsafe_location,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SETTINGS_PATH", "UnsafeDataDirError", "load_settings"]


class UnsafeDataDirError(SettingsError):
    """A data directory where company data could leave the machine."""


def load_settings(path: Path, overrides: Mapping[str, object]) -> Settings:
    """Read the settings file, let the flags that were given override it, and check all.

    The data directory is resolved (links followed, ``..`` removed) before the guard
    judges it, and the resolved path is what every command then uses: no command can
    reach a data directory the guard has not passed.
    """
    try:
        values = read_settings_file(path)
    except ValueError as error:
        message = f"{path}: not a TOML file"
        raise SettingsError(message) from error
    given = {key: value for key, value in overrides.items() if value is not None}
    home = Path.home().resolve()
    settings = parse_settings({**values, **given}, home)
    data_dir = settings.data_dir.resolve()
    problem = unsafe_location(data_dir, home, git_root(data_dir))
    if problem is not None:
        message = f"data_dir: {problem}"
        raise UnsafeDataDirError(message)
    return replace(settings, data_dir=data_dir)
