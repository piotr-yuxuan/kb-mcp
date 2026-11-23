"""The doctor gives each check what it found, and its status folds their states."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.app.doctor import doctor
from kb_mcp.cli.main import main
from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.declaration import Source
from kb_mcp.sources.worklog.declared import WORKLOG
from tests.composed import MODEL, model_of, sourced
from tests.test_fetching import FakeSite

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.settings import Settings

SITE = "https://sandbox.example.invalid"
HOST = "sandbox.example.invalid"
# A second site, a client's, and its Jira source.
CLIENT = "https://client.example.invalid"
CLIENT_JIRA = Source(name="clientjira", connector=JIRA)
SOME_FAILED = 1
NOT_SIGNED_IN = 3
# Jira's source configured, and its site.
A_SOURCE = "KB_MCP_SOURCES__JIRA__PROJECTS"
A_SITE = "KB_MCP_SOURCES__JIRA__SITE"


def states(checks: list[object]) -> dict[str, str]:
    """Map each check to its state."""
    return {each.name: each.state for each in checks}  # type: ignore[attr-defined]


def configured(tmp_path: Path) -> Settings:
    """Give settings whose Confluence and Jira sources are of the site, with a data folder."""
    return MODEL(
        sources={"confluence": {"site": SITE}, "jira": {"site": SITE}},
        data_dir=tmp_path / "data",
    )


def test_a_missing_pandoc_fails_its_check(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The mirror needs pandoc; its absence is said plainly."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert states(doctor(MODEL(data_dir=tmp_path / "data"), []))["pandoc"] == "failed"


@pytest.mark.parametrize(("verified", "state"), [(True, "well"), (False, "well"), (None, "failed")])
def test_tls_inspection_is_reported_and_only_no_answer_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch, *, verified: bool | None, state: str
) -> None:
    """Inspected TLS works through the OS trust store; a site that does not answer fails."""
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: verified)
    found = states(doctor(configured(tmp_path), sourced(CONFLUENCE, JIRA)))
    assert found[f"tls {HOST}"] == state


def test_without_a_saved_session_the_doctor_exits_3(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """No session saved means signing in again, whatever else holds."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    monkeypatch.setenv(A_SITE, SITE)
    options = ["doctor", "--config", str(tmp_path / "none.toml")]
    assert main(options) == NOT_SIGNED_IN
    out = capsys.readouterr().out
    assert "sign-in jira: no session saved: run kb-mcp login jira" in out
    found = states(doctor(configured(tmp_path), sourced(JIRA)))
    assert found["sign-in jira"] == "sign in again"


def test_two_sources_of_one_site_are_checked_once_and_each_of_another_site_alone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 059: once a site, its TLS; each source by its own sign-in and API."""
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    sources = (*sourced(CONFLUENCE, JIRA), CLIENT_JIRA)
    settings = model_of(sources)(
        sources={
            "confluence": {"site": SITE},
            "jira": {"site": SITE},
            "clientjira": {"site": CLIENT},
        },
        data_dir=tmp_path / "data",
    )
    names = [each.name for each in doctor(settings, sources)]
    assert names == [
        "python",
        "pandoc",
        "data directory",
        f"tls {HOST}",
        "sign-in confluence",
        "sign-in jira",
        f"tls {CLIENT.removeprefix('https://')}",
        "sign-in clientjira",
    ]


def test_each_source_of_one_site_is_checked_by_its_own_sign_in(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review round 1: Confluence by its token, Jira by the site's session, none saved.

    Jira asks to sign in again by its own login; Confluence's check is its token's.
    """
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    monkeypatch.setattr(http, "client", lambda *_, **__: FakeSite().client())
    settings = MODEL(
        sources={
            "confluence": {"site": SITE, "email": "someone@example.invalid", "api_token": "t"},
            "jira": {"site": SITE},
        },
        data_dir=tmp_path / "data",
    )
    found = {each.name: each for each in doctor(settings, sourced(CONFLUENCE, JIRA))}
    assert (found["sign-in confluence"].found, found["confluence"].state) == (
        "an API token",
        "well",
    )
    assert found["sign-in jira"].found == "no session saved: run kb-mcp login jira"
    assert "jira" not in found


def test_a_source_configured_without_its_site_fails_its_own_check_alone(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 070, by the user: "We should be tolerant"; by its connector's light check.

    Jira without its site: a check named after it fails, naming the setting, after the
    others; Confluence's site and sign-in are checked, which asks to sign in: exit 3.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SITE", SITE)
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options) == NOT_SIGNED_IN
    checks = [(each["name"], each["state"]) for each in json.loads(capsys.readouterr().out)]
    assert checks[3:] == [
        (f"tls {HOST}", "well"),
        ("sign-in confluence", "sign in again"),
        ("jira", "failed"),
    ]
    monkeypatch.delenv("KB_MCP_SOURCES__CONFLUENCE__SITE")
    assert main(options) == SOME_FAILED
    (*_, jira) = json.loads(capsys.readouterr().out)
    assert jira == {
        "name": "jira",
        "found": "sources.jira.site: not set; add it to the settings",
        "state": "failed",
    }


@pytest.mark.parametrize(
    ("detail", "named"),
    [
        ("short", ["pandoc"]),
        ("detailed", ["python", "pandoc", "data directory"]),
    ],
)
def test_the_doctor_shows_the_checks_not_well_or_in_detail_every_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    detail: str,
    named: list[str],
) -> None:
    """Without pandoc: that one in short, all three in detail, then the count well."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--detail", detail]
    assert main(options) == SOME_FAILED
    *checks, count = capsys.readouterr().out.splitlines()
    assert [check.split(": ")[0] for check in checks] == named
    assert "pandoc: not found on PATH" in checks
    assert count == "2 of 3 checks well"


def test_the_doctor_gives_every_check_as_json(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """One document: each check's name, what it found, and its state."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options) == SOME_FAILED
    checks = json.loads(capsys.readouterr().out)
    assert [(check["name"], check["state"]) for check in checks] == [
        ("python", "well"),
        ("pandoc", "failed"),
        ("data directory", "well"),
    ]
    assert checks[1]["found"] == "not found on PATH"


def test_a_machine_with_no_source_that_signs_in_gets_the_machine_s_checks_alone(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 031, criterion 6: such as one with the work log alone, failed for nothing: exit 0."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KB_MCP_SOURCES__WORKLOG__PATH", str(tmp_path))
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options) == 0
    names = [verdict["name"] for verdict in json.loads(capsys.readouterr().out)]
    assert names == ["python", "pandoc", "data directory"]


def test_a_registry_without_a_source_that_signs_in_reads_none_of_it(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Any registry is checked: no setting of a package that it does not name is read."""
    monkeypatch.setenv("HOME", str(tmp_path))
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options, sourced(WORKLOG)) == 0
    names = [verdict["name"] for verdict in json.loads(capsys.readouterr().out)]
    assert names == ["python", "pandoc", "data directory"]


def test_a_sign_in_not_checked_is_said_so_and_the_settings_that_choose_it_are_read(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A token and an email of a source not configured do not read as a sign-in; exit 0.

    And a source's setting, which makes its checks run, is not said not read.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: None)
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__EMAIL", "someone@example.invalid")
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__API_TOKEN", "token-sentinel-7f2b")
    options = ["doctor", "--config", str(tmp_path / "none.toml")]
    assert main(options) == 0
    err = capsys.readouterr().err
    assert "ignored: sources.jira.api_token (KB_MCP_SOURCES__JIRA__API_TOKEN)" in err
    assert "jira not in use: not checked" in err
    assert "token-sentinel-7f2b" not in err
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    monkeypatch.setenv(A_SITE, SITE)
    assert main([*options, "--detail", "detailed"]) == SOME_FAILED
    assert f"{A_SOURCE}): not read by doctor" not in capsys.readouterr().err


def test_a_token_without_its_email_fails_only_a_sign_in_that_is_checked(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A source not in use: not checked, exit 0. In use, with its site: its check fails, 1."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__API_TOKEN", "token-sentinel-7f2b")
    options = ["doctor", "--config", str(tmp_path / "none.toml")]
    assert main(options) == 0
    assert "jira not in use: not checked" in capsys.readouterr().err
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    monkeypatch.setenv(A_SITE, SITE)
    assert main(options) == SOME_FAILED
    out = capsys.readouterr().out
    assert (
        "jira: sources.jira.email: not set; an API token signs in with its account's email" in out
    )
    assert "token-sentinel-7f2b" not in out


def test_a_source_with_its_site_alone_is_checked(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Review round 1: a site and a token, as sops gives them, with no project: checked."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    monkeypatch.setenv(A_SITE, SITE)
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options) == NOT_SIGNED_IN
    names = [verdict["name"] for verdict in json.loads(capsys.readouterr().out)]
    assert names[3:] == [f"tls {HOST}", "sign-in jira"]
