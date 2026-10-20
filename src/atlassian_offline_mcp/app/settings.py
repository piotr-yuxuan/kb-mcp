"""Loading the settings, and checking where the data would live, for every command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.settings_file import git_root, read_settings_file
from atlassian_offline_mcp.domain.settings import (
    Settings,
    SettingsError,
    parse_settings,
    unsafe_location,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def load_settings(path: Path, overrides: Mapping[str, object]) -> Settings:
    """Read the settings file, let the flags that were given override it, and check all."""
    try:
        values = read_settings_file(path)
    except ValueError as error:
        message = f"{path}: not a TOML file"
        raise SettingsError(message) from error
    given = {key: value for key, value in overrides.items() if value is not None}
    return parse_settings({**values, **given}, Path.home())


def data_dir_problem(settings: Settings) -> str | None:
    """Return why the data directory must not be used, or None when it may."""
    path = settings.data_dir
    return unsafe_location(path, Path.home(), git_root(path))
