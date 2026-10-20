"""Tests of the command: its subcommands, and ``check`` end to end in a scratch home."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

# The exit status for settings that cannot be used, apart from a refused directory (1).
BAD_SETTINGS = 2


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, so that none reads or writes the user's."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    return scratch


def test_help_lists_the_subcommands(capsys: CaptureFixture[str]) -> None:
    """The subcommands found in the commands package are offered."""
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    assert "check" in capsys.readouterr().out


def test_check_accepts_a_plain_data_directory(home: Path, capsys: CaptureFixture[str]) -> None:
    """Valid settings and a safe directory exit 0 and are shown."""
    config = home / "config.toml"
    config.write_text('site = "https://example.atlassian.net"\nspaces = ["ENG"]\n', "utf-8")
    assert main(["check", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "site: https://example.atlassian.net" in out
    assert f"data directory: {(home / 'atlassian-offline-mcp').resolve()}" in out


@pytest.mark.parametrize(
    ("data_dir", "reason"),
    [
        ("~/Library/CloudStorage/Box/mirror", "under ~/Library/CloudStorage"),
        ("~/Dropbox/mirror", "under a Dropbox folder"),
        ("~/project/data", "inside the git working tree"),
        ("~/elsewhere/../Documents/mirror", "under ~/Documents"),
        ("~/linked/data", "inside the git working tree"),
    ],
)
def test_check_refuses_a_data_directory_that_could_leave_the_machine(
    home: Path, data_dir: str, reason: str, capsys: CaptureFixture[str]
) -> None:
    """A synchronised folder or a git working tree exits 1, naming the reason.

    The path is judged once resolved, so neither ``..`` nor a link hides where it leads.
    """
    (home / "project" / ".git").mkdir(parents=True)
    (home / "linked").symlink_to(home / "project")
    assert main(["check", "--config", str(home / "none.toml"), "--data-dir", data_dir]) == 1
    error = capsys.readouterr().err
    assert error.startswith("data directory refused: data_dir: ")
    assert reason in error


def test_check_refuses_bad_settings_by_name(home: Path, capsys: CaptureFixture[str]) -> None:
    """A settings file with an unknown key exits 2, naming it."""
    config = home / "config.toml"
    config.write_text('sight = "https://example.atlassian.net"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    assert "unknown setting: sight" in capsys.readouterr().err


def test_check_refuses_a_file_that_is_not_toml(home: Path, capsys: CaptureFixture[str]) -> None:
    """A broken settings file is refused rather than ignored."""
    config = home / "config.toml"
    config.write_text("site = ", "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    assert "not a TOML file" in capsys.readouterr().err
