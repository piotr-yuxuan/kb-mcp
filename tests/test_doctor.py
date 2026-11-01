"""The doctor gives each check a verdict, and its status follows from them."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.app.doctor import doctor
from kb_mcp.cli.main import main
from kb_mcp.sources.atlassian.declared import ATLASSIAN
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.roles import FAILED, SIGN_IN, WELL
from kb_mcp.sources.worklog.declared import WORKLOG
from tests.composed import MODEL

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

SITE = "https://sandbox.example.invalid"
SOME_FAILED = 1
NOT_SIGNED_IN = 3
# A source of the Atlassian account configured, with no site set.
A_SOURCE = "KB_MCP_SOURCES__JIRA__PROJECTS"


def states(verdicts: list[object]) -> dict[str, str]:
    """Map each check to its state."""
    return {verdict.name: verdict.state for verdict in verdicts}  # type: ignore[attr-defined]


def test_without_a_site_the_doctor_says_so_and_checks_no_network(tmp_path: Path) -> None:
    """With no site set, the checks that need one are replaced by that verdict."""
    found = states(doctor(MODEL(data_dir=tmp_path / "data"), [ATLASSIAN]))
    assert found["site"] == FAILED
    assert "tls" not in found
    assert "sign-in" not in found


def test_a_missing_pandoc_fails_its_check(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The mirror needs pandoc; its absence is said plainly."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert states(doctor(MODEL(data_dir=tmp_path / "data"), []))["pandoc"] == FAILED


@pytest.mark.parametrize(("verified", "state"), [(True, WELL), (False, WELL), (None, FAILED)])
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
        == SIGN_IN
    )


def test_a_check_that_fails_makes_the_doctor_exit_1(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """With a source of the account but without a site, the doctor cannot pass."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    assert main(["doctor", "--config", str(tmp_path / "none.toml")]) == SOME_FAILED


@pytest.mark.parametrize(
    ("summary", "named"),
    [
        ("short", ["pandoc", "site"]),
        ("detailed", ["python", "pandoc", "data directory", "site"]),
    ],
)
def test_the_doctor_shows_the_checks_not_well_or_in_detail_every_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    summary: str,
    named: list[str],
) -> None:
    """Without pandoc nor a site: those two in short, all four in detail, then the count well."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--summary", summary]
    assert main(options) == SOME_FAILED
    *verdicts, count = capsys.readouterr().out.splitlines()
    assert [verdict.split(": ")[0] for verdict in verdicts] == named
    assert "pandoc: not found on PATH" in verdicts
    assert count == "2 of 4 checks well"


def test_the_doctor_gives_every_verdict_as_json(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """One document: each check's name, what it found, and its state."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(A_SOURCE, '["PRB"]')
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--format", "json"]
    assert main(options) == SOME_FAILED
    verdicts = json.loads(capsys.readouterr().out)
    assert [(verdict["name"], verdict["state"]) for verdict in verdicts] == [
        ("python", WELL),
        ("pandoc", FAILED),
        ("data directory", WELL),
        ("site", FAILED),
    ]
    assert verdicts[1]["found"] == "not found on PATH"


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
    assert main(options, (WORKLOG,)) == 0
    names = [verdict["name"] for verdict in json.loads(capsys.readouterr().out)]
    assert names == ["python", "pandoc", "data directory"]
