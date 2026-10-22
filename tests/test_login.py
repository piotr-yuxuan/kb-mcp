"""Signing in keeps the site's cookies alone, in a file the user alone can read."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.commands import login as login_command
from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.config.domain.settings import Settings
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import COOKIES, read_cookies
from atlassian_offline_mcp.sources.atlassian.app import login as login_module

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

SITE = "https://sandbox.example.invalid"
INSTRUCTION = f"Sign in to {SITE} in the Chrome window that opens.\n"
SIGNED_IN = "Signed in; the session is saved.\n"


def test_only_the_site_cookies_of_the_browser_are_saved(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The identity provider's and Atlassian's own cookies stay in the browser profile."""
    browser = [
        {"name": "tenant", "value": "1", "domain": "sandbox.example.invalid", "path": "/"},
        {"name": "wiki", "value": "2", "domain": "sandbox.example.invalid", "path": "/wiki"},
        {"name": "cloud", "value": "3", "domain": ".atlassian.com", "path": "/"},
        {"name": "idp", "value": "4", "domain": ".login.example.invalid", "path": "/"},
    ]
    monkeypatch.setattr(login_module, "sign_in", lambda *_, **__: browser)
    monkeypatch.setattr(login_module, "disable_password_saving", lambda _: None)
    settings = Settings(site=SITE, data_dir=tmp_path / "data")
    login_module.login(settings, SITE, None, extensions=False)
    saved = read_cookies(settings.session / COOKIES)
    assert [(cookie["name"], cookie["path"]) for cookie in saved] == [
        ("tenant", "/"),
        ("wiki", "/wiki"),
    ]


@pytest.mark.parametrize("summary", ["short", "detailed"])
def test_the_command_says_what_to_do_on_stderr_and_its_result_on_stdout(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], summary: str
) -> None:
    """The instruction is a message, after the summary; the result, the same in each detail.

    As JSON, the result is one document.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(login_command, "login", lambda *_, **__: None)
    options = ["login", "--config", str(tmp_path / "none.toml"), "--site", SITE]
    assert main([*options, "--summary", summary]) == 0
    out, err = capsys.readouterr()
    assert out == SIGNED_IN
    assert err.endswith(INSTRUCTION)
    assert main([*options, "--format", "json"]) == 0
    out, err = capsys.readouterr()
    assert err.endswith(INSTRUCTION)
    session = (tmp_path / "atlassian-offline-mcp" / "session").resolve()
    assert json.loads(out) == {"site": SITE, "session": str(session)}
