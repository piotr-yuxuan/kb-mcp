"""A run that finds what the former name left stops before acting and says how to move it.

The rules are plan 027's: the former settings file in place of a missing default, the
former data directory where the default is used and missing, a variable of the former
prefix, and a path setting with a folder or file named after the former name. Every test
builds the former places in its scratch home; none is ever moved. By plan 030, the stop
names each setting by its final name, the sign-in's in ``[accounts.atlassian]``: a key
of the former file, and a variable, the former prefix's or 027's own.
"""

from __future__ import annotations

import json
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
from kb_mcp.config.domain.former_name import BY_HAND, FormerNameError
from kb_mcp.config.domain.settings import SettingsError
from kb_mcp.kernel.exit_status import ExitStatus
from tests.composed import MODEL

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
# The site's variable since plan 030, in the Atlassian account's table.
SITE_VARIABLE = "KB_MCP_ACCOUNTS__ATLASSIAN__SITE"
# The former settings file of a machine that signs in, as the user's machine's: its site and
# its email at its top, where plan 030 moved them from.
SIGNING_IN = f'site = "{SITE}"\nemail = "someone@secret.example.invalid"\n'
KEYS = [
    "Rename each key of the settings file:",
    "site to accounts.atlassian.site",
    "email to accounts.atlassian.email",
]
# A token at the top of a former file: no file may hold it, so it is not renamed to a key.
NOT_RENAMED = (
    "api_token: delete it, and set KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN in the environment"
)
# The page that says the same as the stop, line for line.
PAGE = ROOT / "docs" / "how-to" / "move-to-kb-mcp.md"


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
        load_settings(path, flags or {}, home, MODEL)
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
        ("ATLASSIAN_OFFLINE_MCP_SITE", SITE_VARIABLE),
        ("atlassian_offline_mcp_site", SITE_VARIABLE),
        ("ATLASSIAN_OFFLINE_MCP_API_TOKEN", "KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN"),
        ("ATLASSIAN_OFFLINE_MCP_LOGS__DIR", "KB_MCP_LOGS__DIR"),
    ],
)
def test_a_former_variable_is_renamed_and_its_value_never_shown(
    home: Path, monkeypatch: MonkeyPatch, name: str, renamed: str
) -> None:
    """Rule 3, in any case: the variable and its final name, with no move to make."""
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


@pytest.mark.parametrize(
    "given",
    [
        pytest.param(FORMER_FILE, id="the former file"),
        pytest.param(Path("atlassian-offline-mcp.toml"), id="relative, named after it"),
    ],
)
def test_a_settings_file_given_by_a_former_path_is_named(
    home: Path, monkeypatch: MonkeyPatch, given: Path
) -> None:
    """Rule 4 judges the settings file given, as written, which a script may still name."""
    place(home, given)
    monkeypatch.chdir(home)
    for path in (given, home / given):
        advice = refusal(home, path).advice
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
    monkeypatch.setenv(SITE_VARIABLE, "")
    assert f"ATLASSIAN_OFFLINE_MCP_SITE to {SITE_VARIABLE}" in refusal(home).advice.splitlines()


def test_plan_027_s_name_of_the_site_is_not_its_final_one(
    home: Path, monkeypatch: MonkeyPatch
) -> None:
    """Set beside the former one, ``KB_MCP_SITE`` is not the site's: the stop still names it."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", SITE)
    monkeypatch.setenv("KB_MCP_SITE", SITE)
    assert f"ATLASSIAN_OFFLINE_MCP_SITE to {SITE_VARIABLE}" in refusal(home).advice.splitlines()


@pytest.mark.parametrize("name", ["KB_MCP_SITE", "KB_MCP_EMAIL", "KB_MCP_API_TOKEN"])
def test_plan_027_s_names_of_the_sign_in_name_no_setting_and_are_said(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], name: str
) -> None:
    """Criterion 5 of plan 030: ignored and said, as plan 036 rules for its own; never read."""
    monkeypatch.setenv(name, SITE)
    options = ["check", "--config", str(home / "none.toml"), "--format", "json"]
    assert main(options) == ExitStatus.OK
    out, err = capsys.readouterr()
    assert json.loads(out)["layers"] == {}
    assert err == f"ignored: {name}: names no setting\n"


@pytest.mark.parametrize("target", [Path("nowhere"), FORMER_DATA])
def test_a_link_at_the_new_data_directory_is_followed(home: Path, target: Path) -> None:
    """The run's data directory is where ``~/kb-mcp`` leads, named or not: nothing stops."""
    place(home, FORMER_DATA)
    (home / NEW_DATA).symlink_to(home / target)
    for flags in ({}, {"--data-dir": ("data_dir", str(home / NEW_DATA))}):
        load_settings(SETTINGS_PATH, flags, home, MODEL)


def test_a_data_directory_given_through_a_link_into_the_former_folder_is_named(
    home: Path, monkeypatch: MonkeyPatch
) -> None:
    """Rule 4 judges where a data directory given leads: the move would strand it."""
    place(home, FORMER_DATA)
    (home / "mirror").symlink_to(home / FORMER_DATA)
    monkeypatch.setenv("KB_MCP_DATA_DIR", str(home / "mirror"))
    advice = refusal(home).advice
    assert "data_dir (KB_MCP_DATA_DIR)" in advice.splitlines()
    assert block(advice) == []


def test_a_linked_settings_folder_still_holds_the_default(home: Path) -> None:
    """Rule 1 holds where ``~/.config`` is a link, as a manager of dotfiles makes it."""
    (home / "dotfiles").mkdir()
    (home / ".config").symlink_to(home / "dotfiles")
    place(home, FORMER_FILE)
    assert block(refusal(home).advice) == ["# Move the files:", FILE_MOVE]


def test_the_former_file_is_judged_in_place_of_the_missing_one(home: Path) -> None:
    """A former file naming the former data directory: its move, and its key to change.

    The key's layer is the former file, by its path, which plan 030 names.
    """
    place(home, FORMER_FILE, 'data_dir = "~/atlassian-offline-mcp"\n')
    place(home, FORMER_DATA)
    advice = refusal(home).advice
    assert block(advice) == ["# Move the files:", FILE_MOVE]
    assert "data_dir (~/.config/atlassian-offline-mcp/config.toml)" in advice.splitlines()


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
            {"ATLASSIAN_OFFLINE_MCP_SITE": SITE, SITE_VARIABLE: SITE},
            id="variable renamed already",
        ),
        pytest.param((NEW_FILE, FORMER_DATA / ".git"), {}, id="former data in git"),
        pytest.param(
            (NEW_FILE, NEW_DATA),
            {"KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL": "me+atlassian-offline-mcp@example.invalid"},
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
    load_settings(SETTINGS_PATH, {}, home, MODEL)
    assert files(home) == before


def test_a_run_given_other_places_goes_on(home: Path, tmp_path: Path) -> None:
    """A settings file and a data directory given, as the sandbox's: the former are not used."""
    place(home, FORMER_FILE)
    place(home, FORMER_DATA)
    before = files(home)
    flags = {"--data-dir": ("data_dir", str(tmp_path / "data"))}
    load_settings(tmp_path / "none.toml", flags, home, MODEL)
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
    assert f"ATLASSIAN_OFFLINE_MCP_SITE to {SITE_VARIABLE}" in said
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
    """The page's sample is what the stop says, line for line, for a home holding all four.

    Its former settings file holds the site and the email at its top, as the user's machine's.
    """
    place(home, FORMER_FILE, SIGNING_IN)
    place(home, FORMER_DATA)
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", SITE)
    monkeypatch.setenv("KB_MCP_LOGS__DIR", str(tmp_path / "logs" / "atlassian-offline-mcp"))
    sample = re.search(r"```text\n(.*?)```", PAGE.read_text(encoding="utf-8"), re.DOTALL)
    assert sample is not None
    assert refusal(home).advice.rstrip("\n") == sample[1].rstrip("\n")


def check(home: Path) -> tuple[int, list[str]]:
    """Run ``kb-mcp check`` in a home of its own; give its status and its stderr's lines.

    The first line, the event ``settings.refused``, is left out.
    """
    done = subprocess.run(
        [sys.executable, "-m", "kb_mcp", "check"],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    event, *said = done.stderr.splitlines()
    assert "settings.refused" in event
    return done.returncode, said


def test_the_former_file_s_site_and_email_are_named_by_their_keys_now(tmp_path: Path) -> None:
    """Criterion 5 of plan 030: the stop, not the refusal of a moved key.

    With the former settings file alone under the home, holding the site and the email
    at its top: exit 2, the file's move and each key's final name, never a value, each
    line on the page; the stop gives the advice, so no refusal names a moved key.
    """
    home = tmp_path / "home"
    place(home, FORMER_FILE, SIGNING_IN)
    status, said = check(home)
    assert status == ExitStatus.REFUSED
    assert block("\n".join(said)) == ["# Move the files:", FILE_MOVE]
    assert said[3:6] == KEYS
    assert "secret" not in "\n".join(said)
    page = PAGE.read_text(encoding="utf-8").splitlines()
    assert [line for line in said if line and line not in page] == []


def test_the_former_file_s_keys_are_named_whatever_replaces_their_values(
    home: Path, monkeypatch: MonkeyPatch
) -> None:
    """A stronger layer replaces the site, not the key that the file holds: still named."""
    place(home, FORMER_FILE, SIGNING_IN)
    monkeypatch.setenv(SITE_VARIABLE, SITE)
    advice = refusal(home, flags={"--site": ("accounts.atlassian.site", SITE)}).advice
    assert advice.splitlines()[3:6] == KEYS


def test_a_value_that_the_former_file_holds_and_a_setting_refuses_names_the_file(
    home: Path,
) -> None:
    """Refused before the stop judges, by the former file's path: not by the new file's name."""
    place(home, FORMER_FILE, 'search_mode = "fast"\n')
    with pytest.raises(SettingsError) as refused:
        load_settings(SETTINGS_PATH, {}, home, MODEL)
    assert str(refused.value).startswith(
        "search_mode (~/.config/atlassian-offline-mcp/config.toml): "
    )


def test_a_token_at_the_top_of_the_former_file_is_named_by_its_variable(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Followed, the advice leads to a run that goes on: no file may hold a secret.

    Renaming it to its table would meet the next refusal, of a secret in a file. Never its
    value; its line is on the page.
    """
    place(home, FORMER_FILE, f'{SIGNING_IN}api_token = "{SITE}"\n')
    advice = refusal(home).advice.splitlines()
    assert advice[3:7] == [*KEYS, NOT_RENAMED]
    assert SITE not in "\n".join(advice)
    assert NOT_RENAMED in PAGE.read_text(encoding="utf-8").splitlines()

    place(home, FORMER_FILE, f'api_token = "{SITE}"\n')
    assert main(["check"]) == ExitStatus.REFUSED
    assert NOT_RENAMED in capsys.readouterr().err.splitlines()


def test_a_former_file_given_by_its_path_holding_the_site_gets_the_stop_s_advice(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """An MCP client's entry may pass it: the stop's advice, not the refusal of a moved key.

    Rule 4 names the file given, and its keys renamed since are named, as of rule 1's
    file, whichever folder holds it; no file need be under the former default.
    """
    where = Path("other/atlassian-offline-mcp/config.toml")
    place(home, where, SIGNING_IN)
    assert main(["check", "--config", str(home / where)]) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    said = err.splitlines()
    assert said[1:4] == KEYS
    assert "the settings file (--config)" in said
    assert [line for line in BY_HAND if line not in said] == []
    assert "moved, as" not in err
    assert SITE not in err


def test_a_token_in_a_file_given_under_the_former_name_is_named_by_its_variable(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Rule 4's file as rule 1's: its token too is left unread, and named."""
    where = Path("atlassian-offline-mcp.toml")
    place(home, where, f'api_token = "{SITE}"\n')
    assert main(["check", "--config", str(home / where)]) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert NOT_RENAMED in err.splitlines()
    assert "a secret, read from" not in err
    assert SITE not in err


def test_an_empty_former_file_stops_as_before_plan_030(tmp_path: Path) -> None:
    """Nothing to rename: the move and what is done by hand alone, as plan 027 printed them."""
    home = tmp_path / "home"
    place(home, FORMER_FILE)
    status, said = check(home)
    assert status == ExitStatus.REFUSED
    assert said == [
        "# Move the files:",
        FILE_MOVE,
        "",
        "Then, by hand, as docs/how-to/move-to-kb-mcp.md says:",
        *BY_HAND,
        "",
    ]


def test_a_file_that_the_stop_leaves_alone_is_refused_its_site_at_its_top(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 015's refusal of a moved key, with its table now: the new file is never renamed."""
    place(home, FORMER_FILE, SIGNING_IN)
    place(home, NEW_FILE, f'site = "{SITE}"\n')
    assert main(["check"]) == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert "site (config.toml): moved, as site under [accounts.atlassian]" in err
    assert "Rename each key" not in err
