"""Tests of the settings, their layers, and the guard on where data may live."""

from __future__ import annotations

import re
from ipaddress import IPv4Address
from pathlib import Path

import pytest

from atlassian_offline_mcp.config.app.settings import load_settings
from atlassian_offline_mcp.config.domain.settings import (
    ConfluenceSource,
    Entry,
    Ignored,
    JiraSource,
    Settings,
    SettingsError,
    Sources,
    file_entries,
    loopback,
    settings_of,
    unsafe_location,
)

HOME = Path("/home/someone")
FILE = "config.toml"


def from_file(values: dict[str, object]) -> Settings:
    """Build the settings from a settings file's values alone."""
    return settings_of(file_entries(values, FILE)).settings


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
    assert settings.data_dir == Path("~/mirror")
    assert settings.sources.confluence.spaces == ("ENG", "~5f1a2b")
    assert settings.sources.jira.projects == ("PAY",)
    assert (settings.model, settings.search_mode, settings.embedding_url) == (
        "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0",
        "hybrid",
        "http://127.0.0.1:8080/v1",
    )
    mirror = Path("/data/mirror")
    parts = Settings(data_dir=mirror).parts
    assert {mirror / "vectors.sqlite", mirror / "eval"} <= set(parts)
    assert mirror / "models" not in parts


def test_the_default_embeddings_come_from_ollama_on_this_machine() -> None:
    """Ollama's own address, and the model that plan 018 chose; search by words."""
    settings = from_file({})
    assert (settings.embedding_url, settings.model, settings.search_mode) == (
        "http://127.0.0.1:11434/v1",
        "qwen3-embedding:0.6b",
        "lexical",
    )


def test_the_default_data_directory_is_under_the_home() -> None:
    """With nothing set, the data lives in ~/atlassian-offline-mcp and no site is known."""
    settings = from_file({})
    assert (settings.site, settings.data_dir) == (None, Path("~/atlassian-offline-mcp"))
    assert (settings.sources.confluence.spaces, settings.sources.jira.projects) == ((), ())


def test_every_setting_is_described() -> None:
    """Plan 020 writes the settings' reference from these descriptions."""
    for model in (Settings, Sources, ConfluenceSource, JiraSource):
        assert all(info.description for info in model.model_fields.values()), model


@pytest.mark.parametrize(
    ("values", "named"),
    [
        ({"sight": "https://x.atlassian.net"}, "sight (config.toml): not a setting"),
        ({"sources": {"jira": {"projets": ["PLAT"]}}}, "sources.jira.projets (config.toml):"),
        ({"sources": {"worklog": {"spaces": []}}}, "sources.worklog.spaces (config.toml):"),
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
    ],
)
def test_unusable_settings_are_refused_by_name_and_layer(
    values: dict[str, object], named: str
) -> None:
    """Each refusal names the setting at fault and the layer that gave it."""
    with pytest.raises(SettingsError, match=re.escape(named)):
        from_file(values)


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


def test_a_refusal_never_holds_the_value() -> None:
    """The setting and its layer are named; what the layer held is not."""
    with pytest.raises(SettingsError) as refused:
        from_file({"site": "https://secret-host.example.invalid/wiki"})
    assert "secret-host" not in str(refused.value)


def test_a_stronger_layer_replaces_a_weaker_one_and_the_weaker_is_ignored() -> None:
    """A flag wins over the file; the file's value is recorded as replaced."""
    loaded = settings_of(
        [
            Entry(("site",), "https://file.example.invalid", FILE),
            Entry(("site",), "https://flag.example.invalid", "--site"),
        ]
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
        ]
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
        ]
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
    assert unsafe_location(HOME / "atlassian-offline-mcp", HOME, git_root=None) is None


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
