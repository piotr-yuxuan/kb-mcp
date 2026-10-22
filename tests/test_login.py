"""Signing in keeps the site's cookies alone, in a file the user alone can read."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.session_file import COOKIES, read_cookies
from atlassian_offline_mcp.app import login as login_module
from atlassian_offline_mcp.config.domain.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

SITE = "https://sandbox.example.invalid"


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
    settings = Settings(SITE, tmp_path / "data")
    login_module.login(settings, SITE, None, extensions=False)
    saved = read_cookies(settings.session / COOKIES)
    assert [(cookie["name"], cookie["path"]) for cookie in saved] == [
        ("tenant", "/"),
        ("wiki", "/wiki"),
    ]
