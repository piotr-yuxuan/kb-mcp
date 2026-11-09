"""Signing in keeps the site's cookies alone, in a file the user alone can read."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

from kb_mcp.cli.main import main
from kb_mcp.config.domain.settings import TABLE
from kb_mcp.sources.atlassian.fetch.adapters.browser import SignInFailedError
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, read_cookies
from kb_mcp.sources.atlassian.fetch.app import login as login_module
from kb_mcp.sources.declaration import Account
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.stages import Check, SignedIn
from kb_mcp.sources.worklog.declared import WORKLOG
from tests.composed import MODEL
from tests.test_cli import logged_as
from tests.test_observed import said

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings

SITE = "https://sandbox.example.invalid"
INSTRUCTION = f"Sign in to {SITE} in the Chrome window that opens.\n"
SIGNED_IN = "Signed in; the session is saved.\n"
SIGN_IN_AGAIN = 3
BAD_ARGUMENTS = 2


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
    settings = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=tmp_path / "data")
    login_module.save_session(settings, SITE, None, extensions=False)
    saved = read_cookies(settings.session / COOKIES)
    assert [(cookie["name"], cookie["path"]) for cookie in saved] == [
        ("tenant", "/"),
        ("wiki", "/wiki"),
    ]


@pytest.mark.parametrize("detail", ["short", "detailed"])
def test_the_command_says_what_to_do_on_stderr_and_its_result_on_stdout(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], detail: str
) -> None:
    """The instruction is a message, after the echo; the result, the same in each detail.

    As JSON, the result is one document.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(login_module, "save_session", lambda *_, **__: None)
    options = [
        "login",
        "atlassian",
        "--yes",
        "--config",
        str(tmp_path / "none.toml"),
        "--site",
        SITE,
    ]
    assert main([*options, "--detail", detail]) == 0
    out, err = capsys.readouterr()
    assert out == SIGNED_IN
    assert err.endswith(INSTRUCTION)
    assert main([*options, "--format", "json"]) == 0
    out, err = capsys.readouterr()
    assert err.endswith(INSTRUCTION)
    session = (tmp_path / "kb-mcp" / "session").resolve()
    assert json.loads(out) == {"site": SITE, "session": str(session)}


def test_a_sign_in_that_does_not_complete_exits_3_with_an_error(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The instruction, then the error login.not_signed_in with why; nothing on stdout.

    The run's log file holds the error too.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    reason = "the sign-in window was closed"

    def closed(*_: object, **__: object) -> None:
        raise SignInFailedError(reason)

    monkeypatch.setattr(login_module, "save_session", closed)
    options = [
        "login",
        "atlassian",
        "--yes",
        "--config",
        str(tmp_path / "none.toml"),
        "--site",
        SITE,
    ]
    assert main(options) == SIGN_IN_AGAIN
    out, err = capsys.readouterr()
    assert out == ""
    assert ("error", "login.not_signed_in") in said(err)
    assert err.index(INSTRUCTION) < err.index("login.not_signed_in") < err.index(reason)
    (failed,) = logged_as(tmp_path, "login.not_signed_in")
    assert (failed["level"], failed["reason"]) == ("error", reason)


def test_login_alone_exits_2_naming_the_sign_ins(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 031, criterion 6: a sign-in is named, as a source is; its usage names the choice."""
    with pytest.raises(SystemExit) as stopped:
        main(["login", "--config", str(tmp_path / "none.toml"), "--site", SITE])
    assert stopped.value.code == BAD_ARGUMENTS
    err = capsys.readouterr().err
    assert "{atlassian}" in err
    assert "the following arguments are required: account" in err


def test_a_sign_in_no_source_declares_is_no_choice(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """Under a registry whose sources sign in with none, nothing can be named: exit 2."""
    options = ["atlassian", "--config", str(tmp_path / "none.toml")]
    with pytest.raises(SystemExit) as stopped:
        main(["login", *options], (WORKLOG,))
    assert stopped.value.code == BAD_ARGUMENTS
    assert "invalid choice: 'atlassian'" in capsys.readouterr().err


def test_a_site_not_set_is_refused_before_a_window_opens(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Named by the account's first setting; nothing is signed in to."""
    monkeypatch.setenv("HOME", str(tmp_path))

    def opened(*_: object, **__: object) -> None:
        raise AssertionError

    monkeypatch.setattr(login_module, "save_session", opened)
    options = ["login", "atlassian", "--yes", "--config", str(tmp_path / "none.toml")]
    assert main(options) == BAD_ARGUMENTS
    assert "accounts.atlassian.site: not set" in capsys.readouterr().err


def test_the_command_says_the_account_s_other_settings_are_not_used(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A token and an email given sign in by no browser: said, by each setting's layer."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(login_module, "save_session", lambda *_, **__: None)
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL", "someone@example.invalid")
    options = ["login", "atlassian", "--yes", "--config", str(tmp_path / "none.toml")]
    assert main([*options, "--site", SITE]) == 0
    err = capsys.readouterr().err
    assert "ignored: accounts.atlassian.email (KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL)" in err
    assert "login signs in in a browser" in err
    assert f"--site {SITE}" in err.split("kb-mcp login")[1]
    assert err.split("kb-mcp login")[1].rstrip().splitlines()[-2].strip() == "atlassian"


class DriveAccount(BaseModel):
    """A second account's table, of a registry of these tests' own."""

    model_config = TABLE

    folder: str | None = None


def drive_signed_in(
    settings: Settings, chrome: Path | None, *, extensions: bool
) -> SignedIn | None:
    """Sign in to a second account: its run, as its declaration names it."""
    assert (chrome, extensions) == (None, False)
    return SignedIn(site=str(settings.accounts.drive.folder), session=settings.session)


def drive_checks(settings: Settings) -> list[Check]:
    """Check a second account: its check, as its declaration names it."""
    return [Check(name="drive", found=str(settings.accounts.drive.folder))]


DRIVE = Account(
    name="drive",
    table_path=f"{__name__}:DriveAccount",
    settings=("folder",),
    login=f"{__name__}:drive_signed_in",
    checks=f"{__name__}:drive_checks",
)
TWO_ACCOUNTS = (*SOURCES[:2], replace(SOURCES[2], account=DRIVE))


def test_a_second_account_signs_in_by_its_own_run_and_reads_none_of_the_first(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Nothing of the command names Atlassian: its usage, its run, its settings' use.

    Each account's first setting is said applied for the one named alone, and ``--site``,
    which sets the Atlassian site, is offered to that account alone.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    given = ["--yes", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(["login", "drive", *given], TWO_ACCOUNTS) == BAD_ARGUMENTS
    err = capsys.readouterr().err
    assert "accounts.drive.folder: not set; add it to the settings\n" in err.replace("'", "\n")
    assert "--site" not in err.partition("run.refused")[2]
    monkeypatch.setenv("KB_MCP_ACCOUNTS__DRIVE__FOLDER", "/made/up")
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL", "someone@example.invalid")
    assert main(["login", "drive", *given, "--site", SITE], TWO_ACCOUNTS) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["site"] == "/made/up"
    assert f"accounts.atlassian.site: {SITE} (not applied: atlassian not named)\n" in err
    assert (
        "ignored: accounts.atlassian.email (KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL): atlassian not"
        in err
    )
    assert "--site" not in err.split("kb-mcp login")[1]


def test_doctor_checks_each_account_by_its_own_checks(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Only that which this machine uses: its check after the machine's."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KB_MCP_ACCOUNTS__DRIVE__FOLDER", "/made/up")
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options, TWO_ACCOUNTS) == 0
    names = [check["name"] for check in json.loads(capsys.readouterr().out)]
    assert names == ["python", "pandoc", "data directory", "drive"]


def test_a_prepare_names_each_account_s_first_setting_with_its_own_sources(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Two accounts unset: each line names the sources of that account, and no other."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KB_MCP_SOURCES__WORKLOG__PATH", str(tmp_path))
    given = ["prepare", "--dry-run", "--config", str(tmp_path / "none.toml")]
    assert main(given, TWO_ACCOUNTS) == 0
    err = capsys.readouterr().err
    assert "accounts.atlassian.site: not set; any documents of confluence, jira get no" in err
    assert "accounts.drive.folder: not set; any documents of worklog get no" in err
