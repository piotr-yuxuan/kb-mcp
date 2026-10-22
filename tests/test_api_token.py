"""Signing in with an API token, over the scripted site, in a scratch home (plan 015).

By Atlassian's documentation of basic auth, the token goes with its account's email,
``Authorization: Basic base64(email:token)``; plan 015 sends it to the site's host
alone, keeps nothing of it, and leaves the session that ``login`` saved untouched.
"""

from __future__ import annotations

import base64
import functools
import json
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from atlassian_offline_mcp.cli.commands import login as login_command
from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.sources.atlassian.adapters import http
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import COOKIES, write_cookies
from tests.test_download import SITE, FakeSite

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

EMAIL = "ATLASSIAN_OFFLINE_MCP_EMAIL"
CREDENTIAL = "ATLASSIAN_OFFLINE_MCP_API_TOKEN"
ADDRESS = "someone@example.invalid"
SENTINEL = "token-sentinel-4d1c"
AUTHORISATION = f"Basic {base64.b64encode(f'{ADDRESS}:{SENTINEL}'.encode()).decode()}"
HOST = httpx.URL(SITE).host
SIGN_IN_NEEDED = 3


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a scratch home, no waiting between requests, and the token with its email."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setenv(EMAIL, ADDRESS)
    monkeypatch.setenv(CREDENTIAL, SENTINEL)
    return scratch


def served(
    monkeypatch: MonkeyPatch, answer: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """Let the clients that runs make reach ``answer``, their hooks kept; give what they send."""
    sent: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return answer(request)

    scripted = functools.partial(http.client, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(http, "client", scripted)
    return sent


def download(home: Path, *more: str) -> list[str]:
    """Give the arguments of a download of the scripted site's space and project."""
    return [
        "download",
        "--yes",
        "--config",
        str(home / "none.toml"),
        "--site",
        SITE,
        "--space",
        "MFS",
        "--project",
        "PRB",
        "--since",
        "2026-10-02",
        *more,
    ]


def test_the_token_goes_to_the_site_s_host_alone(home: Path, monkeypatch: MonkeyPatch) -> None:
    """Each request to the site carries it; none to the media host that a file redirects to.

    No session is read or written: its folder is never made.
    """
    sent = served(monkeypatch, FakeSite().handle)
    main(download(home))
    on_site = [request for request in sent if request.url.host == HOST]
    elsewhere = [request for request in sent if request.url.host != HOST]
    assert on_site
    assert {request.url.host for request in elsewhere} == {"api.media.atlassian.com"}
    assert all(request.headers.get("authorization") == AUTHORISATION for request in on_site)
    assert not any("authorization" in request.headers for request in elsewhere)
    assert not (home / "atlassian-offline-mcp" / "session").exists()


@pytest.mark.parametrize("dry_run", [[], ["--dry-run"]])
def test_a_run_with_the_token_leaves_a_saved_session_as_it_was(
    home: Path, monkeypatch: MonkeyPatch, dry_run: list[str]
) -> None:
    """Its cookies are neither sent nor written back, and its folder is unchanged."""
    session = home / "atlassian-offline-mcp" / "session"
    write_cookies(session / COOKIES, [{"name": "kept", "value": "v", "domain": HOST}])
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in session.rglob("*")}
    sent = served(monkeypatch, FakeSite(set_cookies=["renewed=w; Path=/"]).handle)
    main(download(home, *dry_run))
    assert sent
    assert not any("kept=" in request.headers.get("cookie", "") for request in sent)
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in session.rglob("*")}
    assert after == before


@pytest.mark.parametrize("dry_run", [[], ["--dry-run"]])
def test_a_download_refused_by_the_site_exits_3_naming_the_variables(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], dry_run: list[str]
) -> None:
    """A 401: the email and the token to check, by their variables."""
    served(monkeypatch, lambda _: httpx.Response(401))
    assert main(download(home, *dry_run)) == SIGN_IN_NEEDED
    assert f"sign-in needed: check {EMAIL} and {CREDENTIAL}\n" in capsys.readouterr().err


def test_the_doctor_signs_in_with_the_token(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """It names the token as the sign-in, which Confluence and Jira take."""
    sent = served(monkeypatch, FakeSite().handle)
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    options = ["--config", str(home / "none.toml"), "--site", SITE, "--format", "json"]
    assert main(["doctor", *options]) != SIGN_IN_NEEDED
    verdicts = {verdict["name"]: verdict for verdict in json.loads(capsys.readouterr().out)}
    assert verdicts["sign-in"]["found"] == "an API token"
    assert [verdicts[name]["found"] for name in ("confluence", "jira")] == ["signed in"] * 2
    assert sent
    assert all(request.headers.get("authorization") == AUTHORISATION for request in sent)


def test_the_doctor_refused_by_the_site_exits_3_naming_the_variables(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A 401 from each product: both verdicts name the email and the token to check."""
    served(monkeypatch, lambda _: httpx.Response(401))
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    assert main(["doctor", "--config", str(home / "none.toml"), "--site", SITE]) == SIGN_IN_NEEDED
    out = capsys.readouterr().out
    for name in ("confluence", "jira"):
        assert f"{name}: refused: check {EMAIL} and {CREDENTIAL}\n" in out


@pytest.mark.parametrize("email", [ADDRESS, None])
def test_login_with_a_token_signs_in_in_the_browser(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], email: str | None
) -> None:
    """The token is said to be ignored, with or without its email, and login runs."""
    if email is None:
        monkeypatch.delenv(EMAIL)
    signed_in: list[str] = []
    monkeypatch.setattr(login_command, "login", lambda _, site, *__, **___: signed_in.append(site))
    options = ["--yes", "--config", str(home / "none.toml"), "--site", SITE]
    assert main(["login", *options]) == 0
    assert signed_in == [SITE]
    ignored = f"ignored: api_token ({CREDENTIAL}): login signs in in a browser\n"
    assert ignored in capsys.readouterr().err
