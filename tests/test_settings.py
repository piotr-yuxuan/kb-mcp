"""Tests of the settings and of the guard on where data may live."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlassian_offline_mcp.domain.settings import (
    Settings,
    SettingsError,
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
            "model": "bge-small-en-v1.5",
        },
        HOME,
    )
    assert settings == Settings(
        "https://example.atlassian.net",
        HOME / "mirror",
        ("ENG", "~5f1a2b"),
        ("PAY",),
        "bge-small-en-v1.5",
    )
    assert settings.models == HOME / "mirror" / "models"
    assert settings.models in settings.parts


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
