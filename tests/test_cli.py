"""Tests of the command: its subcommands, and ``check`` end to end in a scratch home."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli import options
from atlassian_offline_mcp.cli.main import main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

# The exit status for settings refused before acting, an unsafe data directory included.
BAD_SETTINGS = 2
# What a run may import and declaring the command must not, by plan 015: --help and each
# completion build the whole parser, so they must start fast.
RUNS_PACKAGES = frozenset(
    {
        "httpx",
        "lxml",
        "mcp",
        "numpy",
        "opentelemetry",
        "platformdirs",
        "playwright",
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
        "rich",
        "structlog",
        "yaml",
    }
)
# A subcommand's declaration, which names its run, a module of its own.
DECLARED = """
from pathlib import Path

from atlassian_offline_mcp.cli.domain.command import Command

def register(subparsers):
    parser = subparsers.add_parser("extra", help="a command added by a module pair")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-dir")
    parser.set_defaults(command=Command("extra_run", {"data_dir": "data_dir"}))
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, so that none reads or writes the user's."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    return scratch


@pytest.fixture
def extra(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[Path]:
    """Declare ``extra`` among the options, with its run to be written in the folder given.

    A module whose name begins with _ is put beside it: it is shared, not a subcommand.
    """
    declarations = tmp_path / "declarations"
    declarations.mkdir()
    (declarations / "extra.py").write_text(DECLARED, "utf-8")
    (declarations / "_shared.py").write_text("SHARED = True\n", "utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(options, "__path__", [*options.__path__, str(declarations)])
    monkeypatch.syspath_prepend(str(runs))
    yield runs
    sys.modules.pop(f"{options.__name__}.extra", None)
    sys.modules.pop("extra_run", None)


def test_a_module_pair_makes_a_subcommand(
    home: Path, extra: Path, capsys: CaptureFixture[str]
) -> None:
    """--help offers the declared subcommand, and its run gets the settings its flags set."""
    (extra / "extra_run.py").write_text(
        "import sys\n"
        "def run(arguments, settings):\n"
        "    sys.stdout.write(f'ran in {settings.data_dir}\\n')\n"
        "    return 0\n",
        "utf-8",
    )
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    out = capsys.readouterr().out
    assert "check" in out
    assert "a command added by a module pair" in out
    data = home / "data"
    assert main(["extra", "--config", str(home / "none.toml"), "--data-dir", str(data)]) == 0
    assert capsys.readouterr().out == f"ran in {data.resolve()}\n"


def test_refused_settings_exit_before_the_run_is_imported(
    home: Path, extra: Path, capsys: CaptureFixture[str]
) -> None:
    """A run that would not even import is never reached when the settings are refused."""
    assert not (extra / "extra_run.py").exists()
    config = home / "config.toml"
    config.write_text('sight = "https://example.atlassian.net"\n', "utf-8")
    assert main(["extra", "--config", str(config)]) == BAD_SETTINGS
    assert "unknown setting: sight" in capsys.readouterr().err


def test_declaring_the_command_imports_none_of_the_runs_packages(home: Path) -> None:
    """--help, and a subcommand's, build the whole parser and import no run.

    ``-X importtime`` names each module that the child imports, so a package it does not
    name never reached ``sys.modules``.
    """
    environment = {"HOME": str(home), "PATH": os.environ["PATH"]}
    children = (
        subprocess.run(
            [sys.executable, "-X", "importtime", "-m", "atlassian_offline_mcp", "--help"],
            capture_output=True,
            text=True,
            env=environment,
            cwd=home,
            check=False,
        ),
        subprocess.run(
            [
                sys.executable,
                "-X",
                "importtime",
                "-m",
                "atlassian_offline_mcp",
                "download",
                "--help",
            ],
            capture_output=True,
            text=True,
            env=environment,
            cwd=home,
            check=False,
        ),
    )
    for child in children:
        assert child.returncode == 0
        assert child.stdout.startswith("usage: atlassian-offline-mcp")
        imported = {
            line.rsplit("|", 1)[-1].strip().split(".")[0]
            for line in child.stderr.splitlines()
            if line.startswith("import time:")
        }
        assert {"argparse", "atlassian_offline_mcp"} <= imported
        assert not imported & RUNS_PACKAGES


def test_check_accepts_a_plain_data_directory(home: Path, capsys: CaptureFixture[str]) -> None:
    """Valid settings and a safe directory exit 0 and are shown."""
    config = home / "config.toml"
    config.write_text('site = "https://example.atlassian.net"\nspaces = ["ENG"]\n', "utf-8")
    assert main(["check", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "site: https://example.atlassian.net" in out
    assert f"data directory: {(home / 'atlassian-offline-mcp').resolve()}" in out


@pytest.mark.parametrize(
    ("data_dir", "reason"),
    [
        ("~/Library/CloudStorage/Box/mirror", "under ~/Library/CloudStorage"),
        ("~/Dropbox/mirror", "under a Dropbox folder"),
        ("~/project/data", "inside the git working tree"),
        ("~/elsewhere/../Documents/mirror", "under ~/Documents"),
        ("~/linked/data", "inside the git working tree"),
        ("~/work/data", "under a Dropbox folder"),
        ("~/checkout/data", "inside the git working tree"),
    ],
)
def test_check_refuses_a_data_directory_that_could_leave_the_machine(
    home: Path, data_dir: str, reason: str, capsys: CaptureFixture[str]
) -> None:
    """A synchronised folder or a git working tree exits 2, naming the reason.

    The path is judged once resolved, so neither ``..`` nor a link hides where it leads.
    """
    (home / "project" / ".git").mkdir(parents=True)
    (home / "linked").symlink_to(home / "project")
    (home / "Dropbox (Personal)" / "x").mkdir(parents=True)
    (home / "work").symlink_to(home / "Dropbox (Personal)" / "x")
    (home / "checkout").mkdir()
    (home / "checkout" / ".git").write_text("gitdir: elsewhere\n", "utf-8")  # a worktree
    assert (
        main(["check", "--config", str(home / "none.toml"), "--data-dir", data_dir]) == BAD_SETTINGS
    )
    error = capsys.readouterr().err
    assert error.startswith("settings refused: data_dir: ")
    assert reason in error


def test_check_refuses_bad_settings_by_name(home: Path, capsys: CaptureFixture[str]) -> None:
    """A settings file with an unknown key exits 2, naming it."""
    config = home / "config.toml"
    config.write_text('sight = "https://example.atlassian.net"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    assert "unknown setting: sight" in capsys.readouterr().err


def test_check_refuses_a_file_that_is_not_toml(home: Path, capsys: CaptureFixture[str]) -> None:
    """A broken settings file is refused rather than ignored."""
    config = home / "config.toml"
    config.write_text("site = ", "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    assert "not a TOML file" in capsys.readouterr().err


def test_check_refuses_a_part_of_the_data_directory_that_leads_elsewhere(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A link from <data>/docs into a synchronised folder is refused, naming docs."""
    (home / "Dropbox" / "shared").mkdir(parents=True)
    (home / "atlassian-offline-mcp").mkdir()
    (home / "atlassian-offline-mcp" / "docs").symlink_to(home / "Dropbox" / "shared")
    assert main(["check", "--config", str(home / "none.toml")]) == BAD_SETTINGS
    assert "data_dir: docs: under a Dropbox folder" in capsys.readouterr().err


def test_check_refuses_a_raw_store_that_leads_into_a_git_tree(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A link from <data>/raw into a working tree is refused, naming raw."""
    (home / "project" / ".git").mkdir(parents=True)
    (home / "atlassian-offline-mcp").mkdir()
    (home / "atlassian-offline-mcp" / "raw").symlink_to(home / "project")
    assert main(["check", "--config", str(home / "none.toml")]) == BAD_SETTINGS
    assert "data_dir: raw: inside the git working tree" in capsys.readouterr().err


def test_check_refuses_a_settings_file_it_cannot_read(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A folder where the settings file should be is refused, not a traceback."""
    (home / "config.toml").mkdir()
    assert main(["check", "--config", str(home / "config.toml")]) == BAD_SETTINGS
    assert "not readable" in capsys.readouterr().err


def test_a_flag_overrides_the_settings_file(home: Path, capsys: CaptureFixture[str]) -> None:
    """--data-dir wins over the file's data_dir."""
    config = home / "config.toml"
    config.write_text('data_dir = "~/from-file"\n', "utf-8")
    assert main(["check", "--config", str(config), "--data-dir", "~/from-flag"]) == 0
    assert f"data directory: {(home / 'from-flag').resolve()}" in capsys.readouterr().out
