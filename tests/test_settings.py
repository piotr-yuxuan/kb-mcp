"""Tests of the settings and of the guard on where data may live."""

from __future__ import annotations

from ipaddress import IPv4Address
from pathlib import Path

import pytest

from atlassian_offline_mcp.domain.settings import (
    Settings,
    SettingsError,
    loopback,
    parse_settings,
    unsafe_location,
)

HOME = Path("/home/someone")


def test_settings_are_normalised() -> None:
    """The site loses its trailing slash and the data directory's ~ means the home."""
    settings = parse_settings(
        {
            "site": "https://Example.atlassian.net/",
            "data_dir": "~/mirror",
            "spaces": ["ENG", "~5f1a2b"],
            "projects": ["PAY"],
            "model": "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0",
            "search_mode": "hybrid",
            "embedding_url": "http://127.0.0.1:8080/v1/",
        },
        HOME,
    )
    assert settings == Settings(
        "https://example.atlassian.net",
        HOME / "mirror",
        ("ENG", "~5f1a2b"),
        ("PAY",),
        "hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0",
        "hybrid",
        "http://127.0.0.1:8080/v1",
    )
    mirror = HOME / "mirror"
    assert {mirror / "models", mirror / "vectors.sqlite", mirror / "eval"} <= set(settings.parts)


def test_the_default_embeddings_come_from_ollama_on_this_machine() -> None:
    """Ollama's own address."""
    assert parse_settings({}, HOME).embedding_url == "http://127.0.0.1:11434/v1"


def test_the_default_data_directory_is_under_the_home() -> None:
    """With nothing set, the data lives in ~/atlassian-offline-mcp and no site is known."""
    assert parse_settings({}, HOME) == Settings(None, HOME / "atlassian-offline-mcp")


@pytest.mark.parametrize(
    ("values", "named"),
    [
        ({"sight": "https://x.atlassian.net"}, "unknown setting: sight"),
        ({"site": "http://x.atlassian.net"}, "site:"),
        ({"site": "https://user@x.atlassian.net"}, "site:"),
        ({"site": "https://x.atlassian.net/wiki"}, "site:"),
        ({"site": "https://["}, "site:"),
        ({"data_dir": 3}, "data_dir:"),
        ({"data_dir": "relative/path"}, "data_dir:"),
        ({"data_dir": "~/mirror\0"}, "data_dir:"),
        ({"spaces": "ENG"}, "spaces:"),
        ({"spaces": ["ENG", "not a key"]}, "spaces:"),
        ({"projects": ["pay"]}, "projects:"),
        ({"model": "../elsewhere"}, "model:"),
        ({"model": ["bge-small-en-v1.5"]}, "model:"),
        ({"model": "qwen3 embedding"}, "model:"),
        ({"model": "a" * 129}, "model: the name of an embedding model, such as qwen3-embedding"),
        ({"embedding_url": "http://user@127.0.0.1:11434/v1"}, "embedding_url:"),
        ({"embedding_url": "http://127.0.0.1:11434/v1?key=1"}, "embedding_url:"),
        ({"embedding_url": "http://127.0.0.1:11434/v1#here"}, "embedding_url:"),
        ({"embedding_url": "http://127.0.0.1:port/v1"}, "embedding_url:"),
        ({"embedding_url": "http://127.0.0.1:0/v1"}, "embedding_url:"),
        ({"embedding_url": "http://[::1/v1"}, "embedding_url:"),
        ({"embedding_url": "ftp://127.0.0.1/v1"}, "embedding_url:"),
        ({"embedding_url": "http:///v1"}, "embedding_url:"),
        ({"embedding_url": 11434}, "embedding_url: an http or https address with a host"),
        ({"search_mode": "fuzzy"}, "search_mode: one of lexical, semantic, hybrid"),
    ],
)
def test_unusable_settings_are_refused_by_name(values: dict[str, object], named: str) -> None:
    """Each refusal names the setting at fault."""
    with pytest.raises(SettingsError, match=named):
        parse_settings(values, HOME)


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
    with pytest.raises(SettingsError, match="embedding_url:"):
        parse_settings({"embedding_url": url}, HOME)
