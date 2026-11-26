"""Signing in keeps the site's cookies alone, in a file the user alone can read.

Plan 059: ``login <source>`` signs that source's site in; ``login`` alone, each site of
the sources configured that sign in by session, once a site.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

from kb_mcp.cli.main import main
from kb_mcp.config.settings import TABLE
from kb_mcp.sources.atlassian.fetch.adapters.browser import SignInFailedError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, folder_of, read_cookies
from kb_mcp.sources.atlassian.fetch.app import login as login_module
from kb_mcp.sources.atlassian.fetch.app.login import SignedIn
from kb_mcp.sources.declaration import Source
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.stages import Check
from kb_mcp.sources.worklog.declared import WORKLOG
from tests.composed import MODEL, sourced
from tests.test_cli import logged_as
from tests.test_observed import said

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.settings import Settings

SITE = "https://sandbox.example.invalid"
CLIENT = "https://client.example.invalid"
SIGNED_IN = f"Signed in to {SITE}; the session is saved.\n"
SIGN_IN_AGAIN = 3
BAD_ARGUMENTS = 2


pytestmark = pytest.mark.usefixtures("tmp_path_as_home")


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
    monkeypatch.setattr(login_module, "open_sign_in_window", lambda *_, **__: browser)
    monkeypatch.setattr(login_module, "disable_password_saving", lambda _: None)
    settings = MODEL(
        sources={"confluence": {"site": SITE}, "jira": {"site": SITE}}, data_dir=tmp_path / "data"
    )
    login_module.save_session(settings, SITE, None, extensions=False)
    saved = read_cookies(folder_of(settings.session, SITE) / COOKIES)
    assert [(cookie["name"], cookie["path"]) for cookie in saved] == [
        ("tenant", "/"),
        ("wiki", "/wiki"),
    ]


def opened(monkeypatch: MonkeyPatch) -> list[str]:
    """Stand a browser in for the sign-in: each site signed in to, in turn, signs in."""
    signed_in: list[str] = []
    monkeypatch.setattr(
        login_module, "save_session", lambda _, site, *__, **___: signed_in.append(site)
    )
    return signed_in


def login(tmp_path: Path, *more: str) -> list[str]:
    """Give the arguments of a login with no settings file, then ``more``."""
    return ["login", "--yes", "--config", str(tmp_path / "none.toml"), *more]


@pytest.mark.parametrize("detail", ["short", "detailed"])
def test_the_command_says_each_site_signed_in_on_stdout(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], detail: str
) -> None:
    """The result, the same in each detail; as JSON, one document, a row per site."""
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", SITE)
    opened(monkeypatch)
    assert main([*login(tmp_path, "jira"), "--detail", detail]) == 0
    assert capsys.readouterr().out == SIGNED_IN
    assert main([*login(tmp_path, "jira"), "--format", "json"]) == 0
    session = (tmp_path / "kb-mcp" / "session" / "sandbox.example.invalid").resolve()
    assert json.loads(capsys.readouterr().out) == [{"site": SITE, "session": str(session)}]


def test_a_sign_in_that_does_not_complete_exits_3_with_an_error(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The error login.not_signed_in, with the site and why; nothing on stdout.

    The run's log file holds the error too.
    """
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", SITE)
    reason = "the sign-in window was closed"

    def closed(*_: object, **__: object) -> None:
        raise SignInFailedError(reason)

    monkeypatch.setattr(login_module, "save_session", closed)
    assert main(login(tmp_path, "jira")) == SIGN_IN_AGAIN
    out, err = capsys.readouterr()
    assert out == ""
    assert ("error", "login.not_signed_in") in said(err)
    assert err.index("login.not_signed_in") < err.index(reason)
    (failed,) = logged_as(tmp_path, "login.not_signed_in")
    assert (failed["level"], failed["site"], failed["reason"]) == ("error", SITE, reason)


def test_login_alone_with_no_source_configured_is_refused(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 059: nothing to sign in, exit 2, before a window opens."""
    assert main(login(tmp_path)) == BAD_ARGUMENTS
    err = capsys.readouterr().err
    assert "nothing to sign in" in err
    assert "kb-mcp login <source>" in err


def test_login_alone_signs_in_a_source_with_its_site_alone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review round 1: no project yet, its site set: in use, and signed in."""
    signed_in = opened(monkeypatch)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", SITE)
    assert main(login(tmp_path)) == 0
    assert signed_in == [SITE]


def test_login_alone_signs_in_each_site_of_the_sources_configured_once(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Criterion 4: two sources of one site, one sign-in; a source of another, its own."""
    signed_in = opened(monkeypatch)
    config = tmp_path / "config.toml"
    config.write_text(
        f'[sources.confluence]\nspaces = ["MFS"]\nsite = "{SITE}"\n'
        f'[sources.jira]\nprojects = ["PRB"]\nsite = "{SITE}"\n'
        f'[sources.clientjira]\nconnector = "jira"\nprojects = ["ABC"]\nsite = "{CLIENT}"\n',
        "utf-8",
    )
    given = ["login", "--yes", "--config", str(config), "--format", "json"]
    assert main(given) == 0
    assert signed_in == [SITE, CLIENT]
    assert [row["site"] for row in json.loads(capsys.readouterr().out)] == [SITE, CLIENT]


def test_login_alone_leaves_a_source_that_signs_in_by_a_token_and_named_signs_it_in(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A session would serve it nothing; named, the user asked for it."""
    signed_in = opened(monkeypatch)
    for name, value in {
        "KB_MCP_SOURCES__JIRA__PROJECTS": '["PRB"]',
        "KB_MCP_SOURCES__JIRA__SITE": SITE,
        "KB_MCP_SOURCES__JIRA__API_TOKEN": "token-sentinel-3a9c",
    }.items():
        monkeypatch.setenv(name, value)
    assert main(login(tmp_path)) == 0
    assert signed_in == []
    assert main(login(tmp_path, "jira")) == 0
    assert signed_in == [SITE]


def test_a_source_that_signs_in_with_none_is_no_choice(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Under a registry whose sources sign in with none, nothing can be named: exit 2."""
    with pytest.raises(SystemExit) as stopped:
        main(login(tmp_path, "confluence"), sourced(WORKLOG))
    assert stopped.value.code == BAD_ARGUMENTS
    assert "invalid choice: 'confluence'" in capsys.readouterr().err


def test_a_site_not_set_is_refused_before_a_window_opens(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Named by the source's location; nothing is signed in to."""

    def refused(*_: object, **__: object) -> None:
        raise AssertionError

    monkeypatch.setattr(login_module, "save_session", refused)
    assert main(login(tmp_path, "jira")) == BAD_ARGUMENTS
    assert "sources.jira.site: not set; add it to the settings" in capsys.readouterr().err


def test_login_of_one_source_refuses_no_setting_of_another(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Criterion 4: Confluence configured without its site stops no sign-in of Jira's."""
    signed_in = opened(monkeypatch)
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SPACES", '["MFS"]')
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", SITE)
    assert main(login(tmp_path, "jira")) == 0
    assert signed_in == [SITE]
    assert "run.refused" not in capsys.readouterr().err


def test_the_command_says_the_source_s_other_settings_are_not_used(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """An email given signs in by no browser: said, by its layer; the source named, last."""
    opened(monkeypatch)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", SITE)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__EMAIL", "someone@example.invalid")
    assert main(login(tmp_path, "jira")) == 0
    err = capsys.readouterr().err
    assert "ignored: sources.jira.email (KB_MCP_SOURCES__JIRA__EMAIL)" in err
    assert "login signs in in a browser" in err
    copied = err.split("kb-mcp login")[1]
    command = [line for line in copied.splitlines() if not line.startswith("not in the command")]
    assert command[-1].strip() == "jira"


class DriveTable(BaseModel):
    """A source's table of a connector of these tests' own, which signs in to a folder."""

    model_config = TABLE

    folder: str | None = None


def drive_signed_in(
    settings: Settings, sources: tuple[Source, ...], chrome: Path | None, **given: bool
) -> tuple[tuple[SignedIn, ...], bool]:
    """Sign each source in: its run, as its connector names it."""
    assert (chrome, given) == (None, {"extensions": False})
    folders = [getattr(settings.sources, each.name).folder for each in sources]
    return tuple(SignedIn(site=str(folder), session=settings.session) for folder in folders), True


def drive_checks(settings: Settings, sources: tuple[Source, ...]) -> list[Check]:
    """Check each source: its check, as its connector names it."""
    return [
        Check(name=each.name, found=str(getattr(settings.sources, each.name).folder))
        for each in sources
    ]


DRIVE = replace(
    WORKLOG,
    name="drive",
    settings=("folder",),
    table_path=f"{__name__}:DriveTable",
    location="folder",
    login=f"{__name__}:drive_signed_in",
    checks=f"{__name__}:drive_checks",
)
WITH_DRIVE = (*SOURCES, Source(name="drive", connector=DRIVE))


def test_a_connector_of_its_own_signs_in_by_its_run_and_reads_none_of_another(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Nothing of the command names Atlassian: its usage, its run, its settings' use.

    Each other source's location is said not applied, as login reads it.
    """
    given = ["--format", "json"]
    assert main([*login(tmp_path, "drive"), *given], WITH_DRIVE) == BAD_ARGUMENTS
    err = capsys.readouterr().err
    assert "sources.drive.folder: not set; add it to the settings\n" in err.replace("'", "\n")
    monkeypatch.setenv("KB_MCP_SOURCES__DRIVE__FOLDER", "/made/up")
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", SITE)
    assert main([*login(tmp_path, "drive"), *given], WITH_DRIVE) == 0
    out, err = capsys.readouterr()
    assert [row["site"] for row in json.loads(out)] == ["/made/up"]
    assert f"sources.jira.site: {SITE} (not applied: jira not signed in by this login)\n" in err


def test_doctor_checks_each_source_by_its_connector_s_own_checks(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Only those that this machine configures: its check after the machine's."""
    monkeypatch.setenv("KB_MCP_SOURCES__DRIVE__FOLDER", "/made/up")
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options, WITH_DRIVE) == 0
    names = [check["name"] for check in json.loads(capsys.readouterr().out)]
    assert names == ["python", "pandoc", "data directory", "drive"]


def test_a_login_of_two_sites_that_fails_at_the_second_says_the_first_signed_in(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Review round 1: exit 3, the first site in the result and in login.signed_in."""

    def first_alone(_: object, site: str, *__: object, **___: object) -> None:
        if site == CLIENT:
            message = "the sign-in window was closed"
            raise SignInFailedError(message)

    monkeypatch.setattr(login_module, "save_session", first_alone)
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SITE", SITE)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", CLIENT)
    assert main([*login(tmp_path), "--format", "json"]) == SIGN_IN_AGAIN
    assert [row["site"] for row in json.loads(capsys.readouterr().out)] == [SITE]
    assert [each["site"] for each in logged_as(tmp_path, "login.signed_in")] == [SITE]
    assert [each["site"] for each in logged_as(tmp_path, "login.not_signed_in")] == [CLIENT]


def test_a_login_of_two_sites_that_fails_at_the_first_signs_in_the_second(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 070, criterion 3: the next site is tried; exit 3, the second in the result."""
    tried: list[str] = []

    def second_alone(_: object, site: str, *__: object, **___: object) -> None:
        tried.append(site)
        if site == SITE:
            message = "the sign-in window was closed"
            raise SignInFailedError(message)

    monkeypatch.setattr(login_module, "save_session", second_alone)
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SITE", SITE)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", CLIENT)
    assert main([*login(tmp_path), "--format", "json"]) == SIGN_IN_AGAIN
    assert tried == [SITE, CLIENT]
    assert [row["site"] for row in json.loads(capsys.readouterr().out)] == [CLIENT]
    assert [each["site"] for each in logged_as(tmp_path, "login.not_signed_in")] == [SITE]
    assert [each["site"] for each in logged_as(tmp_path, "login.signed_in")] == [CLIENT]


def test_login_alone_leaves_a_source_by_a_token_without_its_site_as_with_one(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 070, review round 1: a session would serve it nothing, site or not: exit 0.

    Jira by an API token, with its email and no site, Confluence with its own: Confluence's
    site is signed in, and Jira is neither signed in nor refused, the echo saying nothing
    of its site. Named, Jira would sign in in the browser: refused without its site, exit 2.
    """
    signed_in = opened(monkeypatch)
    for name, value in {
        "KB_MCP_SOURCES__CONFLUENCE__SITE": SITE,
        "KB_MCP_SOURCES__JIRA__PROJECTS": '["PRB"]',
        "KB_MCP_SOURCES__JIRA__EMAIL": "someone@example.invalid",
        "KB_MCP_SOURCES__JIRA__API_TOKEN": "token-sentinel-5d1e",
    }.items():
        monkeypatch.setenv(name, value)
    assert main([*login(tmp_path), "--format", "json"]) == 0
    out, err = capsys.readouterr()
    assert signed_in == [SITE]
    assert [row["site"] for row in json.loads(out)] == [SITE]
    assert "will not be signed in" not in err
    assert logged_as(tmp_path, "login.refused") == []
    assert main(login(tmp_path, "jira")) == BAD_ARGUMENTS
    assert "sources.jira.site: not set; add it to the settings" in capsys.readouterr().err
    assert signed_in == [SITE]


def drive_signed_in_by_default(
    settings: Settings, sources: tuple[Source, ...], _chrome: Path | None, **_given: bool
) -> tuple[tuple[SignedIn, ...], bool]:
    """Sign each source in, unnamed: its run, as its connector names it."""
    folders = [getattr(settings.sources, each.name).folder for each in sources]
    return tuple(SignedIn(site=str(folder), session=settings.session) for folder in folders), True


def test_a_connector_s_login_that_does_not_complete_stops_no_other_connector_s(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 070: Atlassian's sign-in does not complete; the drive's, run after it, signs in."""

    def closed(*_: object, **__: object) -> None:
        message = "the sign-in window was closed"
        raise SignInFailedError(message)

    monkeypatch.setattr(login_module, "save_session", closed)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__SITE", SITE)
    monkeypatch.setenv("KB_MCP_SOURCES__DRIVE__FOLDER", "/made/up")
    drive = replace(DRIVE, login=f"{__name__}:drive_signed_in_by_default")
    registry = (*SOURCES, Source(name="drive", connector=drive))
    assert main([*login(tmp_path), "--format", "json"], registry) == SIGN_IN_AGAIN
    assert [row["site"] for row in json.loads(capsys.readouterr().out)] == ["/made/up"]
    assert [each["site"] for each in logged_as(tmp_path, "login.not_signed_in")] == [SITE]


def test_login_alone_signs_in_the_others_past_a_source_without_its_site(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 070, by the user: "We should be tolerant"; "refuse when named".

    Jira in use without its site, Confluence with its own: the echo says that Jira will
    not be signed in, and why; Confluence's site is signed in, and an error, login.refused,
    names Jira and the setting: exit 1. Named, Jira refuses the run, exit 2.
    """
    signed_in = opened(monkeypatch)
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SITE", SITE)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__PROJECTS", '["PRB"]')
    reason = "sources.jira.site: not set; add it to the settings"
    assert main([*login(tmp_path), "--format", "json"]) == 1
    out, err = capsys.readouterr()
    assert signed_in == [SITE]
    assert [row["site"] for row in json.loads(out)] == [SITE]
    assert f"  source jira: will not be signed in, {reason}\n" in err
    (refused,) = logged_as(tmp_path, "login.refused")
    assert (refused["level"], refused["source"], refused["reason"]) == ("error", "jira", reason)
    assert main(login(tmp_path, "jira")) == BAD_ARGUMENTS
    assert reason in capsys.readouterr().err
    assert signed_in == [SITE]
