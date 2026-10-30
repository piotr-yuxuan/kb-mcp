"""The doctor gives each check a verdict, and its status follows from them."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.app.doctor import FAILED, SIGN_IN, WELL, doctor
from tests.composed import MODEL

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

SITE = "https://sandbox.example.invalid"
SOME_FAILED = 1
NOT_SIGNED_IN = 3


def states(verdicts: list[object]) -> dict[str, str]:
    """Map each check to its state."""
    return {verdict.name: verdict.state for verdict in verdicts}  # type: ignore[attr-defined]


def test_without_a_site_the_doctor_says_so_and_checks_no_network(tmp_path: Path) -> None:
    """With no site set, the checks that need one are replaced by that verdict."""
    found = states(doctor(MODEL(data_dir=tmp_path / "data")))
    assert found["site"] == FAILED
    assert "tls" not in found
    assert "sign-in" not in found


def test_a_missing_pandoc_fails_its_check(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The mirror needs pandoc; its absence is said plainly."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert states(doctor(MODEL(data_dir=tmp_path / "data")))["pandoc"] == FAILED


@pytest.mark.parametrize(("verified", "state"), [(True, WELL), (False, WELL), (None, FAILED)])
def test_tls_inspection_is_reported_and_only_no_answer_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch, *, verified: bool | None, state: str
) -> None:
    """Inspected TLS works through the OS trust store; a site that does not answer fails."""
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: verified)
    assert (
        states(doctor(MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=tmp_path / "data")))[
            "tls"
        ]
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
    assert "sign-in: no session saved: run kb-mcp login" in capsys.readouterr().out
    assert (
        states(doctor(MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=tmp_path / "data")))[
            "sign-in"
        ]
        == SIGN_IN
    )


def test_a_check_that_fails_makes_the_doctor_exit_1(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Without a site, the doctor cannot pass."""
    monkeypatch.setenv("HOME", str(tmp_path))
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
