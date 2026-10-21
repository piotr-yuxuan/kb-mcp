"""The download command as the user meets it: its refusals, messages and exit statuses."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters import http
from atlassian_offline_mcp.adapters.session_file import COOKIES, write_cookies
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.settings import Settings
from tests.test_download import SITE, FakeSite

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

REFUSED = 2
SOME_FAILED = 1
SIGN_IN_NEEDED = 3


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, and no waiting between requests."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return scratch


def command(home: Path, *options: str) -> list[str]:
    """Return the arguments of a download with no settings file."""
    return ["download", "--config", str(home / "none.toml"), *options]


def test_a_download_without_a_site_is_refused_by_name(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The site is named as the missing setting."""
    assert main(command(home, "--space", "MFS", "--since", "7d")) == REFUSED
    assert "refused: site: not set" in capsys.readouterr().err


def test_a_download_of_nothing_is_refused(home: Path, capsys: CaptureFixture[str]) -> None:
    """Without a space or a project, there is nothing to do."""
    assert main(command(home, "--site", SITE, "--since", "7d")) == REFUSED
    assert "nothing to download" in capsys.readouterr().err


@pytest.mark.parametrize(("option", "value"), [("--space", "not a key"), ("--project", "prb")])
def test_a_key_that_is_not_one_is_refused_by_the_options(
    home: Path, option: str, value: str, capsys: CaptureFixture[str]
) -> None:
    """A space or project key is checked before anything runs."""
    with pytest.raises(SystemExit) as stopped:
        main(command(home, "--site", SITE, option, value, "--since", "7d"))
    assert stopped.value.code == REFUSED
    assert "key" in capsys.readouterr().err


def test_a_period_that_ends_before_it_starts_is_refused(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The option at fault is named."""
    options = ("--site", SITE, "--space", "MFS", "--since", "2026-10-22", "--until", "2026-10-01")
    assert main(command(home, *options)) == REFUSED
    assert "--until" in capsys.readouterr().err


def test_without_a_session_the_user_is_told_to_sign_in(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """No saved session: exit 3, and the command to run."""
    assert main(command(home, "--site", SITE, "--space", "MFS", "--since", "7d")) == SIGN_IN_NEEDED
    assert "sign-in needed: run atlassian-offline-mcp login" in capsys.readouterr().err


def test_a_space_that_finds_nothing_is_named_on_stderr_and_not_in_the_report(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The user's own key is shown to them, and never written to the run report."""
    chosen = Settings(SITE, (home / "atlassian-offline-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite(spaces=[])
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    options = ("--site", SITE, "--space", "NOPE", "--since", "7d")
    assert main(command(home, *options)) == SOME_FAILED
    captured = capsys.readouterr()
    assert "space NOPE: not found" in captured.err
    assert "confluence spaces failed: not found: 1" in captured.out
    [report] = chosen.runs.iterdir()
    assert "NOPE" not in report.read_text("utf-8")
    assert json.loads(report.read_text("utf-8"))["status"] == SOME_FAILED
