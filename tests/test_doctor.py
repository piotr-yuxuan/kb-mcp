"""The doctor gives each check a verdict, and its status follows from them."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters import http
from atlassian_offline_mcp.app.doctor import FAILED, SIGN_IN, WELL, doctor
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.settings import Settings

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
    found = states(doctor(Settings(None, tmp_path / "data")))
    assert found["site"] == FAILED
    assert "tls" not in found
    assert "session" not in found


def test_a_missing_pandoc_fails_its_check(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The mirror needs pandoc; its absence is said plainly."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert states(doctor(Settings(None, tmp_path / "data")))["pandoc"] == FAILED


@pytest.mark.parametrize(("verified", "state"), [(True, WELL), (False, WELL), (None, FAILED)])
def test_tls_inspection_is_reported_and_only_no_answer_fails(
    tmp_path: Path, monkeypatch: MonkeyPatch, *, verified: bool | None, state: str
) -> None:
    """Inspected TLS works through the OS trust store; a site that does not answer fails."""
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: verified)
    assert states(doctor(Settings(SITE, tmp_path / "data")))["tls"] == state


def test_without_a_saved_session_the_doctor_exits_3(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """No session saved means signing in again, whatever else holds."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    options = ["doctor", "--config", str(tmp_path / "none.toml"), "--site", SITE]
    assert main(options) == NOT_SIGNED_IN
    assert "session: none saved" in capsys.readouterr().out
    assert states(doctor(Settings(SITE, tmp_path / "data")))["session"] == SIGN_IN


def test_a_check_that_fails_makes_the_doctor_exit_1(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Without a site, the doctor cannot pass."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["doctor", "--config", str(tmp_path / "none.toml")]) == SOME_FAILED
