"""The doctor gives each check what it found, and its status folds their states."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.app.doctor import doctor
from kb_mcp.cli.main import main
from kb_mcp.sources.atlassian.declared import ATLASSIAN
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.worklog.declared import WORKLOG
from tests.composed import MODEL, sourced

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

SITE = "https://sandbox.example.invalid"
SOME_FAILED = 1
REFUSED = 2
NOT_SIGNED_IN = 3
# A source of the Atlassian account configured, with no site set.
A_SOURCE = "KB_MCP_SOURCES__JIRA__PROJECTS"


def states(checks: list[object]) -> dict[str, str]:
    """Map each check to its state."""
    return {each.name: each.state for each in checks}  # type: ignore[attr-defined]


def test_without_a_site_the_doctor_says_so_and_checks_no_network(tmp_path: Path) -> None:
    """With no site set, the checks that need one are replaced by that check."""
    found = states(doctor(MODEL(data_dir=tmp_path / "data"), [ATLASSIAN]))
    assert found["site"] == "failed"
    assert "tls" not in found
    assert "sign-in" not in found


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
    assert (
        states(
            doctor(
                MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=tmp_path / "data"),
                [ATLASSIAN],
            )
        )["tls"]
        == state
    )


def test_without_a_saved_session_the_doctor_exits_3(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """No session saved means signing in again, whatever else holds."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--site", SITE]
    assert main(options) == NOT_SIGNED_IN
    assert "sign-in: no session saved: run kb-mcp login atlassian" in capsys.readouterr().out
    assert (
        states(
            doctor(
                MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=tmp_path / "data"),
                [ATLASSIAN],
            )
        )["sign-in"]
        == "sign in again"
    )


def test_a_check_that_fails_makes_the_doctor_exit_1(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """With a source of the account but without a site, the doctor cannot pass."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    assert main(["doctor", "--config", str(tmp_path / "none.toml")]) == SOME_FAILED


@pytest.mark.parametrize(
    ("detail", "named"),
    [
        ("short", ["pandoc", "site"]),
        ("detailed", ["python", "pandoc", "data directory", "site"]),
    ],
)
def test_the_doctor_shows_the_checks_not_well_or_in_detail_every_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    detail: str,
    named: list[str],
) -> None:
    """Without pandoc nor a site: those two in short, all four in detail, then the count well."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--detail", detail]
    assert main(options) == SOME_FAILED
    *checks, count = capsys.readouterr().out.splitlines()
    assert [check.split(": ")[0] for check in checks] == named
    assert "pandoc: not found on PATH" in checks
    assert count == "2 of 4 checks well"


def test_the_doctor_gives_every_check_as_json(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """One document: each check's name, what it found, and its state."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options) == SOME_FAILED
    checks = json.loads(capsys.readouterr().out)
    assert [(check["name"], check["state"]) for check in checks] == [
        ("python", "well"),
        ("pandoc", "failed"),
        ("data directory", "well"),
        ("site", "failed"),
    ]
    assert checks[1]["found"] == "not found on PATH"


def test_a_machine_with_neither_a_site_nor_a_source_of_it_gets_the_machine_s_checks_alone(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Plan 031, criterion 6: such as one with the work log alone, failed for nothing: exit 0."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KB_MCP_SOURCES__WORKLOG__PATH", str(tmp_path))
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options) == 0
    names = [verdict["name"] for verdict in json.loads(capsys.readouterr().out)]
    assert names == ["python", "pandoc", "data directory"]


def test_a_registry_without_an_account_reads_none_of_it(
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
    """A token and an email without a site do not read as a sign-in that holds; exit 0.

    And a source's setting, which makes the site's check run, is not said not read.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL", "someone@example.invalid")
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN", "token-sentinel-7f2b")
    options = ["doctor", "--config", str(tmp_path / "none.toml")]
    assert main(options) == 0
    err = capsys.readouterr().err
    assert "ignored: accounts.atlassian.api_token (KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN)" in err
    assert "no site nor source of it: its sign-in not checked" in err
    assert "token-sentinel-7f2b" not in err
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    assert main([*options, "--detail", "detailed"]) == SOME_FAILED
    assert f"{A_SOURCE}): not read by doctor" not in capsys.readouterr().err


def test_a_token_without_its_email_refuses_only_a_sign_in_that_is_checked(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Neither a site nor a source: not checked, exit 0. With a source of it: exit 2."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN", "token-sentinel-7f2b")
    options = ["doctor", "--config", str(tmp_path / "none.toml")]
    assert main(options) == 0
    assert "its sign-in not checked" in capsys.readouterr().err
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    assert main(options) == REFUSED
    assert "accounts.atlassian.email: not set" in capsys.readouterr().err
