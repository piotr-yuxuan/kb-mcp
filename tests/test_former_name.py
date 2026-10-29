"""A run that finds what the former name left stops before acting and says how to move it.

The rules are plan 027's: the former settings file in place of a missing default, the
former data directory where the default is used and missing, a variable of the former
prefix, and a path setting with a folder or file named after the former name. Every test
builds the former places in its scratch home; none is ever moved.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.main import main
from kb_mcp.config.adapters.settings_file import SETTINGS_PATH
from kb_mcp.config.app.settings import load_settings
from kb_mcp.config.domain.former_name import FormerNameError
from kb_mcp.kernel.exit_status import ExitStatus

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

ROOT = Path(__file__).parents[1]
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
    assert "Then, by hand, as docs/how-to/move-to-kb-mcp.md says:" in advice.splitlines()
    assert "secret" not in advice
    assert block(advice) == []


def test_a_path_naming_the_former_name_names_its_setting_never_its_value(
    home: Path, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Rule 4, in any case and from any layer: a path setting and its layer, not its value."""
    worklog = tmp_path / "atlassian-offline-mcp-notes"
    place(home, NEW_FILE, f'sources.worklog.path = "{worklog}"\n')
    monkeypatch.setenv("KB_MCP_LOGS__DIR", str(tmp_path / "Atlassian_Offline_MCP-logs"))
    data = tmp_path / "Atlassian Offline MCP" / "data"
    advice = refusal(home, flags={"--data-dir": ("data_dir", str(data))}).advice
    assert "data_dir (--data-dir)" in advice.splitlines()
    assert "logs.dir (KB_MCP_LOGS__DIR)" in advice.splitlines()
    assert "sources.worklog.path (config.toml)" in advice.splitlines()
    assert str(tmp_path) not in advice


def test_a_settings_file_given_by_its_former_path_is_named(home: Path) -> None:
    """Rule 4 judges the settings file given, which a script may still name."""
    place(home, FORMER_FILE)
    advice = refusal(home, home / FORMER_FILE).advice
    assert "the settings file (--config)" in advice.splitlines()
    assert block(advice) == []


@pytest.mark.parametrize(
    "given",
    [
        pytest.param(NEW_FILE, id="straight"),
        pytest.param(Path(".config/other/../kb-mcp/config.toml"), id="through another folder"),
    ],
)
def test_the_default_settings_file_named_by_any_path_is_the_default(
    home: Path, monkeypatch: MonkeyPatch, given: Path
) -> None:
    """Rule 1 holds for ``--config`` naming the default, from the home or relative to it."""
    place(home, FORMER_FILE)
    monkeypatch.chdir(home)
    for path in (given, home / given):
        assert block(refusal(home, path).advice) == ["# Move the files:", FILE_MOVE]


def test_the_default_data_directory_named_by_any_path_is_the_default(home: Path) -> None:
    """Rule 2 holds for ``--data-dir`` naming the default through another folder."""
    place(home, FORMER_DATA)
    flags = {"--data-dir": ("data_dir", str(home / "other" / ".." / NEW_DATA))}
    assert block(refusal(home, flags=flags).advice) == ["# Move the files:", DATA_MOVE]


def test_the_defaults_named_through_a_linked_home_are_the_defaults(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A home reached by a link, its places written from the link: rules 1 and 2 hold."""
    home = tmp_path / "home"
    home.mkdir()
    link = tmp_path / "link"
    link.symlink_to(home)
    monkeypatch.setenv("HOME", str(link))
    place(home, FORMER_FILE)
    place(home, FORMER_DATA)
    flags = {"--data-dir": ("data_dir", str(link / NEW_DATA))}
    advice = refusal(home, link / NEW_FILE, flags).advice
    assert block(advice) == ["# Move the files:", FILE_MOVE, DATA_MOVE]


def test_an_empty_new_variable_is_not_set(home: Path, monkeypatch: MonkeyPatch) -> None:
    """An empty variable is ignored, as the loader ignores it: the former one still stops."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", SITE)
    monkeypatch.setenv("KB_MCP_SITE", "")
    assert "ATLASSIAN_OFFLINE_MCP_SITE to KB_MCP_SITE" in refusal(home).advice.splitlines()


@pytest.mark.parametrize("target", [Path("nowhere"), FORMER_DATA])
def test_a_link_at_the_new_data_directory_is_followed(home: Path, target: Path) -> None:
    """The run's data directory is where ``~/kb-mcp`` leads, named or not: nothing stops."""
    place(home, FORMER_DATA)
    (home / NEW_DATA).symlink_to(home / target)
    for flags in ({}, {"--data-dir": ("data_dir", str(home / NEW_DATA))}):
        load_settings(SETTINGS_PATH, flags, home)


def test_a_linked_settings_folder_still_holds_the_default(home: Path) -> None:
    """Rule 1 holds where ``~/.config`` is a link, as a manager of dotfiles makes it."""
    (home / "dotfiles").mkdir()
    (home / ".config").symlink_to(home / "dotfiles")
    place(home, FORMER_FILE)
    assert block(refusal(home).advice) == ["# Move the files:", FILE_MOVE]


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
        pytest.param(
            (NEW_FILE, NEW_DATA),
            {"KB_MCP_EMAIL": "me+atlassian-offline-mcp@example.invalid"},
            id="no path naming it",
        ),
        pytest.param(
            (NEW_FILE, NEW_DATA),
            {"KB_MCP_LOGS__DIR": "/srv/-home-src-atlassian-offline-mcp/scratch/logs"},
            id="a folder above holding the name",
        ),
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
    said = done.stderr.splitlines()
    assert done.returncode == ExitStatus.REFUSED
    assert "settings.refused" in done.stderr
    assert block(done.stderr) == ["# Move the files:", FILE_MOVE, DATA_MOVE]
    assert "ATLASSIAN_OFFLINE_MCP_SITE to KB_MCP_SITE" in said
    assert "Then, by hand, as docs/how-to/move-to-kb-mcp.md says:" in said
    assert (
        "- uv tool uninstall atlassian-offline-mcp, then uv tool install --force <checkout>" in said
    )
    assert "- Claude Code: claude mcp remove --scope user atlassian-offline-mcp, then" in said
    assert "  added again on ~/kb-mcp/docs/" in said
    assert "secret" not in done.stderr
    assert files(home) == before


@pytest.mark.parametrize("arguments", [["--help"], ["--version"], ["completion"]], ids=" ".join)
def test_what_reads_no_settings_never_stops(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], arguments: list[str]
) -> None:
    """``--help``, ``--version`` and ``completion`` read no settings: none of them stops."""
    place(home, FORMER_FILE)
    place(home, FORMER_DATA)
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", SITE)
    try:
        status = main(arguments)
    except SystemExit as stopped:
        status = stopped.code
    assert status == ExitStatus.OK
    assert "settings.refused" not in capsys.readouterr().err


def test_the_how_to_page_holds_every_line_the_stop_prints(
    home: Path, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """The page's sample is what the stop says, line for line, for a home holding all four."""
    place(home, FORMER_FILE)
    place(home, FORMER_DATA)
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", SITE)
    monkeypatch.setenv("KB_MCP_LOGS__DIR", str(tmp_path / "logs" / "atlassian-offline-mcp"))
    page = (ROOT / "docs" / "how-to" / "move-to-kb-mcp.md").read_text(encoding="utf-8")
    sample = re.search(r"```text\n(.*?)```", page, re.DOTALL)
    assert sample is not None
    assert refusal(home).advice.rstrip("\n") == sample[1].rstrip("\n")
