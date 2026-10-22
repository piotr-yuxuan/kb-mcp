"""Tests of the command: its subcommands, and ``check`` end to end in a scratch home."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pty
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, override

import argcomplete
import pytest

from atlassian_offline_mcp.cli import commands, options
from atlassian_offline_mcp.cli.main import main, parser
from atlassian_offline_mcp.config.domain.settings import SETTING_PATHS
from atlassian_offline_mcp.kernel.exit_status import MEANINGS, ExitStatus
from atlassian_offline_mcp.kernel.output import Output
from tests.test_question import read_until
from tests.test_settings import user_log_folder

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from atlassian_offline_mcp.kernel.output import Level

ROOT = Path(__file__).parents[1]
# The exit status for what is refused before acting: options, and settings, an unsafe data
# directory included.
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
# What other runs import and ``completion`` must not, by plan 015: a command loads only
# its own code, and shells run this one at each start. The entry loads pydantic for all.
OTHER_RUNS_PACKAGES = frozenset({"httpx", "mcp", "numpy", "playwright"})
# A subcommand's declaration, which names its run, a module of its own.
DECLARED = """
from pathlib import Path

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import add_output_options

def register(subparsers):
    parser = subparsers.add_parser("extra", help="a command added by a module pair")
    config = parser.add_argument("--config", type=Path)
    where = parser.add_argument("--where", dest="data_dir")
    add_output_options(parser)
    parser.set_defaults(
        command=Command(
            "extra",
            "extra_run",
            reads=("data_dir",),
            flags={"data_dir": "data_dir"},
            actions=(config, where),
        )
    )
"""


class Declaring(argparse.ArgumentParser):
    """A parser that keeps its subcommands' parsers by name, which argparse holds privately."""

    subcommands: dict[str, argparse.ArgumentParser]

    @override
    def add_subparsers(
        self, **keywords: object
    ) -> argparse._SubParsersAction[argparse.ArgumentParser]:
        declared = super().add_subparsers(**keywords)
        self.subcommands = declared.choices
        return declared


# Every setting but a table, by its path, its names joined by dots.
SETTINGS = {".".join(path) for path, kind in SETTING_PATHS.items() if kind != "table"}
# Every subcommand that the command declares, by the name it is typed by.
SUBCOMMANDS = parser(Declaring).subcommands
# What a subcommand needs besides its options to be parsed: its positional arguments.
POSITIONALS = {"eval": ["golden.yaml"], "model": ["check"]}
# The subcommands whose output is their own, by plan 015: the protocol, a script.
OWN_OUTPUT = {"serve", "completion"}
# The subcommands that write under the data directory, and so ask first, by plan 015.
WRITING = {"download", "eval", "index", "login", "mirror"}
SECRETS = {
    "ATLASSIAN_OFFLINE_MCP_API_TOKEN": "token-sentinel-4d1c",
    "ATLASSIAN_OFFLINE_MCP_EMBEDDING_API_KEY": "key-sentinel-9a7e",
}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, so that none reads or writes the user's.

    The user's log folder is under it, as ``XDG_STATE_HOME`` is removed.
    """
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
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
    """--help offers the declared subcommand, and its run gets the settings its flags set.

    A flag's layer is its option, whatever its ``dest``.
    """
    (extra / "extra_run.py").write_text(
        "def run(arguments, loaded):\n"
        "    return 0, (loaded.settings.data_dir, loaded.layer('data_dir'))\n"
        "def text(given, summary):\n"
        "    return f'ran in {given[0]} [{given[1]}]\\n'\n",
        "utf-8",
    )
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    out = capsys.readouterr().out
    assert "check" in out
    assert "a command added by a module pair" in out
    data = home / "data"
    assert main(["extra", "--config", str(home / "none.toml"), "--where", str(data)]) == 0
    assert capsys.readouterr().out == f"ran in {data.resolve()} [--where]\n"


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_each_subcommand_s_command_carries_its_name_and_a_run_that_imports(name: str) -> None:
    """The name typed, and a module of ``cli.commands`` with a ``run`` and a declaration.

    The run's module need not bear the name: eval's is evaluate. It is named by a
    string and imported only once chosen, so a misspelt one would fail only when run.
    Its declaration, in ``cli.options``, bears the same module's name.
    """
    command = SUBCOMMANDS[name].get_default("command")
    assert command.name == name
    package, _, module = command.run.rpartition(".")
    assert package == commands.__name__
    assert callable(importlib.import_module(command.run).run)
    assert callable(importlib.import_module(f"{options.__name__}.{module}").register)


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_each_subcommand_reads_settings_by_their_paths_and_declares_each_flag(name: str) -> None:
    """What it reads and what its flags set are settings; each flag is one of its options.

    A misspelt path would read nothing, and a flag missing from its actions would
    override nothing.
    """
    command = SUBCOMMANDS[name].get_default("command")
    assert set(command.reads) <= SETTINGS
    assert set(command.flags.values()) <= SETTINGS
    named = command.setting_flags()
    assert set(named) == set(command.flags)
    assert all(option.startswith("--") for option, _ in named.values())


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_the_commands_that_write_take_yes_and_download_alone_a_dry_run(name: str) -> None:
    """They ask first, as plan 015 lists them; check, doctor, model and serve never do."""
    command = SUBCOMMANDS[name].get_default("command")
    arguments = parser().parse_args([name, *POSITIONALS.get(name, [])])
    assert command.writes is (name in WRITING)
    assert hasattr(arguments, "yes") is command.writes
    assert command.dry_run is (name == "download")
    assert hasattr(arguments, "dry_run") is command.dry_run


def test_check_reads_every_setting() -> None:
    """It shows them all, so a setting added to the model must be added to its reads."""
    assert set(SUBCOMMANDS["check"].get_default("command").reads) == SETTINGS


def test_refused_settings_exit_before_the_run_is_imported(
    home: Path, extra: Path, capsys: CaptureFixture[str]
) -> None:
    """A run that would not even import is never reached when the settings are refused."""
    assert not (extra / "extra_run.py").exists()
    config = home / "config.toml"
    config.write_text('sight = "https://example.atlassian.net"\n', "utf-8")
    assert main(["extra", "--config", str(config)]) == BAD_SETTINGS
    assert "sight (config.toml): not a setting" in capsys.readouterr().err


def test_the_version_is_the_project_s(capsys: CaptureFixture[str]) -> None:
    """--version prints the program's name and the version that the project declares."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out == f"atlassian-offline-mcp {project['version']}\n"


def test_the_help_says_who_asks_and_what_each_exit_status_means() -> None:
    """The commands that write ask first, by name; every status of the one enum is listed.

    The help is read with its lines joined, as its width follows the terminal's.
    """
    said = " ".join(parser().format_help().split())
    assert f"write under the data directory ({', '.join(sorted(WRITING))})" in said
    assert "then ask" in said
    for status in ExitStatus:
        assert f"{status.value} {MEANINGS[status]}" in said


@pytest.mark.parametrize("name", sorted(set(SUBCOMMANDS) - OWN_OUTPUT))
def test_the_help_of_each_subcommand_with_a_result_says_what_its_json_holds(name: str) -> None:
    """Plan 020 writes the reference of the commands from their help."""
    assert "With --format json:" in SUBCOMMANDS[name].format_help()


@pytest.mark.parametrize(("variables", "coloured"), [({"NO_COLOR": "1"}, False), ({}, True)])
def test_the_help_on_a_terminal_has_no_colour_under_no_color(
    home: Path, variables: dict[str, str], *, coloured: bool
) -> None:
    """On a pseudo-terminal, --help has no escape byte under NO_COLOR, which argparse honours.

    Without it, the same child's help is coloured: the terminal would show colour.
    """
    controller, terminal = pty.openpty()
    with subprocess.Popen(
        [sys.executable, "-m", "atlassian_offline_mcp", "--help"],
        stdin=subprocess.DEVNULL,
        stdout=terminal,
        stderr=terminal,
        env={"HOME": str(home), "PATH": os.environ["PATH"], **variables},
        cwd=home,
    ) as child:
        os.close(terminal)
        said = read_until(controller, b"\0")
    os.close(controller)
    assert child.returncode == 0
    assert b"Exit statuses" in said
    assert (b"\x1b" in said) is coloured


def test_declaring_the_command_imports_none_of_the_runs_packages(home: Path) -> None:
    """--version, --help, a subcommand's and a completion import no run; ``completion`` its own.

    Each builds the whole parser. ``-X importtime`` names each module that the child
    imports, so a package it does not name never reached ``sys.modules``.
    """
    environment = {"HOME": str(home), "PATH": os.environ["PATH"]}
    typed = "atlassian-offline-mcp download --sp"
    completing = {
        "_ARGCOMPLETE": "1",
        "COMP_LINE": typed,
        "COMP_POINT": str(len(typed)),
        "_ARGCOMPLETE_STDOUT_FILENAME": str(home / "completions"),
    }
    # Only --version reads the package's metadata, which costs as much as the parser.
    parser_refused = RUNS_PACKAGES | {"importlib.metadata"}
    children = (
        (
            subprocess.run(
                [sys.executable, "-X", "importtime", "-m", "atlassian_offline_mcp", "--version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=environment,
                cwd=home,
                check=False,
            ),
            RUNS_PACKAGES,
        ),
        (
            subprocess.run(
                [sys.executable, "-X", "importtime", "-m", "atlassian_offline_mcp", "--help"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=environment,
                cwd=home,
                check=False,
            ),
            parser_refused,
        ),
        (
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
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=environment,
                cwd=home,
                check=False,
            ),
            parser_refused,
        ),
        (
            subprocess.run(
                [sys.executable, "-X", "importtime", "-m", "atlassian_offline_mcp"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env={**environment, **completing},
                cwd=home,
                check=False,
            ),
            parser_refused,
        ),
        (
            subprocess.run(
                [sys.executable, "-X", "importtime", "-m", "atlassian_offline_mcp", "completion"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=environment,
                cwd=home,
                check=False,
            ),
            OTHER_RUNS_PACKAGES,
        ),
    )
    assert (home / "completions").read_text("utf-8").strip() == "--space"
    for child, refused in children:
        assert child.returncode == 0
        imported = {
            line.rsplit("|", 1)[-1].strip()
            for line in child.stderr.splitlines()
            if line.startswith("import time:")
        }
        imported |= {module.split(".")[0] for module in imported}
        assert {"argparse", "atlassian_offline_mcp"} <= imported
        assert not imported & refused


@pytest.mark.parametrize(
    ("line", "offered"),
    [("dow", {"download"}), ("download --sp", {"--space"}), ("check --format ", {"text", "json"})],
)
def test_the_shell_completes_the_command_line(home: Path, line: str, offered: set[str]) -> None:
    """A child called as the shell code calls it offers what may follow the line.

    That is argcomplete's protocol: the line and the cursor in the environment, the
    completions, separated by vertical tabs, in the file it names.
    """
    typed = f"atlassian-offline-mcp {line}"
    environment = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "_ARGCOMPLETE": "1",
        "COMP_LINE": typed,
        "COMP_POINT": str(len(typed)),
        "_ARGCOMPLETE_STDOUT_FILENAME": str(home / "completions"),
    }
    child = subprocess.run(
        [sys.executable, "-m", "atlassian_offline_mcp"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
        cwd=home,
        check=False,
    )
    assert child.returncode == 0
    completions = (home / "completions").read_text("utf-8").split("\v")
    assert {completion.strip() for completion in completions} == offered


def test_completion_prints_the_shell_code_whatever_the_settings(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """``completion`` prints argcomplete's code for bash and zsh, and reads no settings."""
    (home / ".config" / "atlassian-offline-mcp").mkdir(parents=True)
    (home / ".config" / "atlassian-offline-mcp" / "config.toml").write_text("site = ", "utf-8")
    assert main(["completion"]) == 0
    assert capsys.readouterr().out == argcomplete.shellcode(["atlassian-offline-mcp"])


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
@pytest.mark.parametrize(
    ("given", "level"),
    [
        ([], "warning"),
        (["-v"], "info"),
        (["-vv"], "debug"),
        (["-v", "-v", "-v"], "debug"),
        (["-q"], "error"),
        *((["--log-level", named], named) for named in ("debug", "info", "warning", "error")),
    ],
)
def test_every_subcommand_takes_the_level_its_options_name(
    name: str, given: list[str], level: str
) -> None:
    """Warning by default, info with -v, debug from -vv on, error with -q, else as named."""
    assert parser().parse_args([name, *given, *POSITIONALS.get(name, [])]).level == level


@pytest.mark.parametrize("level", ["debug", "info", "warning"])
def test_quiet_is_at_the_level_error_alone(level: Level) -> None:
    """-q sets the level error, so that a run quiet at another level is a mistake."""
    with pytest.raises(ValueError, match="-q sets the level error"):
        Output(level, "short", "text", quiet=True, stdin_terminal=False, stderr_terminal=False)


@pytest.mark.parametrize(
    "given",
    [["-q", "-v"], ["-v", "-q"], ["-q", "--log-level", "info"], ["-vv", "--log-level", "debug"]],
)
def test_the_level_options_exclude_one_another(
    home: Path, given: list[str], capsys: CaptureFixture[str]
) -> None:
    """Two of -q, -v and --log-level: refused by the parser, exit 2, before any settings."""
    config = home / "config.toml"
    config.write_text("site = ", "utf-8")
    with pytest.raises(SystemExit) as stopped:
        main(["check", "--config", str(config), *given])
    assert stopped.value.code == BAD_SETTINGS
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("name", sorted(set(SUBCOMMANDS) - OWN_OUTPUT))
def test_every_subcommand_with_a_result_takes_its_format_and_summary(name: str) -> None:
    """Text and short by default; JSON and detailed when asked."""
    positionals = POSITIONALS.get(name, [])
    defaults = parser().parse_args([name, *positionals])
    assert (defaults.format, defaults.summary) == ("text", "short")
    asked = parser().parse_args([name, "--format", "json", "--summary", "detailed", *positionals])
    assert (asked.format, asked.summary) == ("json", "detailed")


@pytest.mark.parametrize("name", sorted(OWN_OUTPUT))
def test_serve_and_completion_take_no_format_nor_summary(
    name: str, capsys: CaptureFixture[str]
) -> None:
    """Their output is their own: the protocol, the script."""
    with pytest.raises(SystemExit) as stopped:
        parser().parse_args([name, "--format", "json", "--summary", "detailed"])
    assert stopped.value.code == BAD_SETTINGS
    assert "unrecognized arguments: --format json --summary detailed" in capsys.readouterr().err


def test_check_quiet_prints_nothing_but_still_its_document(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """-q leaves a result as text unwritten, a site given too; one in JSON is written still."""
    site = "https://quiet.example.invalid"
    options = ["check", "--config", str(home / "none.toml"), "--site", site, "-q"]
    assert main(options) == 0
    assert capsys.readouterr() == ("", "")
    assert main([*options, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["layers"] == {"site": "--site"}


@pytest.mark.parametrize(
    "level",
    [*(["--log-level", named] for named in ("debug", "info", "warning", "error")), ["-v"], ["-vv"]],
)
def test_a_level_leaves_check_s_listing_as_the_default_writes_it(
    home: Path, level: list[str], capsys: CaptureFixture[str]
) -> None:
    """The level is of what is said on stderr, as Unix has it: only -q leaves stdout empty."""
    site = "https://loud.example.invalid"
    options = ["check", "--config", str(home / "none.toml"), "--site", site]
    assert main(options) == 0
    default = capsys.readouterr()
    assert default.out == f"site: {site}\n"
    assert main([*options, *level]) == 0
    assert capsys.readouterr() == default


def test_check_as_json_gives_settings_layers_and_ignored_values_secrets_masked(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """One document: the settings, each one's layer, what was ignored; never a secret's value."""
    config = home / "config.toml"
    config.write_text(
        'site = "https://file.example.invalid"\n[sources.confluence]\nspaces = ["ENG"]\n', "utf-8"
    )
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", "https://variable.example.invalid")
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SPACES", '["X"]')
    for summary in ("short", "detailed"):
        options = ["--config", str(config), "--summary", summary, "--format", "json"]
        assert main(["check", *options]) == 0
        out = capsys.readouterr().out
        assert not any(secret in out for secret in SECRETS.values())
        document = json.loads(out)
        settings = document["settings"]
        assert settings["site"] == "https://variable.example.invalid"
        assert settings["data_dir"] == str((home / "atlassian-offline-mcp").resolve())
        assert settings["sources"]["confluence"]["spaces"] == ["ENG"]
        assert settings["api_token"]
        assert settings["embedding_api_key"]
        assert document["layers"] == {
            "site": "ATLASSIAN_OFFLINE_MCP_SITE",
            "sources.confluence.spaces": "config.toml",
            "api_token": "ATLASSIAN_OFFLINE_MCP_API_TOKEN",
            "embedding_api_key": "ATLASSIAN_OFFLINE_MCP_EMBEDDING_API_KEY",
        }
        assert sorted(document["ignored"], key=lambda ignored: ignored["layer"]) == [
            {"setting": None, "layer": "ATLASSIAN_OFFLINE_MCP_SPACES", "why": "names no setting"},
            {
                "setting": "site",
                "layer": "config.toml",
                "why": "replaced by ATLASSIAN_OFFLINE_MCP_SITE",
            },
        ]


def test_check_accepts_a_plain_data_directory(home: Path, capsys: CaptureFixture[str]) -> None:
    """Valid settings and a safe directory exit 0; in short, the settings given are shown."""
    config = home / "config.toml"
    config.write_text(
        'site = "https://example.atlassian.net"\n[sources.confluence]\nspaces = ["ENG"]\n',
        "utf-8",
    )
    assert main(["check", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert out == "site: https://example.atlassian.net\nsources.confluence.spaces: ENG\n"
    assert main(["check", "--config", str(config), "--summary", "detailed"]) == 0
    data = (home / "atlassian-offline-mcp").resolve()
    assert f"data_dir: {data} [default]\n" in capsys.readouterr().out


def test_check_in_short_shows_each_setting_given_and_its_value(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """From any layer, by its path; a secret said to be set; the settings at defaults left out."""
    config = home / "config.toml"
    config.write_text('site = "https://file.example.invalid"\nsearch_mode = "hybrid"\n', "utf-8")
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SOURCES__CONFLUENCE__SPACES", '["ENG", "OPS"]')
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    assert main(["check", "--config", str(config), "--data-dir", "~/from-flag"]) == 0
    assert capsys.readouterr().out == (
        "site: https://file.example.invalid\n"
        "api_token: set\n"
        f"data_dir: {(home / 'from-flag').resolve()}\n"
        "search_mode: hybrid\n"
        "embedding_api_key: set\n"
        "sources.confluence.spaces: ENG, OPS\n"
    )


def test_check_in_detail_shows_every_setting_its_value_and_its_layer(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The settings at defaults too, unset ones said to be so; a secret never shown."""
    monkeypatch.setenv(*next(iter(SECRETS.items())))
    assert main(["check", "--config", str(home / "none.toml"), "--summary", "detailed"]) == 0
    out = capsys.readouterr().out
    assert out == (
        "site: (not set) [default]\n"
        "email: (not set) [default]\n"
        "api_token: set [ATLASSIAN_OFFLINE_MCP_API_TOKEN]\n"
        f"data_dir: {(home / 'atlassian-offline-mcp').resolve()} [default]\n"
        "model: qwen3-embedding:0.6b [default]\n"
        "search_mode: lexical [default]\n"
        "embedding_url: http://127.0.0.1:11434/v1 [default]\n"
        "embedding_api_key: not set [default]\n"
        "sources.confluence.spaces: (none) [default]\n"
        "sources.jira.projects: (none) [default]\n"
        f"logs.dir: {user_log_folder(home.resolve())} [default]\n"
        "telemetry.endpoint: (not set) [default]\n"
    )
    assert not any(secret in out for secret in SECRETS.values())


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
    """A synchronised folder or a git working tree exits 2, naming the setting, its layer, why.

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
    assert "data_dir (--data-dir): " in error
    assert reason in error


def test_check_names_the_layer_of_a_refused_data_directory(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The file's data directory, then the variable's, each refused naming its layer."""
    config = home / "config.toml"
    config.write_text('data_dir = "~/Dropbox/from-file"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    assert "data_dir (config.toml): under a Dropbox folder" in capsys.readouterr().err

    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_DATA_DIR", "~/Documents/from-variable")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert "data_dir (ATLASSIAN_OFFLINE_MCP_DATA_DIR): under ~/Documents" in error


@pytest.mark.parametrize("name", ["check", "index"])
@pytest.mark.parametrize(
    "refused",
    [
        ("~/Dropbox/logs", "under a Dropbox folder"),
        ("~/project/logs", "inside the git working tree"),
    ],
)
def test_check_and_index_refuse_a_log_folder_that_could_leave_the_machine(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    name: str,
    refused: tuple[str, str],
) -> None:
    """Logs hold titles and queries: the data directory's guard exits 2, naming logs.dir.

    From the file, then from its variable, each named as the layer.
    """
    folder, reason = refused
    (home / "project" / ".git").mkdir(parents=True)
    config = home / "config.toml"
    config.write_text(f'[logs]\ndir = "{folder}"\n', "utf-8")
    assert main([name, "--config", str(config)]) == BAD_SETTINGS
    assert f"settings refused: logs.dir (config.toml): {reason}" in capsys.readouterr().err

    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_LOGS__DIR", folder)
    assert main([name, "--config", str(home / "none.toml")]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert f"settings refused: logs.dir (ATLASSIAN_OFFLINE_MCP_LOGS__DIR): {reason}" in error


# Endpoints that telemetry may not go to, by plan 016: a name, another host, a user, https.
ELSEWHERE = [
    "http://localhost:4318",
    "http://192.0.2.1:4318",
    "http://user@127.0.0.1:4318",
    "https://127.0.0.1:4318",
]
# What telemetry's endpoint must be, as the setting's refusal says.
TELEMETRY_RULE = (
    "an http address of this machine, with a port and no path, such as"
    " http://127.0.0.1:4318; write 127.0.0.1 for localhost"
)


@pytest.mark.parametrize("endpoint", ELSEWHERE)
def test_check_refuses_a_telemetry_endpoint_off_this_machine_naming_it(
    home: Path, capsys: CaptureFixture[str], endpoint: str
) -> None:
    """The setting exits 2, naming itself, its layer and what it must be."""
    config = home / "config.toml"
    config.write_text(f'[telemetry]\nendpoint = "{endpoint}"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    assert capsys.readouterr().err == (
        f"settings refused: telemetry.endpoint (config.toml): {TELEMETRY_RULE}\n"
    )


@pytest.mark.parametrize("endpoint", ELSEWHERE)
def test_check_ignores_opentelemetry_s_endpoint_off_this_machine_and_says_so(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], endpoint: str
) -> None:
    """Other programs share the variable: said ignored, it leaves telemetry off, exit 0."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    options = ["check", "--config", str(home / "none.toml"), "--summary", "detailed"]
    assert main(options) == 0
    out, err = capsys.readouterr()
    assert "telemetry.endpoint: (not set) [default]\n" in out
    assert (
        err == f"ignored: telemetry.endpoint (OTEL_EXPORTER_OTLP_ENDPOINT): not {TELEMETRY_RULE}\n"
    )


def test_check_names_the_layer_of_telemetry_s_endpoint_the_setting_first(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """OpenTelemetry's variable, below the file: shown as the layer, or said replaced.

    ``OTEL_SDK_DISABLED=true`` replaces whatever gave it, leaving it unset.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")
    options = ["check", "--summary", "detailed", "--config"]
    assert main([*options, str(home / "none.toml")]) == 0
    out, err = capsys.readouterr()
    assert "telemetry.endpoint: http://127.0.0.1:4317 [OTEL_EXPORTER_OTLP_ENDPOINT]\n" in out
    assert err == ""

    config = home / "config.toml"
    config.write_text('[telemetry]\nendpoint = "http://127.0.0.1:4318"\n', "utf-8")
    assert main([*options, str(config)]) == 0
    out, err = capsys.readouterr()
    assert "telemetry.endpoint: http://127.0.0.1:4318 [config.toml]\n" in out
    assert (
        err
        == "ignored: telemetry.endpoint (OTEL_EXPORTER_OTLP_ENDPOINT): replaced by config.toml\n"
    )

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert main([*options, str(config)]) == 0
    out, err = capsys.readouterr()
    assert "telemetry.endpoint: (not set) [OTEL_SDK_DISABLED]\n" in out
    assert "ignored: telemetry.endpoint (config.toml): replaced by OTEL_SDK_DISABLED\n" in err


def test_check_refuses_bad_settings_by_name(home: Path, capsys: CaptureFixture[str]) -> None:
    """A settings file with an unknown key exits 2, naming it and the file."""
    config = home / "config.toml"
    config.write_text('sight = "https://example.atlassian.net"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    assert "sight (config.toml): not a setting" in capsys.readouterr().err


def test_check_refuses_a_list_variable_not_in_json_by_its_name(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A list from the environment is JSON: the variable is named, never what it holds."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SOURCES__JIRA__PROJECTS", "PLAT,PRB")
    assert main(["check", "--config", str(home / "none.toml")]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert error.startswith("settings refused: ATLASSIAN_OFFLINE_MCP_SOURCES__JIRA__PROJECTS")
    assert "PLAT" not in error


def test_check_refuses_a_secret_in_the_settings_file(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The API token is read from the environment alone."""
    config = home / "config.toml"
    config.write_text('api_token = "not-to-be-shown"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert "api_token (config.toml): a secret" in error
    assert "not-to-be-shown" not in error


def test_check_runs_with_variables_that_name_no_setting_or_are_empty(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A misspelt, a former or an empty variable is ignored, not refused, and said on stderr."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SOURCES__JIRA__PROJETS", '["X"]')
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SPACES", '["X"]')
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", "")
    assert main(["check", "--config", str(home / "none.toml"), "--summary", "detailed"]) == 0
    out, err = capsys.readouterr()
    assert "site: (not set) [default]\n" in out
    assert sorted(err.splitlines()) == [
        "ignored: ATLASSIAN_OFFLINE_MCP_SOURCES__JIRA__PROJETS: names no setting",
        "ignored: ATLASSIAN_OFFLINE_MCP_SPACES: names no setting",
        "ignored: site (ATLASSIAN_OFFLINE_MCP_SITE): empty",
    ]


def test_an_empty_table_in_the_file_gives_each_setting_under_it_at_its_default(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Its settings are the file's; check reads them, so none is said to be unread."""
    config = home / "config.toml"
    config.write_text('[sources.jira]\n# projects = ["PLAT"]\n', "utf-8")
    assert main(["check", "--config", str(config), "--summary", "detailed"]) == 0
    out, err = capsys.readouterr()
    assert "sources.jira.projects: (none) [config.toml]\n" in out
    assert err == ""


def test_an_empty_table_in_a_variable_replaces_each_setting_under_it(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Each is the variable's, at its default, and the file's value is said to be replaced."""
    config = home / "config.toml"
    config.write_text('[sources.jira]\nprojects = ["PLAT"]\n', "utf-8")
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SOURCES", "{}")
    assert main(["check", "--config", str(config), "--summary", "detailed"]) == 0
    out, err = capsys.readouterr()
    assert "sources.confluence.spaces: (none) [ATLASSIAN_OFFLINE_MCP_SOURCES]\n" in out
    assert "sources.jira.projects: (none) [ATLASSIAN_OFFLINE_MCP_SOURCES]\n" in out
    assert err == (
        "ignored: sources.jira.projects (config.toml): replaced by ATLASSIAN_OFFLINE_MCP_SOURCES\n"
    )


def test_a_settings_file_named_default_is_a_layer_as_any_other(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Its site is shown in short, as a layer gave it, and said replaced by a variable."""
    config = home / "default"
    config.write_text('site = "https://file.example.invalid"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == 0
    assert capsys.readouterr().out == "site: https://file.example.invalid\n"
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", "https://variable.example.invalid")
    assert main(["check", "--config", str(config)]) == 0
    out, err = capsys.readouterr()
    assert out == "site: https://variable.example.invalid\n"
    assert err == "ignored: site (default): replaced by ATLASSIAN_OFFLINE_MCP_SITE\n"


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
    assert "data_dir (default): docs: under a Dropbox folder" in capsys.readouterr().err


def test_check_refuses_a_raw_store_that_leads_into_a_git_tree(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A link from <data>/raw into a working tree is refused, naming raw."""
    (home / "project" / ".git").mkdir(parents=True)
    (home / "atlassian-offline-mcp").mkdir()
    (home / "atlassian-offline-mcp" / "raw").symlink_to(home / "project")
    assert main(["check", "--config", str(home / "none.toml")]) == BAD_SETTINGS
    assert "data_dir (default): raw: inside the git working tree" in capsys.readouterr().err


def test_check_refuses_a_settings_file_it_cannot_read(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A folder where the settings file should be is refused, not a traceback."""
    (home / "config.toml").mkdir()
    assert main(["check", "--config", str(home / "config.toml")]) == BAD_SETTINGS
    assert "not readable" in capsys.readouterr().err


def test_check_names_the_layer_of_each_setting_the_strongest_winning(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The file, then its variable, then the flag: each wins in turn, and check names it.

    Each value replaced is said on stderr, naming its layer and the one that replaced it.
    """
    detailed = ["--summary", "detailed"]
    assert main(["check", "--config", str(home / "none.toml"), *detailed]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "site: (not set) [default]\n" in out
    assert f"data_dir: {(home / 'atlassian-offline-mcp').resolve()} [default]\n" in out
    assert "sources.confluence.spaces: (none) [default]\n" in out
    assert "sources.jira.projects: (none) [default]\n" in out

    config = home / "config.toml"
    config.write_text(
        'site = "https://file.example.invalid"\ndata_dir = "~/from-file"\n'
        '[sources.confluence]\nspaces = ["ENG"]\n[sources.jira]\nprojects = ["PLAT"]\n',
        "utf-8",
    )
    assert main(["check", "--config", str(config), *detailed]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "site: https://file.example.invalid [config.toml]\n" in out
    assert f"data_dir: {(home / 'from-file').resolve()} [config.toml]\n" in out
    assert "sources.confluence.spaces: ENG [config.toml]\n" in out
    assert "sources.jira.projects: PLAT [config.toml]\n" in out

    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SITE", "https://variable.example.invalid")
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_DATA_DIR", "~/from-variable")
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SOURCES__CONFLUENCE__SPACES", '["OPS"]')
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_SOURCES__JIRA__PROJECTS", '["PRB", "PAY"]')
    assert main(["check", "--config", str(config), *detailed]) == 0
    out, err = capsys.readouterr()
    assert sorted(err.splitlines()) == [
        "ignored: data_dir (config.toml): replaced by ATLASSIAN_OFFLINE_MCP_DATA_DIR",
        "ignored: site (config.toml): replaced by ATLASSIAN_OFFLINE_MCP_SITE",
        (
            "ignored: sources.confluence.spaces (config.toml):"
            " replaced by ATLASSIAN_OFFLINE_MCP_SOURCES__CONFLUENCE__SPACES"
        ),
        (
            "ignored: sources.jira.projects (config.toml):"
            " replaced by ATLASSIAN_OFFLINE_MCP_SOURCES__JIRA__PROJECTS"
        ),
    ]
    assert "site: https://variable.example.invalid [ATLASSIAN_OFFLINE_MCP_SITE]\n" in out
    data = (home / "from-variable").resolve()
    assert f"data_dir: {data} [ATLASSIAN_OFFLINE_MCP_DATA_DIR]\n" in out
    spaces = "sources.confluence.spaces: OPS [ATLASSIAN_OFFLINE_MCP_SOURCES__CONFLUENCE__SPACES]"
    assert f"{spaces}\n" in out
    projects = "sources.jira.projects: PRB, PAY [ATLASSIAN_OFFLINE_MCP_SOURCES__JIRA__PROJECTS]"
    assert f"{projects}\n" in out

    flag = ["--site", "https://flag.example.invalid", "--data-dir", "~/from-flag"]
    assert main(["check", "--config", str(config), *flag, *detailed]) == 0
    out, err = capsys.readouterr()
    assert "site: https://flag.example.invalid [--site]\n" in out
    assert f"data_dir: {(home / 'from-flag').resolve()} [--data-dir]\n" in out
    assert "ignored: site (ATLASSIAN_OFFLINE_MCP_SITE): replaced by --site\n" in err
    assert "ignored: data_dir (ATLASSIAN_OFFLINE_MCP_DATA_DIR): replaced by --data-dir\n" in err


def test_check_reads_no_generic_atlassian_name(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """ATLASSIAN_SITE is another tool's: the site stays unset."""
    monkeypatch.setenv("ATLASSIAN_SITE", "https://other.example.invalid")
    assert main(["check", "--config", str(home / "none.toml"), "--summary", "detailed"]) == 0
    assert "site: (not set) [default]\n" in capsys.readouterr().out


def test_a_flag_overrides_the_settings_file(home: Path, capsys: CaptureFixture[str]) -> None:
    """--data-dir wins over the file's data_dir."""
    config = home / "config.toml"
    config.write_text('data_dir = "~/from-file"\n', "utf-8")
    assert main(["check", "--config", str(config), "--data-dir", "~/from-flag"]) == 0
    assert capsys.readouterr().out == f"data_dir: {(home / 'from-flag').resolve()}\n"
