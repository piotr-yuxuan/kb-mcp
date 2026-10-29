"""Tests of the settings, their layers, and the guard on where data may live."""

from __future__ import annotations

import os
import re
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import pytest
from pydantic import BaseModel, Field, SecretStr, ValidationError, create_model
from pydantic_settings import EnvSettingsSource

from kb_mcp.cli.main import main
from kb_mcp.config.app.settings import UnsafeDataDirError, load_settings
from kb_mcp.config.domain.settings import (
    SETTING_PATHS,
    ConfluenceSource,
    Entry,
    Ignored,
    Loaded,
    Settings,
    SettingsError,
    environment_entries,
    file_entries,
    setting_paths,
    settings_of,
    unsafe_location,
)
from kb_mcp.kernel.endpoint import Service, loopback, refused_endpoint
from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

HOME = Path("/home/someone")
FILE = "config.toml"
# Values that no output may hold, as a secret or a value given.
SENTINEL = "sentinel-0c1e5a"


def from_file(values: dict[str, object]) -> Settings:
    """Build the settings from a settings file's values alone."""
    return settings_of(file_entries(values, FILE), HOME).settings


def user_log_folder(home: Path) -> Path:
    """Give the user's log folder under a home, where the platform keeps it, by plan 016.

    On Linux, without ``XDG_STATE_HOME``, as platformdirs places it.
    """
    return {
        "darwin": home / "Library" / "Logs" / "kb-mcp",
        "linux": home / ".local" / "state" / "kb-mcp" / "log",
    }[sys.platform]


def test_settings_are_normalised() -> None:
    """The site becomes https://<host>, the endpoint loses its trailing slash."""
    settings = from_file(
        {
            "site": "https://Example.atlassian.net/",
            "email": "someone@example.invalid",
            "data_dir": "~/mirror",
            "model": "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0",
            "search_mode": "hybrid",
            "embedding_url": "http://127.0.0.1:8080/v1/",
            "sources": {
                "confluence": {"spaces": ["ENG", "~5f1a2b"]},
                "jira": {"projects": ["PAY"]},
            },
        }
    )
    assert settings.site == "https://example.atlassian.net"
    assert settings.email == "someone@example.invalid"
    assert settings.data_dir == HOME / "mirror"
    assert settings.sources.confluence.spaces == ("ENG", "~5f1a2b")
    assert settings.sources.jira.projects == ("PAY",)
    assert (settings.model, settings.search_mode, settings.embedding_url) == (
        "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0",
        "hybrid",
        "http://127.0.0.1:8080/v1",
    )
    mirror = Path("/data/mirror")
    parts = Settings(data_dir=mirror).parts
    assert {mirror / "vectors.sqlite", mirror / "conversions.sqlite", mirror / "eval"} <= set(parts)
    assert mirror / "models" not in parts


def test_the_alias_file_is_in_the_data_directory() -> None:
    """The user's aliases are <data>/aliases.toml, by plan 043, and no setting names them."""
    assert Settings(data_dir=Path("/data/mirror")).aliases == Path("/data/mirror/aliases.toml")
    assert not any("alias" in ".".join(path) for path in SETTING_PATHS)


def test_the_default_embeddings_come_from_ollama_on_this_machine() -> None:
    """Ollama's own address, and the model that plan 018 chose."""
    settings = from_file({})
    assert (settings.embedding_url, settings.model) == (
        "http://127.0.0.1:11434/v1",
        "qwen3-embedding:0.6b",
    )


def test_by_default_index_cuts_windows_and_search_is_hybrid() -> None:
    """Plan 025: with no file, variable or flag, windows, searched by words and meaning."""
    settings = settings_of([], HOME).settings
    assert (settings.chunking, settings.search_mode) == ("windows", "hybrid")


def test_the_default_data_directory_is_under_the_home() -> None:
    """With nothing set, the data lives in ~/kb-mcp and no site is known."""
    settings = from_file({})
    assert (settings.site, settings.data_dir) == (None, HOME / "kb-mcp")
    assert (settings.sources.confluence.spaces, settings.sources.jira.projects) == ((), ())


@pytest.mark.parametrize(
    ("given", "data_dir"),
    [
        (None, HOME / "kb-mcp"),
        ("~", HOME),
        ("~/mirror", HOME / "mirror"),
        ("/data/mirror", Path("/data/mirror")),
    ],
)
def test_the_data_directory_is_absolute_with_the_home_given_for_the_tilde(
    given: str | None, data_dir: Path
) -> None:
    """Data written under a relative path would land below the current directory."""
    entries = [] if given is None else [Entry(("data_dir",), given, "--data-dir")]
    assert settings_of(entries, HOME).settings.data_dir == data_dir


def test_no_settings_hold_a_path_under_the_tilde_without_a_home() -> None:
    """Built without the loader's home, the default data directory is refused too."""
    with pytest.raises(ValidationError):
        Settings()
    with pytest.raises(ValidationError):
        Settings(data_dir=Path("~/mirror"))


def test_every_setting_is_described() -> None:
    """Plan 020 writes the settings' reference from these descriptions, at every depth."""
    for path in SETTING_PATHS:
        model: type[BaseModel] = Settings
        for name in path[:-1]:
            model = model.model_fields[name].annotation
        assert model.model_fields[path[-1]].description, path


def test_each_setting_is_read_by_its_kind() -> None:
    """Tables and lists are JSON; the token and the embedding key are the secrets.

    The data directory, the log folder and the work log's folder are paths, in which
    ``~`` is the home.
    """
    assert {path: kind for path, kind in SETTING_PATHS.items() if kind != "value"} == {
        ("api_token",): "secret",
        ("data_dir",): "path",
        ("embedding_api_key",): "secret",
        ("logs",): "table",
        ("logs", "dir"): "path",
        ("telemetry",): "table",
        ("rerank",): "table",
        ("sources",): "table",
        ("sources", "confluence"): "table",
        ("sources", "confluence", "spaces"): "list",
        ("sources", "jira"): "table",
        ("sources", "jira", "projects"): "list",
        ("sources", "worklog"): "table",
        ("sources", "worklog", "path"): "path",
    }


@pytest.mark.parametrize(
    ("annotation", "kind"),
    [
        (tuple[str, ...] | None, "list"),
        (Annotated[SecretStr, Field(min_length=1)] | None, "secret"),
        (Literal["a", "b"] | None, "value"),
        (Annotated[Path, Field(description="a path")], "path"),
    ],
)
def test_a_setting_s_kind_is_seen_through_none_and_annotated(annotation: object, kind: str) -> None:
    """A setting that may be None, or carries rules, is read as its type is."""
    model = create_model("Table", setting=(annotation, None))
    assert setting_paths(model) == {("setting",): kind}


@pytest.mark.parametrize(
    "annotation",
    [list[str], frozenset[str], dict[str, str], ConfluenceSource | None, SecretStr | int],
)
def test_a_setting_of_a_type_that_has_no_kind_is_refused(annotation: object) -> None:
    """Read as text, a list would not be parsed as JSON, and a secret taken from the file."""
    model = create_model("Table", setting=(annotation, None))
    with pytest.raises(TypeError, match="a type that has no kind"):
        setting_paths(model)


@pytest.mark.parametrize(
    ("values", "named"),
    [
        ({"sight": "https://x.atlassian.net"}, "sight (config.toml): not a setting"),
        ({"sources": {"jira": {"projets": ["PLAT"]}}}, "sources.jira.projets (config.toml):"),
        ({"sources": {"worklog": {"spaces": []}}}, "sources.worklog.spaces (config.toml):"),
        ({"unknown": {}}, "unknown (config.toml): not a setting"),
        ({"sources": {"gitlab": {}}}, "sources.gitlab (config.toml): not a setting"),
        ({"site": "http://x.atlassian.net"}, "site (config.toml):"),
        ({"site": "https://user@x.atlassian.net"}, "site (config.toml):"),
        ({"site": "https://x.atlassian.net/wiki"}, "site (config.toml):"),
        ({"site": "https://["}, "site (config.toml): an https address with a host name alone"),
        ({"data_dir": 3}, "data_dir (config.toml):"),
        ({"data_dir": "relative/path"}, "data_dir (config.toml): an absolute path"),
        ({"data_dir": "~/mirror\0"}, "data_dir (config.toml):"),
        ({"data_dir": "~someone/mirror"}, "data_dir (config.toml):"),
        (
            {"sources": {"confluence": {"spaces": "ENG"}}},
            "sources.confluence.spaces (config.toml):",
        ),
        (
            {"sources": {"confluence": {"spaces": ["ENG", "not a key"]}}},
            "sources.confluence.spaces.1 (config.toml): a space key",
        ),
        ({"sources": {"jira": {"projects": ["pay"]}}}, "sources.jira.projects.0 (config.toml)"),
        ({"sources": {"jira": 3}}, "sources.jira (config.toml):"),
        ({"model": "../elsewhere"}, "model (config.toml):"),
        ({"model": ["bge-small-en-v1.5"]}, "model (config.toml):"),
        ({"model": "qwen3 embedding"}, "model (config.toml):"),
        ({"model": "a" * 129}, "model (config.toml): the name of an embedding model, such as"),
        ({"embedding_url": "http://user@127.0.0.1:11434/v1"}, "embedding_url (config.toml):"),
        ({"embedding_url": "http://127.0.0.1:11434/v1?key=1"}, "embedding_url (config.toml):"),
        ({"embedding_url": "http://127.0.0.1:11434/v1#here"}, "embedding_url (config.toml):"),
        ({"embedding_url": "http://127.0.0.1:port/v1"}, "embedding_url (config.toml):"),
        ({"embedding_url": "http://127.0.0.1:0/v1"}, "embedding_url (config.toml):"),
        ({"embedding_url": "http://[::1/v1"}, "embedding_url (config.toml):"),
        ({"embedding_url": "ftp://127.0.0.1/v1"}, "embedding_url (config.toml):"),
        ({"embedding_url": "http:///v1"}, "embedding_url (config.toml):"),
        ({"embedding_url": 11434}, "embedding_url (config.toml):"),
        ({"search_mode": "fuzzy"}, "search_mode (config.toml):"),
        ({"logs": {"dir": "relative/logs"}}, "logs.dir (config.toml): an absolute path"),
        ({"logs": "~/logs"}, "logs (config.toml):"),
    ],
)
def test_unusable_settings_are_refused_by_name_and_layer(
    values: dict[str, object], named: str
) -> None:
    """Each refusal names the setting at fault and the layer that gave it."""
    with pytest.raises(SettingsError, match=re.escape(named)):
        from_file(values)


@pytest.mark.parametrize(
    ("given", "endpoint"),
    [
        ("http://127.0.0.1:4318", "http://127.0.0.1:4318"),
        ("http://127.0.0.1:4318/", "http://127.0.0.1:4318"),
        ("HTTP://127.1.2.3:4318", "http://127.1.2.3:4318"),
        ("http://[::1]:4318", "http://[::1]:4318"),
    ],
)
def test_telemetry_s_endpoint_is_an_http_address_of_this_machine(given: str, endpoint: str) -> None:
    """A literal address of this machine, with a port, which OTLP's paths follow."""
    assert from_file({"telemetry": {"endpoint": given}}).telemetry.endpoint == endpoint


def test_telemetry_is_off_by_default() -> None:
    """No endpoint is set, so nothing is sent anywhere."""
    assert from_file({}).telemetry.endpoint is None


@pytest.mark.parametrize(
    "given",
    [
        "http://localhost:4318",
        "http://192.0.2.1:4318",
        "http://user@127.0.0.1:4318",
        "https://127.0.0.1:4318",
        "http://127.0.0.1",
        "http://127.0.0.1:4318/v1/traces",
        "http://127.0.0.1:4318?key=1",
        "http://127.0.0.1:4318#here",
        "http://127.0.0.1:0",
        "http://[::1:4318",
        "127.0.0.1:4318",
    ],
)
def test_telemetry_s_endpoint_elsewhere_or_with_more_than_its_address_is_refused(
    given: str,
) -> None:
    """Telemetry holds titles and queries: this machine alone, written as an address.

    Named, the setting and its layer, with what it must be, never its value.
    """
    with pytest.raises(SettingsError) as refused:
        from_file({"telemetry": {"endpoint": given}})
    assert str(refused.value) == (
        "telemetry.endpoint (config.toml): an http address of this machine, with a port and"
        " no path, such as http://127.0.0.1:4318; write 127.0.0.1 for localhost"
    )


def test_an_empty_table_of_settings_leaves_them_at_their_defaults() -> None:
    """``[sources.jira]`` with nothing under it yet is a table of the settings."""
    assert from_file({"sources": {"jira": {}}}).sources.jira.projects == ()


def test_an_empty_table_gives_each_setting_under_it_and_none_other() -> None:
    """Each at its default, by the table's layer, so that it replaces a weaker value there."""
    loaded = settings_of(
        [
            *file_entries({"site": "https://file.example.invalid"}, FILE),
            *file_entries({"sources": {"confluence": {"spaces": ["ENG"]}}}, FILE),
            *file_entries({"sources": {}}, "stronger"),
        ],
        HOME,
    )
    assert loaded.settings.sources.confluence.spaces == ()
    assert loaded.layers == {
        "site": FILE,
        "sources.confluence.spaces": "stronger",
        "sources.jira.projects": "stronger",
        "sources.worklog.path": "stronger",
        "sources.worklog.archives": "stronger",
    }
    assert loaded.ignored == (Ignored("sources.confluence.spaces", FILE, "replaced by stronger"),)
    assert loaded.replaced == {"sources.confluence.spaces"}


def test_a_value_replacing_an_empty_table_s_default_replaces_no_value_given() -> None:
    """The table's layer wrote none: the stronger value is its setting's, nothing ignored."""
    loaded = settings_of(
        [
            *file_entries({"sources": {"jira": {}}}, FILE),
            Entry(("sources", "jira", "projects"), ["PRB"], "--project"),
        ],
        HOME,
    )
    assert loaded.settings.sources.jira.projects == ("PRB",)
    assert loaded.layers == {"sources.jira.projects": "--project"}
    assert loaded.ignored == ()
    assert loaded.replaced == frozenset()


@pytest.mark.parametrize(
    ("key", "table"), [("spaces", "[sources.confluence]"), ("projects", "[sources.jira]")]
)
def test_the_old_lists_at_the_top_of_the_file_are_refused_with_their_new_place(
    key: str, table: str
) -> None:
    """Plan 015 moved spaces and projects into their sources' tables, without an alias."""
    with pytest.raises(SettingsError) as refused:
        file_entries({key: ["PLAT"]}, FILE)
    assert str(refused.value) == f"{key} ({FILE}): moved, as {key} under {table}"


@pytest.mark.parametrize("key", ["_cli_parse_args", "_env_file", "SITE", "unknown"])
def test_the_model_refuses_a_key_that_names_no_setting_whatever_its_layer(key: str) -> None:
    """A key that names no setting is refused, from any layer, never taken as an option.

    pydantic-settings' model takes ``_cli_parse_args`` as one, which parses sys.argv,
    ``_env_file``, which reads the file named, and ``SITE`` as ``site``.
    """
    with pytest.raises(SettingsError, match=re.escape(f"{key} (a layer):")):
        settings_of([Entry((key,), "/etc/passwd", "a layer")], HOME)


def test_a_refusal_never_holds_the_value() -> None:
    """The setting and its layer are named; what the layer held is not."""
    with pytest.raises(SettingsError) as refused:
        from_file({"site": "https://secret-host.example.invalid/wiki"})
    assert "secret-host" not in str(refused.value)


def test_the_layer_of_a_path_that_names_no_setting_is_refused() -> None:
    """A misspelt path would otherwise name the default layer, silently."""
    with pytest.raises(KeyError):
        Loaded(from_file({})).layer("sources.confluence.spacez")


def test_a_stronger_layer_replaces_a_weaker_one_and_the_weaker_is_ignored() -> None:
    """A flag wins over the file; the file's value is recorded as replaced."""
    loaded = settings_of(
        [
            Entry(("site",), "https://file.example.invalid", FILE),
            Entry(("site",), "https://flag.example.invalid", "--site"),
        ],
        HOME,
    )
    assert loaded.settings.site == "https://flag.example.invalid"
    assert loaded.layers == {"site": "--site"}
    assert loaded.ignored == (Ignored("site", FILE, "replaced by --site"),)


def test_a_stronger_list_replaces_a_weaker_one_whole() -> None:
    """A list is never joined to another: the flag's spaces are all the spaces."""
    loaded = settings_of(
        [
            *file_entries({"sources": {"confluence": {"spaces": ["ENG", "OPS"]}}}, FILE),
            Entry(("sources", "confluence", "spaces"), ["MFS"], "--space"),
        ],
        HOME,
    )
    assert loaded.settings.sources.confluence.spaces == ("MFS",)
    assert loaded.layers == {"sources.confluence.spaces": "--space"}
    assert loaded.ignored == (Ignored("sources.confluence.spaces", FILE, "replaced by --space"),)


def test_a_value_replaces_a_weaker_table_above_or_below_it() -> None:
    """A value at a table's place replaces the values under it, and the reverse."""
    loaded = settings_of(
        [
            Entry(("sources", "jira", "projects"), ["PLAT"], FILE),
            Entry(("sources", "jira"), {}, "stronger"),
            Entry(("sources", "jira", "projects"), ["PRB"], "strongest"),
        ],
        HOME,
    )
    assert loaded.settings.sources.jira.projects == ("PRB",)
    assert loaded.ignored == (
        Ignored("sources.jira.projects", FILE, "replaced by stronger"),
        Ignored("sources.jira", "stronger", "replaced by strongest"),
    )


def test_the_loader_takes_the_file_then_the_flags_and_makes_the_home_s_path(
    tmp_path: Path,
) -> None:
    """The flags given override the file; one not given leaves it; ~ is the home given."""
    home = (tmp_path / "home").resolve()
    config = tmp_path / "work.toml"
    config.write_text(
        'site = "https://file.example.invalid"\ndata_dir = "~/from-file"\n'
        '[sources.jira]\nprojects = ["PLAT"]\n',
        "utf-8",
    )
    loaded = load_settings(
        config,
        {
            "--data-dir": ("data_dir", "~/from-flag"),
            "--site": ("site", None),
            "--project": ("sources.jira.projects", ["PRB", "PAY"]),
        },
        home,
    )
    assert loaded.settings.data_dir == home / "from-flag"
    assert loaded.settings.site == "https://file.example.invalid"
    assert loaded.settings.sources.jira.projects == ("PRB", "PAY")
    assert loaded.layers == {
        "site": "work.toml",
        "data_dir": "--data-dir",
        "sources.jira.projects": "--project",
    }
    assert set(loaded.ignored) == {
        Ignored("data_dir", "work.toml", "replaced by --data-dir"),
        Ignored("sources.jira.projects", "work.toml", "replaced by --project"),
    }


def loaded_from(
    tmp_path: Path, text: str, flags: dict[str, tuple[str, object]] | None = None
) -> Loaded:
    """Load the settings from a settings file of this text, the environment and flags."""
    home = (tmp_path / "home").resolve()
    config = tmp_path / FILE
    config.write_text(text, "utf-8")
    return load_settings(config, flags or {}, home)


def test_the_log_folder_is_the_user_s_unless_one_is_set(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """By default where the platform keeps the user's logs, an empty table too; else as set.

    ``~`` in the one set is the home.
    """
    home = (tmp_path / "home").resolve()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    by_default = loaded_from(tmp_path, "")
    assert by_default.settings.logs.dir == user_log_folder(home)
    assert by_default.layer("logs.dir") == "default"
    empty = loaded_from(tmp_path, "[logs]\n")
    assert empty.settings.logs.dir == user_log_folder(home)
    assert empty.layer("logs.dir") == FILE
    assert loaded_from(tmp_path, '[logs]\ndir = "~/logs"\n').settings.logs.dir == home / "logs"


def test_the_user_s_log_folder_passes_the_guard_too(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A home inside a git working tree holds it: refused, naming the default layer."""
    (tmp_path / "repository" / ".git").mkdir(parents=True)
    home = (tmp_path / "repository" / "home").resolve()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    elsewhere = {"--data-dir": ("data_dir", str(tmp_path / "data"))}
    with pytest.raises(UnsafeDataDirError, match=r"^logs\.dir \(default\): inside the git"):
        load_settings(tmp_path / FILE, elsewhere, home)


def test_opentelemetry_s_endpoint_is_a_layer_below_the_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Shared by other programs, it gives the endpoint that no setting gives, named.

    The file's, then the variable's, replace it, and it is said to be replaced.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")
    shared = loaded_from(tmp_path, "")
    assert shared.settings.telemetry.endpoint == "http://127.0.0.1:4317"
    assert shared.layers == {"telemetry.endpoint": "OTEL_EXPORTER_OTLP_ENDPOINT"}
    assert shared.ignored == ()

    text = '[telemetry]\nendpoint = "http://127.0.0.1:4318"\n'
    from_the_file = loaded_from(tmp_path, text)
    assert from_the_file.settings.telemetry.endpoint == "http://127.0.0.1:4318"
    assert from_the_file.layers == {"telemetry.endpoint": FILE}
    assert from_the_file.ignored == (
        Ignored("telemetry.endpoint", "OTEL_EXPORTER_OTLP_ENDPOINT", f"replaced by {FILE}"),
    )

    variable = "KB_MCP_TELEMETRY__ENDPOINT"
    monkeypatch.setenv(variable, "http://127.0.0.1:4319")
    from_the_variable = loaded_from(tmp_path, text)
    assert from_the_variable.settings.telemetry.endpoint == "http://127.0.0.1:4319"
    assert from_the_variable.layers == {"telemetry.endpoint": variable}


@pytest.mark.parametrize(
    "given",
    [
        "http://localhost:4318",
        f"http://{SENTINEL}.example.invalid:4318",
        f"http://{SENTINEL}@127.0.0.1:4318",
        "https://127.0.0.1:4318",
        "http://127.0.0.1:4318/v1/traces",
        "",
    ],
)
def test_opentelemetry_s_endpoint_that_the_setting_would_refuse_is_ignored(
    tmp_path: Path, monkeypatch: MonkeyPatch, given: str
) -> None:
    """Said, with what it must be, never its value; telemetry stays off, or as set."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", given)
    loaded = loaded_from(tmp_path, "")
    assert loaded.settings.telemetry.endpoint is None
    assert loaded.layers == {}
    (ignored,) = loaded.ignored
    assert (ignored.setting, ignored.layer) == ("telemetry.endpoint", "OTEL_EXPORTER_OTLP_ENDPOINT")
    assert ignored.why.startswith("not an http address of this machine, with a port and no path")
    assert SENTINEL not in ignored.why
    text = '[telemetry]\nendpoint = "http://127.0.0.1:4318"\n'
    assert loaded_from(tmp_path, text).settings.telemetry.endpoint == "http://127.0.0.1:4318"


@pytest.mark.parametrize("disabled", ["true", "TRUE", " True\n"])
def test_opentelemetry_disabled_leaves_telemetry_s_endpoint_unset_whatever_gave_it(
    tmp_path: Path, monkeypatch: MonkeyPatch, disabled: str
) -> None:
    """``OTEL_SDK_DISABLED``, true as the SDK reads it, is above every layer.

    The values it replaces are said to be, the file's and the variables' alike.
    """
    monkeypatch.setenv("OTEL_SDK_DISABLED", disabled)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")
    loaded = loaded_from(tmp_path, '[telemetry]\nendpoint = "http://127.0.0.1:4318"\n')
    assert loaded.settings.telemetry.endpoint is None
    assert loaded.layers == {"telemetry.endpoint": "OTEL_SDK_DISABLED"}
    assert loaded.ignored == (
        Ignored("telemetry.endpoint", "OTEL_EXPORTER_OTLP_ENDPOINT", f"replaced by {FILE}"),
        Ignored("telemetry.endpoint", FILE, "replaced by OTEL_SDK_DISABLED"),
    )


@pytest.mark.parametrize("enabled", ["false", "1", "yes", ""])
def test_opentelemetry_disabled_by_any_other_value_leaves_telemetry_on(
    tmp_path: Path, monkeypatch: MonkeyPatch, enabled: str
) -> None:
    """OpenTelemetry's specification takes any value but true as false, so does the SDK."""
    monkeypatch.setenv("OTEL_SDK_DISABLED", enabled)
    loaded = loaded_from(tmp_path, '[telemetry]\nendpoint = "http://127.0.0.1:4318"\n')
    assert loaded.settings.telemetry.endpoint == "http://127.0.0.1:4318"
    assert loaded.ignored == ()


def test_each_layer_wins_over_the_weaker_and_the_weaker_is_ignored(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The file, then the variable, then the flag: each wins and names its layer.

    The value replaced is recorded as ignored, with what replaced it.
    """
    text = 'site = "https://file.example.invalid"\n'
    from_the_file = loaded_from(tmp_path, text)
    assert from_the_file.settings.site == "https://file.example.invalid"
    assert from_the_file.layers["site"] == FILE
    assert from_the_file.ignored == ()

    monkeypatch.setenv("KB_MCP_SITE", "https://variable.example.invalid")
    from_the_variable = loaded_from(tmp_path, text)
    assert from_the_variable.settings.site == "https://variable.example.invalid"
    assert from_the_variable.layers["site"] == "KB_MCP_SITE"
    assert from_the_variable.ignored == (Ignored("site", FILE, "replaced by KB_MCP_SITE"),)

    from_the_flag = loaded_from(
        tmp_path, text, {"--site": ("site", "https://flag.example.invalid")}
    )
    assert from_the_flag.settings.site == "https://flag.example.invalid"
    assert from_the_flag.layers["site"] == "--site"
    assert set(from_the_flag.ignored) == {
        Ignored("site", FILE, "replaced by KB_MCP_SITE"),
        Ignored("site", "KB_MCP_SITE", "replaced by --site"),
    }


def test_a_list_from_the_environment_replaces_the_file_s_whole(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The variable's projects are all the projects, in JSON."""
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__PROJECTS", '["PRB"]')
    loaded = loaded_from(tmp_path, '[sources.jira]\nprojects = ["PLAT", "PAY"]\n')
    assert loaded.settings.sources.jira.projects == ("PRB",)
    assert loaded.layers["sources.jira.projects"] == "KB_MCP_SOURCES__JIRA__PROJECTS"


def test_each_setting_s_variable_gives_its_value_and_names_its_layer(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Every setting that is no table has a variable: the prefix, then its path."""
    given = {
        "KB_MCP_SITE": "https://variable.example.invalid",
        "KB_MCP_EMAIL": "someone@example.invalid",
        "KB_MCP_API_TOKEN": SENTINEL,
        "KB_MCP_DATA_DIR": "~/from-variable",
        "KB_MCP_MODEL": "bge-m3",
        "KB_MCP_SEARCH_MODE": "hybrid",
        "KB_MCP_EMBEDDING_URL": "http://127.0.0.1:8080/v1",
        "KB_MCP_EMBEDDING_API_KEY": f"{SENTINEL}-key",
        "KB_MCP_SOURCES__CONFLUENCE__SPACES": '["ENG"]',
        "KB_MCP_SOURCES__JIRA__PROJECTS": '["PRB", "PAY"]',
        "KB_MCP_LOGS__DIR": "~/logs",
        "KB_MCP_TELEMETRY__ENDPOINT": "http://127.0.0.1:4318",
    }
    for name, value in given.items():
        monkeypatch.setenv(name, value)
    loaded = loaded_from(tmp_path, "")
    settings = loaded.settings
    assert (settings.site, settings.email, settings.model, settings.search_mode) == (
        "https://variable.example.invalid",
        "someone@example.invalid",
        "bge-m3",
        "hybrid",
    )
    assert settings.data_dir == (tmp_path / "home" / "from-variable").resolve()
    assert settings.embedding_url == "http://127.0.0.1:8080/v1"
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == SENTINEL
    assert settings.embedding_api_key is not None
    assert settings.embedding_api_key.get_secret_value() == f"{SENTINEL}-key"
    assert settings.sources.confluence.spaces == ("ENG",)
    assert settings.sources.jira.projects == ("PRB", "PAY")
    assert settings.logs.dir == (tmp_path / "home" / "logs").resolve()
    assert settings.telemetry.endpoint == "http://127.0.0.1:4318"
    assert loaded.layers == {
        name.removeprefix("KB_MCP_").lower().replace("__", "."): name for name in given
    }
    assert loaded.ignored == ()


def test_a_table_from_the_environment_is_a_json_object(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """At the top or below it; each value it gives names its variable."""
    monkeypatch.setenv("KB_MCP_SOURCES", '{"confluence": {"spaces": ["ENG"]}}')
    loaded = loaded_from(tmp_path, "")
    assert loaded.settings.sources.confluence.spaces == ("ENG",)
    assert loaded.layers["sources.confluence.spaces"] == "KB_MCP_SOURCES"
    monkeypatch.delenv("KB_MCP_SOURCES")
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA", '{"projects": ["PRB"]}')
    loaded = loaded_from(tmp_path, "")
    assert loaded.settings.sources.jira.projects == ("PRB",)
    assert loaded.layers["sources.jira.projects"] == "KB_MCP_SOURCES__JIRA"


def test_an_empty_table_from_the_environment_replaces_the_file_s_values_under_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``{}`` leaves the table's settings at their defaults, the file's recorded as replaced."""
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA", "{}")
    loaded = loaded_from(tmp_path, '[sources.jira]\nprojects = ["PLAT"]\n')
    assert loaded.settings.sources.jira.projects == ()
    assert loaded.ignored == (
        Ignored("sources.jira.projects", FILE, "replaced by KB_MCP_SOURCES__JIRA"),
    )


@pytest.mark.parametrize(
    ("outer", "inner"),
    [
        (
            ("KB_MCP_SOURCES", f'{{"jira": {{"projects": ["{SENTINEL}"]}}}}'),
            ("KB_MCP_SOURCES__JIRA__PROJECTS", '["PRB"]'),
        ),
        (
            ("KB_MCP_SOURCES", "{}"),
            ("KB_MCP_SOURCES__JIRA", f'{{"projects": ["{SENTINEL}"]}}'),
        ),
        (
            ("KB_MCP_SOURCES__JIRA", '{"projects": ["PLAT"]}'),
            ("KB_MCP_SOURCES__JIRA__PROJECTS", f'["{SENTINEL}"]'),
        ),
        (
            ("KB_MCP_SITE", f"https://{SENTINEL}.example.invalid"),
            ("kb_mcp_site", "https://other.example.invalid"),
        ),
    ],
)
@pytest.mark.parametrize("inner_first", [True, False])
def test_two_variables_of_one_setting_or_of_a_table_and_inside_it_are_refused(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    outer: tuple[str, str],
    inner: tuple[str, str],
    *,
    inner_first: bool,
) -> None:
    """pydantic-settings merges them, by the environment's order below the top.

    No value of the merge could name the variable that gave it: both are named, in
    either order, never what they hold.
    """
    for name, value in [inner, outer] if inner_first else [outer, inner]:
        monkeypatch.setenv(name, value)
    with pytest.raises(SettingsError) as refused:
        loaded_from(tmp_path, "")
    named, _, _ = str(refused.value).partition(": ")
    assert set(named.split(", ")) == {outer[0], inner[0]}
    assert SENTINEL not in str(refused.value)


@pytest.mark.parametrize(
    ("given", "unknown"),
    [
        (
            ("KB_MCP_SOURCES", '{"jira": {"projects": ["PRB"]}}'),
            "KB_MCP_SOURCES__JIRA__PROJETS",
        ),
        (
            ("KB_MCP_SOURCES__JIRA", '{"projects": ["PRB"]}'),
            "KB_MCP_SOURCES__JIRA__PROJETS",
        ),
        (
            ("KB_MCP_SOURCES", '{"jira": {"projects": ["PRB"]}}'),
            "KB_MCP_SOURCES__JIRA__PROJECTS__0",
        ),
        (
            ("KB_MCP_SOURCES__JIRA__PROJECTS", '["PRB"]'),
            "KB_MCP_SOURCES__JIRA__PROJECTS__0",
        ),
    ],
)
@pytest.mark.parametrize("unknown_first", [True, False])
def test_a_variable_naming_no_setting_inside_another_s_setting_is_ignored_alone(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    given: tuple[str, str],
    unknown: str,
    *,
    unknown_first: bool,
) -> None:
    """The other gives its value whole, in either order; this one is ignored, as alone.

    pydantic-settings would merge it into the other's table or list.
    """
    named = (unknown, f'["{SENTINEL}"]')
    for name, value in [named, given] if unknown_first else [given, named]:
        monkeypatch.setenv(name, value)
    loaded = loaded_from(tmp_path, "")
    assert loaded.settings.sources.jira.projects == ("PRB",)
    assert loaded.layers == {"sources.jira.projects": given[0]}
    assert loaded.ignored == (Ignored(None, unknown, "names no setting"),)


def test_a_variable_naming_no_setting_below_a_value_is_ignored_alone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A value has nothing below it: the site is the variable's, the other is ignored."""
    monkeypatch.setenv("KB_MCP_SITE", "https://variable.example.invalid")
    monkeypatch.setenv("KB_MCP_SITE__X", "1")
    loaded = loaded_from(tmp_path, "")
    assert loaded.settings.site == "https://variable.example.invalid"
    assert loaded.ignored == (Ignored(None, "KB_MCP_SITE__X", "names no setting"),)


def test_a_variable_is_read_without_regard_to_case_and_named_as_written(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """As pydantic-settings reads it: the layer is the variable's own name."""
    monkeypatch.setenv("kb_mcp_site", "https://lower.example.invalid")
    monkeypatch.setenv("Kb_Mcp_Spaces", '["X"]')
    loaded = loaded_from(tmp_path, "")
    assert loaded.settings.site == "https://lower.example.invalid"
    assert loaded.layers == {"site": "kb_mcp_site"}
    assert loaded.ignored == (Ignored(None, "Kb_Mcp_Spaces", "names no setting"),)


def test_the_generic_atlassian_names_are_not_read(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """One prefix alone: a token exported for another tool never switches the sign-in."""
    monkeypatch.setenv("ATLASSIAN_SITE", "https://other.example.invalid")
    monkeypatch.setenv("ATLASSIAN_EMAIL", "someone@example.invalid")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", SENTINEL)
    loaded = loaded_from(tmp_path, "")
    settings = loaded.settings
    assert (settings.site, settings.email, settings.api_token) == (None, None, None)
    assert loaded.ignored == ()


def test_secrets_come_from_the_environment_and_are_never_shown(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The token and the embedding key are read, and their text is in no representation.

    Neither the settings, nor what the loader gives, nor the environment's entries,
    which hold them before they are masked, show them.
    """
    monkeypatch.setenv("KB_MCP_API_TOKEN", SENTINEL)
    monkeypatch.setenv("KB_MCP_EMBEDDING_API_KEY", f"{SENTINEL}-key")
    loaded = loaded_from(tmp_path, "")
    settings = loaded.settings
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == SENTINEL
    assert settings.embedding_api_key is not None
    assert settings.embedding_api_key.get_secret_value() == f"{SENTINEL}-key"
    assert SENTINEL not in f"{settings!r} {settings} {loaded!r}"
    entries, _ = environment_entries(os.environ, EnvSettingsSource(Settings))
    assert SENTINEL not in f"{entries!r} {entries}"


@pytest.mark.parametrize(
    ("key", "variable"),
    [
        ("api_token", "KB_MCP_API_TOKEN"),
        ("embedding_api_key", "KB_MCP_EMBEDDING_API_KEY"),
    ],
)
def test_a_secret_in_the_file_is_refused_by_name_never_by_value(
    tmp_path: Path, key: str, variable: str
) -> None:
    """A secret would sit in a file other tools read: it is refused, naming its variable."""
    with pytest.raises(SettingsError) as refused:
        loaded_from(tmp_path, f'{key} = "{SENTINEL}"\n')
    assert str(refused.value) == f"{key} ({FILE}): a secret, read from {variable} alone"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("KB_MCP_SOURCES__JIRA__PROJECTS", "PLAT,PRB"),
        ("KB_MCP_SOURCES__JIRA__PROJECTS", '{"PLAT": "PRB"}'),
        ("KB_MCP_SOURCES__JIRA", '["PLAT", "PRB"]'),
        ("KB_MCP_SOURCES", "null"),
    ],
)
def test_a_list_or_a_table_not_in_json_is_refused_by_its_variable_never_its_value(
    tmp_path: Path, monkeypatch: MonkeyPatch, name: str, value: str
) -> None:
    """PLAT,PRB is not JSON, nor an object a list, nor null a table: the variable is named.

    pydantic-settings would refuse PLAT,PRB naming no variable, and drop a table's null
    unread.
    """
    monkeypatch.setenv(name, value)
    with pytest.raises(SettingsError) as refused:
        loaded_from(tmp_path, "")
    assert str(refused.value).startswith(f"{name}: ")
    assert "PLAT" not in str(refused.value)
    assert value not in str(refused.value)


@pytest.mark.parametrize(
    ("variable", "value", "named"),
    [
        (
            "KB_MCP_SOURCES",
            f'{{"worklog": "{SENTINEL}"}}',
            "sources.worklog (KB_MCP_SOURCES):",
        ),
        (
            "KB_MCP_SEARCH_MODE",
            SENTINEL,
            "search_mode (KB_MCP_SEARCH_MODE):",
        ),
    ],
)
def test_a_bad_value_from_the_environment_is_refused_naming_its_variable(
    tmp_path: Path, monkeypatch: MonkeyPatch, variable: str, value: str, named: str
) -> None:
    """The layer of a refused value is the variable that gave it, never what it held."""
    monkeypatch.setenv(variable, value)
    with pytest.raises(SettingsError) as refused:
        loaded_from(tmp_path, "")
    message = str(refused.value)
    assert named in message
    assert SENTINEL not in message


def test_variables_naming_no_setting_or_empty_are_ignored(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Other tools and versions share the environment: such a variable is ignored, and said."""
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__PROJETS", '["X"]')
    monkeypatch.setenv("KB_MCP_SPACES", '["X"]')
    monkeypatch.setenv("KB_MCP_SITE", "")
    loaded = loaded_from(tmp_path, 'site = "https://file.example.invalid"\n')
    assert loaded.settings.site == "https://file.example.invalid"
    assert loaded.settings.sources.jira.projects == ()
    assert set(loaded.ignored) == {
        Ignored(None, "KB_MCP_SOURCES__JIRA__PROJETS", "names no setting"),
        Ignored(None, "KB_MCP_SPACES", "names no setting"),
        Ignored("site", "KB_MCP_SITE", "empty"),
    }


@pytest.mark.parametrize(
    "path",
    [
        HOME / "Library/CloudStorage/OneDrive-Company/mirror",
        HOME / "Library/Mobile Documents/com~apple~CloudDocs/mirror",
        HOME / "Documents/mirror",
        HOME / "Desktop/mirror",
        Path("/home/someone/Dropbox (Maestral)/mirror"),
        Path("/Volumes/data/OneDrive/mirror"),
        Path("/data/Google Drive/mirror"),
        HOME / "documents/mirror",
        HOME / "library/cloudstorage/mirror",
        Path("/home/someone/dropbox/mirror"),
        Path("/home/someone/GoogleDrive/mirror"),
    ],
)
def test_synchronised_folders_are_refused(path: Path) -> None:
    """A folder that may be copied to a cloud is no place for company data, in any case.

    The default file system of macOS ignores case, so ~/documents is ~/Documents.
    """
    assert unsafe_location(path, HOME, git_root=None) is not None


def test_a_git_working_tree_is_refused() -> None:
    """Data inside a working tree could be committed."""
    reason = unsafe_location(HOME / "src/project/data", HOME, git_root=HOME / "src/project")
    assert reason == f"inside the git working tree {HOME / 'src/project'}"


def test_a_plain_folder_under_the_home_is_accepted() -> None:
    """The default place passes."""
    assert unsafe_location(HOME / "kb-mcp", HOME, git_root=None) is None


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:11434/v1", "http://127.1.2.3/v1", "https://[::1]:8443/v1"]
)
def test_a_literal_address_of_this_machine_is_loopback(url: str) -> None:
    """127.0.0.0/8 and ::1, written as addresses."""
    assert loopback(url)


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "LOCALHOST",
        "localhost.",
        str(IPv4Address(0)),  # 0.0.0.0, which some systems route to this machine
        "10.0.0.1",
        "2130706433",
        "0x7f.1",
        "127.0.0.1.example.com",
        "example.com",
    ],
)
def test_any_other_host_is_not_loopback(host: str) -> None:
    """A name may resolve anywhere; any other address is another machine."""
    assert not loopback(f"http://{host}:11434/v1")


def test_an_address_with_a_user_part_is_neither_a_setting_nor_loopback() -> None:
    """``127.0.0.1@example.com`` is example.com, with a user named 127.0.0.1."""
    url = "http://127.0.0.1@example.com/v1"
    assert not loopback(url)
    with pytest.raises(SettingsError, match="embedding_url"):
        from_file({"embedding_url": url})


ARCHIVES = "KB_MCP_SOURCES__WORKLOG__ARCHIVES"


def check_work_log(
    tmp_path: Path, monkeypatch: MonkeyPatch, table: str, environment: dict[str, str]
) -> int:
    """Run check with a settings file holding plan 015's shape and this work-log table."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    config = tmp_path / "config.toml"
    config.write_text(
        'site = "https://x.atlassian.net"\n'
        '[sources.confluence]\nspaces = ["MFS"]\n'
        '[sources.jira]\nprojects = ["PRB"]\n'
        f"[sources.worklog]\n{table}\n",
        "utf-8",
    )
    return main(["check", "--config", str(config)])


def test_the_work_log_s_table_passes_check_which_lists_both_keys(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The folder under ~ is the home's; archives as written."""
    assert check_work_log(tmp_path, monkeypatch, 'path = "~/todo"\narchives = false', {}) == 0
    out = capsys.readouterr().out
    assert f"sources.worklog.path: {tmp_path / 'home' / 'todo'}\n" in out
    assert "sources.worklog.archives: False\n" in out


@pytest.mark.parametrize(
    "case",
    [
        ('path = "todo"', {}, "sources.worklog.path (config.toml): an absolute path"),
        ('folder = "~/todo"', {}, "sources.worklog.folder (config.toml): not a setting"),
        ('path = "~/todo"', {ARCHIVES: "maybe"}, f"sources.worklog.archives ({ARCHIVES}):"),
    ],
)
def test_a_work_log_table_off_its_rules_exits_2_by_name(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, dict[str, str], str],
) -> None:
    """A relative folder, an unknown key, an archives that is no boolean: never the value."""
    table, environment, named = case
    assert check_work_log(tmp_path, monkeypatch, table, environment) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert named in err
    assert "maybe" not in err


def test_archives_false_in_the_environment_turns_archives_off(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The variable is stronger than the file, as for every setting."""
    assert check_work_log(tmp_path, monkeypatch, 'path = "~/todo"', {ARCHIVES: "false"}) == 0
    assert "sources.worklog.archives: False\n" in capsys.readouterr().out


def test_a_refusal_names_its_own_service_s_setting_and_flag() -> None:
    """Each service is refused in its own words: its setting, then the flag that allows it."""
    other = Service(
        name="the other server", setting="other.url", flag="--allow-remote-other", start="x"
    )
    url = "http://10.0.0.1:9931/v1"
    elsewhere = refused_endpoint(url, other, remote_allowed=False) or ""
    assert elsewhere.startswith("other.url: not an address of this machine")
    assert elsewhere.endswith("or pass --allow-remote-other")
    https_only = "other.url: an endpoint off this machine is reached over https only"
    assert refused_endpoint(url, other, remote_allowed=True) == https_only
    assert refused_endpoint("http://127.0.0.1:9931/v1", other, remote_allowed=False) is None
