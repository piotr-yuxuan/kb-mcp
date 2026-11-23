"""Loading the settings from the file, the environment and the flags, and the guard on places."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import platformdirs

from kb_mcp.config.file import git_root, read_settings_file
from kb_mcp.config.settings import (
    LayerValue,
    Loaded,
    Settings,
    SettingsError,
    environment_entries,
    file_entries,
    settings_of,
    shared_entries,
    unsafe_location,
)
from kb_mcp.kernel.names import PROGRAM

if TYPE_CHECKING:
    from collections.abc import Mapping


class UnsafeDataDirError(SettingsError):
    """A data directory, or a log folder, where company data could leave the machine."""


def default_log_folder() -> Path:
    """Return the user's log folder for this program, as platformdirs places it."""
    return Path(platformdirs.user_log_dir(PROGRAM, appauthor=False))


def load_settings(
    path: Path, flags: Mapping[str, tuple[str, object]], home: Path, model: type[Settings]
) -> Loaded:
    """Read the settings file, the environment and ``flags``, each stronger, and guard the places.

    ``flags`` maps a flag to its setting and its value, None when not given. The data
    directory and the log folder are resolved before the guard, and given so.
    """
    try:
        values = read_settings_file(path)
    except ValueError as error:
        message = f"{path}: not a TOML file"
        raise SettingsError(message) from error
    except OSError as error:
        message = f"{path}: not readable ({type(error).__name__})"
        raise SettingsError(message) from error
    environment, unread = environment_entries(os.environ, model)
    below, above, unshared = shared_entries(os.environ)
    loaded = settings_of(
        [
            *below,
            *file_entries(values, path.name, model),
            *environment,
            *(
                LayerValue(path=tuple(setting.split(".")), value=value, layer=flag)
                for flag, (setting, value) in flags.items()
                if value is not None
            ),
            *above,
        ],
        home,
        model,
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
    return Loaded(
        settings=settings,
        layers=loaded.layers,
        ignored=(*unread, *unshared, *loaded.ignored),
        replaced=loaded.replaced,
    )
