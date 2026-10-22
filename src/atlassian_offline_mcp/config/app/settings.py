"""Loading the settings, with the guard on where the data lives, for every command."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic_settings import EnvSettingsSource

from atlassian_offline_mcp.config.adapters.settings_file import git_root, read_settings_file
from atlassian_offline_mcp.config.domain.settings import (
    Entry,
    Loaded,
    Settings,
    SettingsError,
    environment_entries,
    file_entries,
    settings_of,
    unsafe_location,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["UnsafeDataDirError", "load_settings"]


class UnsafeDataDirError(SettingsError):
    """A data directory where company data could leave the machine."""


def load_settings(path: Path, flags: Mapping[str, tuple[str, object]], home: Path) -> Loaded:
    """Read the settings file, the environment and the flags given, each stronger, and check.

    ``flags`` maps each flag, such as ``--site``, to the setting it overrides, by its
    path joined by dots, and its value, None when it was not given. The file's layer is
    its name, a variable's its name. ``~`` in a path is ``home``, which must be
    resolved. What was ignored is each variable that names no setting or is empty,
    then each value replaced.

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
    environment, unread = environment_entries(os.environ, EnvSettingsSource(Settings))
    loaded = settings_of(
        [
            *file_entries(values, path.name),
            *environment,
            *(
                Entry(tuple(setting.split(".")), value, flag)
                for flag, (setting, value) in flags.items()
                if value is not None
            ),
        ],
        home,
    )
    settings = loaded.settings.model_copy(update={"data_dir": loaded.settings.data_dir.resolve()})
    for place in (settings.data_dir, *settings.parts):
        resolved = place.resolve()
        problem = unsafe_location(resolved, home, git_root(resolved))
        if problem is not None:
            where = "" if place == settings.data_dir else f"{place.name}: "
            message = f"data_dir ({loaded.layer('data_dir')}): {where}{problem}"
            raise UnsafeDataDirError(message)
    return Loaded(settings, loaded.layers, (*unread, *loaded.ignored), loaded.replaced)
