"""The doctor names each check's verdict, from what the machine and the settings hold."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.app.doctor import doctor
from atlassian_offline_mcp.domain.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


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
