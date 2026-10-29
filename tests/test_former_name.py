"""A run that finds what the former name left stops before acting and says how to move it.

The rules are plan 027's: the former settings file in place of a missing default, the
former data directory where the default is used and missing, a variable of the former
prefix, and a setting whose value names the former name. Every test builds the former
places in its scratch home; none is ever moved.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from kb_mcp.config.adapters.settings_file import SETTINGS_PATH
from kb_mcp.config.app.settings import load_settings
from kb_mcp.config.domain.former_name import FormerNameError
from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

FORMER_FILE = Path(".config/atlassian-offline-mcp/config.toml")
FORMER_DATA = Path("atlassian-offline-mcp")
NEW_FILE = Path(".config/kb-mcp/config.toml")
NEW_DATA = Path("kb-mcp")
FILE_MOVE = (
    "mkdir -p ~/.config/kb-mcp"
    " && mv ~/.config/atlassian-offline-mcp/config.toml ~/.config/kb-mcp/config.toml"
)
DATA_MOVE = "mv ~/atlassian-offline-mcp ~/kb-mcp"
SITE = "https://secret.example.invalid"


@pytest.fixture
def home() -> Path:
    """Give the scratch home that every test has, resolved, as the loader is given it."""
    return Path.home().resolve()


def place(home: Path, where: Path, settings: str = "") -> None:
    """Make a settings file, or a folder holding a file, under the home."""
    path = home / where
    if path.suffix == ".toml":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(settings, encoding="utf-8")
    else:
        path.mkdir(parents=True)
        (path / "index.sqlite").write_bytes(b"")


def files(home: Path) -> set[str]:
    """Name every file and folder under the home, by its path from it."""
    return {path.relative_to(home).as_posix() for path in home.rglob("*")}


def refusal(
    home: Path, path: Path = SETTINGS_PATH, flags: dict[str, tuple[str, object]] | None = None
) -> FormerNameError:
    """Load the settings, which must stop for the former name; nothing must have moved."""
    before = files(home)
    with pytest.raises(FormerNameError) as caught:
        load_settings(path, flags or {}, home)
    assert files(home) == before
    return caught.value


def block(advice: str) -> list[str]:
    """Give the lines of the moves' block: its heading, down to the blank line ending it."""
    lines = advice.splitlines()
    if "# Move the files:" not in lines:
        return []
    start = lines.index("# Move the files:")
    return lines[start : lines.index("", start)]


def test_the_former_settings_file_alone_is_moved(home: Path) -> None:
    """Rule 1: the default file missing, the former one is moved to it."""
    place(home, FORMER_FILE)
    assert block(refusal(home).advice) == ["# Move the files:", FILE_MOVE]


def test_the_former_data_directory_alone_is_moved(home: Path) -> None:
    """Rule 2: the default data directory used and missing, the former one is moved to it."""
    place(home, FORMER_DATA)
    assert block(refusal(home).advice) == ["# Move the files:", DATA_MOVE]


@pytest.mark.parametrize(
    ("name", "renamed"),
    [
        ("ATLASSIAN_OFFLINE_MCP_SITE", "KB_MCP_SITE"),
        ("atlassian_offline_mcp_site", "KB_MCP_SITE"),
        ("ATLASSIAN_OFFLINE_MCP_LOGS__DIR", "KB_MCP_LOGS__DIR"),
    ],
)
def test_a_former_variable_is_renamed_and_its_value_never_shown(
    home: Path, monkeypatch: MonkeyPatch, name: str, renamed: str
) -> None:
    """Rule 3, in any case: the variable and its new name, with no move to make."""
    monkeypatch.setenv(name, SITE)
    advice = refusal(home).advice
    assert f"{name} to {renamed}" in advice.splitlines()
    assert "secret" not in advice
    assert block(advice) == []


def test_a_value_naming_the_former_name_names_its_setting_never_its_value(
    home: Path, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Rule 4, in any case and from any layer: the setting and its layer, not its value."""
    monkeypatch.setenv("KB_MCP_LOGS__DIR", str(tmp_path / "Atlassian_Offline_MCP-logs"))
    data = tmp_path / "former-atlassian-offline-mcp"
    advice = refusal(home, flags={"--data-dir": ("data_dir", str(data))}).advice
    assert "data_dir (--data-dir)" in advice.splitlines()
    assert "logs.dir (KB_MCP_LOGS__DIR)" in advice.splitlines()
    assert str(tmp_path) not in advice


def test_the_former_file_is_judged_in_place_of_the_missing_one(home: Path) -> None:
    """A former file naming the former data directory: its move, and its key to change."""
    place(home, FORMER_FILE, 'data_dir = "~/atlassian-offline-mcp"\n')
    place(home, FORMER_DATA)
    advice = refusal(home).advice
    assert block(advice) == ["# Move the files:", FILE_MOVE]
    assert "data_dir (config.toml)" in advice.splitlines()


def test_a_new_file_naming_the_default_data_directory_moves_the_former(home: Path) -> None:
    """Rule 2 judges the data directory the run would use, whoever names it."""
    place(home, NEW_FILE, 'data_dir = "~/kb-mcp"\n')
    place(home, FORMER_DATA)
    assert block(refusal(home).advice) == ["# Move the files:", DATA_MOVE]


@pytest.mark.parametrize(
    ("made", "environment"),
    [
        pytest.param((NEW_FILE, NEW_DATA), {}, id="new places too"),
        pytest.param((NEW_FILE, NEW_DATA), {"ATLASSIAN_OFFLINE_MCP_SITE": ""}, id="empty variable"),
        pytest.param(
            (NEW_FILE, NEW_DATA),
            {"ATLASSIAN_OFFLINE_MCP_SITE": SITE, "KB_MCP_SITE": SITE},
            id="variable renamed already",
        ),
        pytest.param((NEW_FILE, FORMER_DATA / ".git"), {}, id="former data in git"),
    ],
)
def test_a_run_that_finds_new_places_goes_on(
    home: Path, monkeypatch: MonkeyPatch, made: tuple[Path, ...], environment: dict[str, str]
) -> None:
    """The former places exist beside what the run uses instead: nothing stops it."""
    place(home, FORMER_FILE)
    place(home, FORMER_DATA)
    for where in made:
        place(home, where)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    before = files(home)
    load_settings(SETTINGS_PATH, {}, home)
    assert files(home) == before


def test_a_run_given_other_places_goes_on(home: Path, tmp_path: Path) -> None:
    """A settings file and a data directory given, as the sandbox's: the former are not used."""
    place(home, FORMER_FILE)
    place(home, FORMER_DATA)
    before = files(home)
    flags = {"--data-dir": ("data_dir", str(tmp_path / "data"))}
    load_settings(tmp_path / "none.toml", flags, home)
    assert files(home) == before


def test_check_stops_before_any_log_file_and_moves_nothing(tmp_path: Path) -> None:
    """``kb-mcp check`` in a home holding everything: exit 2, the advice, nothing written."""
    home = tmp_path / "home"
    place(home, FORMER_FILE)
    place(home, FORMER_DATA)
    before = files(home)
    environment = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "ATLASSIAN_OFFLINE_MCP_SITE": SITE,
    }
    done = subprocess.run(
        [sys.executable, "-m", "kb_mcp", "check"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == ExitStatus.REFUSED
    assert "settings.refused" in done.stderr
    assert block(done.stderr) == ["# Move the files:", FILE_MOVE, DATA_MOVE]
    assert "ATLASSIAN_OFFLINE_MCP_SITE to KB_MCP_SITE" in done.stderr.splitlines()
    assert "secret" not in done.stderr
    assert files(home) == before
