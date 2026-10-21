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

    The data directory, and each place under it where data is written, is resolved
    (links followed, ``..`` removed) before the guard judges it, and the resolved data
    directory is what every command then uses. Links deeper inside are not followed.
    """
    try:
        values = read_settings_file(path)
    except ValueError as error:
        message = f"{path}: not a TOML file"
        raise SettingsError(message) from error
    except OSError as error:
        message = f"{path}: not readable ({type(error).__name__})"
        raise SettingsError(message) from error
    given = {key: value for key, value in overrides.items() if value is not None}
    home = Path.home().resolve()
    settings = parse_settings({**values, **given}, home)
    settings = replace(settings, data_dir=settings.data_dir.resolve())
    for place in (settings.data_dir, *settings.parts):
        resolved = place.resolve()
        problem = unsafe_location(resolved, home, git_root(resolved))
        if problem is not None:
            where = "" if place == settings.data_dir else f"{place.name}: "
            message = f"data_dir: {where}{problem}"
            raise UnsafeDataDirError(message)
    return settings
