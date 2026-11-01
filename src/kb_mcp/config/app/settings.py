"""Loading the settings, with the guard on where the data and the logs live, for every command."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_settings import EnvSettingsSource

from kb_mcp.config.adapters.settings_file import SETTINGS_PATH, git_root, read_settings_file
from kb_mcp.config.domain.former_name import (
    FORMER_DATA_DIR,
    FORMER_SETTINGS_FILE,
    Found,
    refuse_former_name,
)
from kb_mcp.config.domain.settings import (
    DEFAULT_DATA_DIR,
    Entry,
    Loaded,
    Settings,
    SettingsError,
    at_home,
    environment_entries,
    file_entries,
    settings_of,
    shared_entries,
    unsafe_location,
)
from kb_mcp.observability.adapters.logs import default_log_folder

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["UnsafeDataDirError", "load_settings"]


class UnsafeDataDirError(SettingsError):
    """A data directory, or a log folder, where company data could leave the machine."""


def load_settings(
    path: Path, flags: Mapping[str, tuple[str, object]], home: Path, model: type[Settings]
) -> Loaded:
    """Read the settings file, the environment and the flags given, each stronger, and check.

    The settings are of ``model``, which ``settings_model`` composed. ``flags`` maps
    each flag, such as ``--site``, to the setting it overrides, by its path joined by
    dots, and its value, None when it was not given. The file's layer is its name, the
    former settings file's its path from ``~``, and a variable's its name. ``~`` in a
    path is ``home``, which must be resolved. What was ignored is each variable that
    names no setting or is empty, then each value replaced.

    Telemetry's endpoint has two layers more, OpenTelemetry's own variables, as
    ``shared_entries`` reads them: ``OTEL_EXPORTER_OTLP_ENDPOINT``, below the file,
    ignored unless the setting would take it, and ``OTEL_SDK_DISABLED`` when true, above
    all, which leaves the endpoint unset: telemetry off.

    The data directory, each place under it where data is written, and the log folder,
    the user's (``default_log_folder``) when none is set, are resolved (links followed,
    ``..`` removed) before the guard judges them, as logs hold titles and queries; the
    resolved data directory and log folder are what every command then uses. Links
    deeper inside are not followed.

    Before the guard, ``refuse_former_name`` judges what the program's former name left,
    from what exists under ``home``: the former settings file is read in place of the
    default one when that is missing, so that its values are judged too, but for its
    keys renamed since, which the stop names, as it does of a file given under the former
    name. The settings file given and the data directory are compared with the defaults
    once resolved, so that any path naming a default is taken for it.
    """
    defaults = {
        place: at_home(place, home)
        for place in (SETTINGS_PATH, FORMER_SETTINGS_FILE, Path(DEFAULT_DATA_DIR), FORMER_DATA_DIR)
    }
    found = Found(
        settings_file=SETTINGS_PATH,
        settings_given=path,
        reads_default=path.expanduser().resolve() == defaults[SETTINGS_PATH].resolve(),
        existing=frozenset(place for place, there in defaults.items() if there.exists()),
        former_data_in_git=git_root(defaults[FORMER_DATA_DIR]) is not None,
    )
    read = defaults[FORMER_SETTINGS_FILE] if found.former_file_judged else path
    try:
        values = read_settings_file(read)
    except ValueError as error:
        message = f"{read}: not a TOML file"
        raise SettingsError(message) from error
    except OSError as error:
        message = f"{read}: not readable ({type(error).__name__})"
        raise SettingsError(message) from error
    judged = found.model_copy(update={"keys_read": frozenset(values)})
    environment, unread = environment_entries(os.environ, EnvSettingsSource(model), model)
    below, above, unshared = shared_entries(os.environ)
    loaded = settings_of(
        [
            *below,
            *file_entries(
                {name: value for name, value in values.items() if name not in judged.renamed_keys},
                str(FORMER_SETTINGS_FILE) if found.former_file_judged else path.name,
                model,
            ),
            *environment,
            *(
                Entry(path=tuple(setting.split(".")), value=value, layer=flag)
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
    refuse_former_name(judged, loaded, settings.data_dir, os.environ, home)
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
