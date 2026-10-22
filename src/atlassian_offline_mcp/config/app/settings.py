"""Loading the settings, with the guard on where the data and the logs live, for every command."""

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
from atlassian_offline_mcp.observability.adapters.logs import default_log_folder

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["UnsafeDataDirError", "load_settings"]


class UnsafeDataDirError(SettingsError):
    """A data directory, or a log folder, where company data could leave the machine."""


def load_settings(path: Path, flags: Mapping[str, tuple[str, object]], home: Path) -> Loaded:
    """Read the settings file, the environment and the flags given, each stronger, and check.

    ``flags`` maps each flag, such as ``--site``, to the setting it overrides, by its
    path joined by dots, and its value, None when it was not given. The file's layer is
    its name, a variable's its name. ``~`` in a path is ``home``, which must be
    resolved. What was ignored is each variable that names no setting or is empty,
    then each value replaced.

    The data directory, each place under it where data is written, and the log folder,
    the user's (``default_log_folder``) when none is set, are resolved (links followed,
    ``..`` removed) before the guard judges them, as logs hold titles and queries; the
    resolved data directory and log folder are what every command then uses. Links
    deeper inside are not followed.
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
    logs = loaded.settings.logs
    settings = loaded.settings.model_copy(
        update={
            "data_dir": loaded.settings.data_dir.resolve(),
            "logs": logs.model_copy(update={"dir": (logs.dir or default_log_folder()).resolve()}),
        }
    )
    places = [
        ("data_dir", settings.data_dir, ""),
        *(("data_dir", part, f"{part.name}: ") for part in settings.parts),
        ("logs.dir", settings.logs.dir, ""),
    ]
    for setting, place, where in places:
        resolved = place.resolve()
        problem = unsafe_location(resolved, home, git_root(resolved))
        if problem is not None:
            message = f"{setting} ({loaded.layer(setting)}): {where}{problem}"
            raise UnsafeDataDirError(message)
    return Loaded(settings, loaded.layers, (*unread, *loaded.ignored), loaded.replaced)
