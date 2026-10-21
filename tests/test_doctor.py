"""The doctor names each check's verdict, from what the machine and the settings hold."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.app.doctor import SIGN_IN_AGAIN, doctor
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.commands import doctor as doctor_command
from atlassian_offline_mcp.domain.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

NOT_SIGNED_IN = 3


def test_without_a_site_the_doctor_says_so_and_checks_no_network(tmp_path: Path) -> None:
    """With no site set, the checks that need one are replaced by that verdict."""
    verdicts = dict(doctor(Settings(None, tmp_path / "data")))
    assert verdicts["site"] == "not set: add it to the settings or pass --site"
    assert "tls" not in verdicts
    assert "session" not in verdicts


def test_a_missing_pandoc_is_named(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The mirror needs pandoc; its absence is said plainly."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert dict(doctor(Settings(None, tmp_path / "data")))["pandoc"] == "not found on PATH"


def test_the_doctor_exits_3_when_the_session_must_be_renewed(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A verdict that asks to sign in again makes the exit status say so."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        doctor_command, "doctor", lambda _: [("session", f"none saved: {SIGN_IN_AGAIN}")]
    )
    assert main(["doctor", "--config", str(tmp_path / "none.toml")]) == NOT_SIGNED_IN
    assert SIGN_IN_AGAIN in capsys.readouterr().out
