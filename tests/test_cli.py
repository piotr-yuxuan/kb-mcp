"""Tests of the command: its subcommands, and ``check`` end to end in a scratch home."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pty
import re
import stat
import subprocess
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import argcomplete
import pytest

import kb_mcp
from kb_mcp.cli import commands, options
from kb_mcp.cli.main import main, parser
from kb_mcp.config.domain.settings import setting_paths
from kb_mcp.kernel.exit_status import MEANINGS, ExitStatus
from kb_mcp.kernel.output import Output
from tests.composed import MODEL
from tests.endpoint import nothing_listening
from tests.test_confirmation import read_until
from tests.test_observed import said as said_on
from tests.test_settings import user_log_folder

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.kernel.output import Level

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
        "requests",
        "rich",
        "structlog",
        "yaml",
    }
)
# A subcommand's declaration, which names its run, a module of its own.
DECLARED = """
from pathlib import Path

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options

def register(subparsers, _sources):
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
SETTINGS = {".".join(path) for path, kind in setting_paths(MODEL).items() if kind != "table"}
# Every subcommand that the command declares, by the name it is typed by.
SUBCOMMANDS = parser(Declaring).subcommands
# What a subcommand needs besides its options to be parsed: its positional arguments.
POSITIONALS = {
    "login": ["atlassian"],
    "eval": ["golden.yaml"],
    "eval-agents": ["grade", "runs"],
    "eval-rerank": ["golden.yaml"],
    "model": ["check"],
    "reranker": ["check"],
}
# The subcommands whose output is their own, by plan 015: the protocol, a script.
OWN_OUTPUT = {"serve", "completion"}
# The subcommands that write under the data directory, and so ask first, by plan 015.
WRITING = {
    "embed",
    "eval",
    "eval-agents",
    "eval-rerank",
    "fetch",
    "index",
    "login",
    "prepare",
}
# The subcommands that take --dry-run, by plans 015 and 017.
DRY_RUN = {"fetch", "prepare"}
SECRETS = {
    "KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN": "token-sentinel-4d1c",
    "KB_MCP_EMBEDDING_API_KEY": "key-sentinel-9a7e",
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
    Its declaration, in ``cli.options``, bears the same module's name, or, for a run that
    several commands share, as ``fetch``'s, the command's.
    """
    command = SUBCOMMANDS[name].get_default("command")
    assert command.name == name
    package, _, module = command.run.rpartition(".")
    assert package == commands.__name__
    assert callable(importlib.import_module(command.run).run)
    declaration = name if module == "sources" else module
    assert callable(importlib.import_module(f"{options.__name__}.{declaration}").register)


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
def test_the_commands_that_write_take_yes_and_fetch_and_prepare_a_dry_run(name: str) -> None:
    """They ask first, as plans 015 and 017 list them; check, doctor, model, serve never do."""
    command = SUBCOMMANDS[name].get_default("command")
    arguments = parser().parse_args([name, *POSITIONALS.get(name, [])])
    assert command.writes is (name in WRITING)
    assert hasattr(arguments, "yes") is command.writes
    assert command.dry_run is (name in DRY_RUN)
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


def test_the_program_says_what_it_is_in_one_sentence_everywhere() -> None:
    """Plan 052: the project's description, the package's docstring and --help's, alike.

    The README and the instructions for coding agents open with it too, its words as they
    are, whatever their lines.
    """
    said = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["description"]
    assert "work log" in said
    assert (kb_mcp.__doc__ or "").splitlines()[0] == said
    assert parser().description == said
    assert [
        page
        for page in ("README.md", "AGENTS.md")
        if said not in " ".join((ROOT / page).read_text("utf-8").split())
    ] == []


def test_the_version_is_the_project_s(capsys: CaptureFixture[str]) -> None:
    """--version prints the program's name and the version that the project declares."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out == f"kb-mcp {project['version']}\n"


def test_the_help_lists_the_commands_of_plan_031(capsys: CaptureFixture[str]) -> None:
    """Plan 031, criterion 2: each of these, which another command may join."""
    with pytest.raises(SystemExit):
        main(["--help"])
    assert set(SUBCOMMANDS) >= {
        "check",
        "completion",
        "doctor",
        "embed",
        "eval",
        "eval-agents",
        "eval-rerank",
        "fetch",
        "index",
        "login",
        "model",
        "prepare",
        "reranker",
        "serve",
    }
    said = capsys.readouterr().out
    assert all(name in said for name in SUBCOMMANDS)


@pytest.mark.parametrize("name", ["sync", "download", "mirror"])
def test_a_command_that_went_is_refused_naming_the_choices(
    name: str, capsys: CaptureFixture[str]
) -> None:
    """Plan 031: no alias stays; the parser's message lists what there is, exit 2."""
    with pytest.raises(SystemExit) as stopped:
        main([name])
    assert stopped.value.code == ExitStatus.REFUSED
    err = capsys.readouterr().err
    assert f"invalid choice: '{name}'" in err
    assert "'fetch'" in err
    assert "'prepare'" in err


def test_the_help_says_who_asks_and_what_each_exit_status_means() -> None:
    """The commands that write ask first, by name; every status of the one enum is listed.

    The help is read with its lines joined, as its width follows the terminal's, which may
    break a name at its hyphen.
    """
    said = " ".join(parser().format_help().split()).replace("- ", "-")
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
        [sys.executable, "-m", "kb_mcp", "--help"],
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
    assert b"Exit statuses" in b" ".join(said.split())
    assert (b"\x1b" in said) is coloured


def test_declaring_the_command_imports_none_of_the_runs_packages(home: Path) -> None:
    """--version, --help, a subcommand's and a completion import no run; ``completion`` its own.

    Each builds the whole parser. ``completion``, which shells run at each start, is not
    observed, as plan 016 decided after its review: it reads no settings, so its run
    imports none of the runs' packages either, as --version. ``-X importtime`` names
    each module that the child imports, so a package it does not name never reached
    ``sys.modules``.
    """
    environment = {"HOME": str(home), "PATH": os.environ["PATH"]}
    typed = "kb-mcp fetch --sp"
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
                [sys.executable, "-X", "importtime", "-m", "kb_mcp", "--version"],
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
                [sys.executable, "-X", "importtime", "-m", "kb_mcp", "--help"],
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
                    "kb_mcp",
                    "fetch",
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
                [sys.executable, "-X", "importtime", "-m", "kb_mcp"],
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
                [sys.executable, "-X", "importtime", "-m", "kb_mcp", "completion"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=environment,
                cwd=home,
                check=False,
            ),
            RUNS_PACKAGES,
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
        assert {"argparse", "kb_mcp"} <= imported
        assert not imported & refused


@pytest.mark.parametrize(
    ("line", "offered"),
    [("fet", {"fetch"}), ("fetch --sp", {"--space"}), ("check --format ", {"text", "json"})],
)
def test_the_shell_completes_the_command_line(home: Path, line: str, offered: set[str]) -> None:
    """A child called as the shell code calls it offers what may follow the line.

    That is argcomplete's protocol: the line and the cursor in the environment, the
    completions, separated by vertical tabs, in the file it names.
    """
    typed = f"kb-mcp {line}"
    environment = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "_ARGCOMPLETE": "1",
        "COMP_LINE": typed,
        "COMP_POINT": str(len(typed)),
        "_ARGCOMPLETE_STDOUT_FILENAME": str(home / "completions"),
    }
    child = subprocess.run(
        [sys.executable, "-m", "kb_mcp"],
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
    (home / ".config" / "kb-mcp").mkdir(parents=True)
    (home / ".config" / "kb-mcp" / "config.toml").write_text("site = ", "utf-8")
    assert main(["completion"]) == 0
    assert capsys.readouterr().out == argcomplete.shellcode(["kb-mcp"])


def test_completion_is_not_observed_and_writes_no_script_with_q(
    capsys: CaptureFixture[str],
) -> None:
    """As --version, it says nothing on stderr at any level; -q leaves its script unwritten.

    Plan 016 decided so after its review, shells running it at each start; plan 015 has
    the script be its result, which -q leaves unwritten as any result as text.
    """
    for level in (["-v"], ["-vv"], ["--log-level", "debug"]):
        assert main(["completion", *level]) == 0
        assert capsys.readouterr() == (argcomplete.shellcode(["kb-mcp"]), "")
    assert main(["completion", "-q"]) == 0
    assert capsys.readouterr() == ("", "")


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
    assert json.loads(capsys.readouterr().out)["layers"] == {"accounts.atlassian.site": "--site"}


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
    default = capsys.readouterr().out
    assert default == f"accounts.atlassian.site: {site}\n"
    assert main([*options, *level]) == 0
    assert capsys.readouterr().out == default


def test_check_as_json_gives_settings_layers_and_ignored_values_secrets_masked(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """One document: the settings, each one's layer, what was ignored; never a secret's value."""
    config = home / "config.toml"
    config.write_text(
        '[accounts.atlassian]\nsite = "https://file.example.invalid"\n'
        '[sources.confluence]\nspaces = ["ENG"]\n',
        "utf-8",
    )
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__SITE", "https://variable.example.invalid")
    monkeypatch.setenv("KB_MCP_SPACES", '["X"]')
    for summary in ("short", "detailed"):
        options = ["--config", str(config), "--summary", summary, "--format", "json"]
        assert main(["check", *options]) == 0
        out = capsys.readouterr().out
        assert not any(secret in out for secret in SECRETS.values())
        document = json.loads(out)
        settings = document["settings"]
        assert settings["accounts"]["atlassian"]["site"] == "https://variable.example.invalid"
        assert settings["data_dir"] == str((home / "kb-mcp").resolve())
        assert settings["sources"]["confluence"]["spaces"] == ["ENG"]
        assert settings["accounts"]["atlassian"]["api_token"]
        assert settings["embedding_api_key"]
        assert document["layers"] == {
            "accounts.atlassian.site": "KB_MCP_ACCOUNTS__ATLASSIAN__SITE",
            "sources.confluence.spaces": "config.toml",
            "accounts.atlassian.api_token": "KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN",
            "embedding_api_key": "KB_MCP_EMBEDDING_API_KEY",
        }
        assert sorted(document["ignored"], key=lambda ignored: ignored["layer"]) == [
            {"setting": None, "layer": "KB_MCP_SPACES", "why": "names no setting"},
            {
                "setting": "accounts.atlassian.site",
                "layer": "config.toml",
                "why": "replaced by KB_MCP_ACCOUNTS__ATLASSIAN__SITE",
            },
        ]


def test_check_accepts_a_plain_data_directory(home: Path, capsys: CaptureFixture[str]) -> None:
    """Valid settings and a safe directory exit 0; in short, the settings given are shown."""
    config = home / "config.toml"
    config.write_text(
        '[accounts.atlassian]\nsite = "https://example.atlassian.net"\n'
        '[sources.confluence]\nspaces = ["ENG"]\n',
        "utf-8",
    )
    assert main(["check", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert out == (
        "accounts.atlassian.site: https://example.atlassian.net\nsources.confluence.spaces: ENG\n"
    )
    assert main(["check", "--config", str(config), "--summary", "detailed"]) == 0
    data = (home / "kb-mcp").resolve()
    assert f"data_dir: {data} [default]\n" in capsys.readouterr().out


def test_check_in_short_shows_each_setting_given_and_its_value(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """From any layer, by its path; a secret said to be set; the settings at defaults left out."""
    config = home / "config.toml"
    config.write_text(
        'search_mode = "semantic"\n[accounts.atlassian]\nsite = "https://file.example.invalid"\n',
        "utf-8",
    )
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SPACES", '["ENG", "OPS"]')
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    assert main(["check", "--config", str(config), "--data-dir", "~/from-flag"]) == 0
    assert capsys.readouterr().out == (
        f"data_dir: {(home / 'from-flag').resolve()}\n"
        "search_mode: semantic\n"
        "embedding_api_key: set\n"
        "accounts.atlassian.site: https://file.example.invalid\n"
        "accounts.atlassian.api_token: set\n"
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
        f"data_dir: {(home / 'kb-mcp').resolve()} [default]\n"
        "model: qwen3-embedding:0.6b [default]\n"
        "search_mode: hybrid [default]\n"
        "chunking: windows [default]\n"
        "embedding_url: http://127.0.0.1:11434/v1 [default]\n"
        "embedding_api_key: not set [default]\n"
        "accounts.atlassian.site: (not set) [default]\n"
        "accounts.atlassian.email: (not set) [default]\n"
        "accounts.atlassian.api_token: set [KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN]\n"
        "sources.confluence.spaces: (none) [default]\n"
        "sources.jira.projects: (none) [default]\n"
        "sources.worklog.path: (not set) [default]\n"
        "sources.worklog.archives: True [default]\n"
        f"logs.dir: {user_log_folder(home.resolve())} [default]\n"
        "telemetry.endpoint: (not set) [default]\n"
        "rerank.enabled: False [default]\n"
        "rerank.url: http://127.0.0.1:9931/v1 [default]\n"
        "rerank.model: qwen3-reranker-0.6b [default]\n"
        "rerank.depth: 30 [default]\n"
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

    monkeypatch.setenv("KB_MCP_DATA_DIR", "~/Documents/from-variable")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert "data_dir (KB_MCP_DATA_DIR): under ~/Documents" in error


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

    From the file, then from its variable, each named as the layer, by the error
    settings.refused; the run never starts, so no log file is written anywhere.
    """
    folder, reason = refused
    (home / "project" / ".git").mkdir(parents=True)
    config = home / "config.toml"
    config.write_text(f'[logs]\ndir = "{folder}"\n', "utf-8")
    assert main([name, "--config", str(config)]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert said_on(error) == [("error", "settings.refused")]
    assert f"logs.dir (config.toml): {reason}" in error

    monkeypatch.setenv("KB_MCP_LOGS__DIR", folder)
    assert main([name, "--config", str(home / "none.toml")]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert said_on(error) == [("error", "settings.refused")]
    assert f"logs.dir (KB_MCP_LOGS__DIR): {reason}" in error
    assert not (home / folder.removeprefix("~/")).exists()
    assert not user_log_folder(home.resolve()).exists()


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
    """The setting exits 2, naming itself, its layer and what it must be, in one error."""
    config = home / "config.toml"
    config.write_text(f'[telemetry]\nendpoint = "{endpoint}"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    (line,) = capsys.readouterr().err.splitlines()
    assert said_on(line) == [("error", "settings.refused")]
    assert f"telemetry.endpoint (config.toml): {TELEMETRY_RULE}" in line


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

    ``OTEL_SDK_DISABLED=true`` replaces whatever gave it, leaving it unset. Nothing
    listens at either endpoint, which each run says once, after it says telemetry on.
    """
    with nothing_listening() as shared, nothing_listening() as set_here:
        variable, setting = shared.removesuffix("/v1"), set_here.removesuffix("/v1")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", variable)
        options = ["check", "--summary", "detailed", "--config"]
        assert main([*options, str(home / "none.toml")]) == 0
        out, err = capsys.readouterr()
        assert f"telemetry.endpoint: {variable} [OTEL_EXPORTER_OTLP_ENDPOINT]\n" in out
        on, undelivered = err.splitlines()
        assert on == f"telemetry: on, to {variable} (OTEL_EXPORTER_OTLP_ENDPOINT)"
        assert said_on(undelivered) == [("warning", "telemetry.undelivered")]

        config = home / "config.toml"
        config.write_text(f'[telemetry]\nendpoint = "{setting}"\n', "utf-8")
        assert main([*options, str(config)]) == 0
        out, err = capsys.readouterr()
        assert f"telemetry.endpoint: {setting} [config.toml]\n" in out
        on, ignored, undelivered = err.splitlines()
        assert on == f"telemetry: on, to {setting} (config.toml)"
        assert ignored == (
            "ignored: telemetry.endpoint (OTEL_EXPORTER_OTLP_ENDPOINT): replaced by config.toml"
        )
        assert said_on(undelivered) == [("warning", "telemetry.undelivered")]

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert main([*options, str(config)]) == 0
    out, err = capsys.readouterr()
    assert "telemetry.endpoint: (not set) [OTEL_SDK_DISABLED]\n" in out
    assert "ignored: telemetry.endpoint (config.toml): replaced by OTEL_SDK_DISABLED\n" in err


def test_check_says_that_telemetry_is_on_and_names_its_layer_at_info(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A command that only reads has no summary, but says that telemetry is on, and where.

    run.start names the endpoint and its layer too. OpenTelemetry's variable alone turns
    telemetry on; nothing listens there, which the run says once: two lines at the
    default level.
    """
    with nothing_listening() as url:
        endpoint = url.removesuffix("/v1")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
        options = ["check", "--config", str(home / "none.toml")]
        assert main(options) == 0
        on, undelivered = capsys.readouterr().err.splitlines()
        assert on == f"telemetry: on, to {endpoint} (OTEL_EXPORTER_OTLP_ENDPOINT)"
        assert said_on(undelivered) == [("warning", "telemetry.undelivered")]
        assert main([*options, "-v"]) == 0
        err = capsys.readouterr().err
    (started,) = [line for line in err.splitlines() if said_on(line) == [("info", "run.start")]]
    assert f"telemetry={endpoint} " in started
    assert "telemetry_layer=OTEL_EXPORTER_OTLP_ENDPOINT" in started
    starts = logged_as(home, "run.start")
    assert [(start["telemetry"], start["telemetry_layer"]) for start in starts] == [
        (endpoint, "OTEL_EXPORTER_OTLP_ENDPOINT")
    ] * len(["default", "-v"])


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
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__PROJECTS", "PLAT,PRB")
    assert main(["check", "--config", str(home / "none.toml")]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert said_on(error) == [("error", "settings.refused")]
    assert "KB_MCP_SOURCES__JIRA__PROJECTS" in error
    assert "PLAT" not in error


def test_check_refuses_a_secret_in_the_settings_file(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The API token is read from the environment alone."""
    config = home / "config.toml"
    config.write_text('[accounts.atlassian]\napi_token = "not-to-be-shown"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == BAD_SETTINGS
    error = capsys.readouterr().err
    assert "accounts.atlassian.api_token (config.toml): a secret" in error
    assert "not-to-be-shown" not in error


def test_check_runs_with_variables_that_name_no_setting_or_are_empty(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A misspelt, a former or an empty variable is ignored, not refused, and said on stderr."""
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__PROJETS", '["X"]')
    monkeypatch.setenv("KB_MCP_SPACES", '["X"]')
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__SITE", "")
    assert main(["check", "--config", str(home / "none.toml"), "--summary", "detailed"]) == 0
    out, err = capsys.readouterr()
    assert "\naccounts.atlassian.site: (not set) [default]\n" in out
    assert sorted(err.splitlines()) == [
        "ignored: KB_MCP_SOURCES__JIRA__PROJETS: names no setting",
        "ignored: KB_MCP_SPACES: names no setting",
        "ignored: accounts.atlassian.site (KB_MCP_ACCOUNTS__ATLASSIAN__SITE): empty",
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
    monkeypatch.setenv("KB_MCP_SOURCES", "{}")
    assert main(["check", "--config", str(config), "--summary", "detailed"]) == 0
    out, err = capsys.readouterr()
    assert "sources.confluence.spaces: (none) [KB_MCP_SOURCES]\n" in out
    assert "sources.jira.projects: (none) [KB_MCP_SOURCES]\n" in out
    assert err == ("ignored: sources.jira.projects (config.toml): replaced by KB_MCP_SOURCES\n")


def test_a_settings_file_named_default_is_a_layer_as_any_other(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Its site is shown in short, as a layer gave it, and said replaced by a variable."""
    config = home / "default"
    config.write_text('[accounts.atlassian]\nsite = "https://file.example.invalid"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == 0
    assert capsys.readouterr().out == "accounts.atlassian.site: https://file.example.invalid\n"
    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__SITE", "https://variable.example.invalid")
    assert main(["check", "--config", str(config)]) == 0
    out, err = capsys.readouterr()
    assert out == "accounts.atlassian.site: https://variable.example.invalid\n"
    assert err == (
        "ignored: accounts.atlassian.site (default): replaced by KB_MCP_ACCOUNTS__ATLASSIAN__SITE\n"
    )


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
    (home / "kb-mcp").mkdir()
    (home / "kb-mcp" / "docs").symlink_to(home / "Dropbox" / "shared")
    assert main(["check", "--config", str(home / "none.toml")]) == BAD_SETTINGS
    assert "data_dir (default): docs: under a Dropbox folder" in capsys.readouterr().err


def test_check_refuses_a_raw_store_that_leads_into_a_git_tree(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """A link from <data>/raw into a working tree is refused, naming raw."""
    (home / "project" / ".git").mkdir(parents=True)
    (home / "kb-mcp").mkdir()
    (home / "kb-mcp" / "raw").symlink_to(home / "project")
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
    assert "\naccounts.atlassian.site: (not set) [default]\n" in out
    assert f"data_dir: {(home / 'kb-mcp').resolve()} [default]\n" in out
    assert "sources.confluence.spaces: (none) [default]\n" in out
    assert "sources.jira.projects: (none) [default]\n" in out

    config = home / "config.toml"
    config.write_text(
        'data_dir = "~/from-file"\n[accounts.atlassian]\nsite = "https://file.example.invalid"\n'
        '[sources.confluence]\nspaces = ["ENG"]\n[sources.jira]\nprojects = ["PLAT"]\n',
        "utf-8",
    )
    assert main(["check", "--config", str(config), *detailed]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "\naccounts.atlassian.site: https://file.example.invalid [config.toml]\n" in out
    assert f"data_dir: {(home / 'from-file').resolve()} [config.toml]\n" in out
    assert "sources.confluence.spaces: ENG [config.toml]\n" in out
    assert "sources.jira.projects: PLAT [config.toml]\n" in out

    monkeypatch.setenv("KB_MCP_ACCOUNTS__ATLASSIAN__SITE", "https://variable.example.invalid")
    monkeypatch.setenv("KB_MCP_DATA_DIR", "~/from-variable")
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SPACES", '["OPS"]')
    monkeypatch.setenv("KB_MCP_SOURCES__JIRA__PROJECTS", '["PRB", "PAY"]')
    assert main(["check", "--config", str(config), *detailed]) == 0
    out, err = capsys.readouterr()
    assert sorted(err.splitlines()) == [
        (
            "ignored: accounts.atlassian.site (config.toml):"
            " replaced by KB_MCP_ACCOUNTS__ATLASSIAN__SITE"
        ),
        "ignored: data_dir (config.toml): replaced by KB_MCP_DATA_DIR",
        (
            "ignored: sources.confluence.spaces (config.toml):"
            " replaced by KB_MCP_SOURCES__CONFLUENCE__SPACES"
        ),
        (
            "ignored: sources.jira.projects (config.toml):"
            " replaced by KB_MCP_SOURCES__JIRA__PROJECTS"
        ),
    ]
    variable = "KB_MCP_ACCOUNTS__ATLASSIAN__SITE"
    assert f"\naccounts.atlassian.site: https://variable.example.invalid [{variable}]\n" in out
    data = (home / "from-variable").resolve()
    assert f"data_dir: {data} [KB_MCP_DATA_DIR]\n" in out
    spaces = "sources.confluence.spaces: OPS [KB_MCP_SOURCES__CONFLUENCE__SPACES]"
    assert f"{spaces}\n" in out
    projects = "sources.jira.projects: PRB, PAY [KB_MCP_SOURCES__JIRA__PROJECTS]"
    assert f"{projects}\n" in out

    flag = ["--site", "https://flag.example.invalid", "--data-dir", "~/from-flag"]
    assert main(["check", "--config", str(config), *flag, *detailed]) == 0
    out, err = capsys.readouterr()
    assert "\naccounts.atlassian.site: https://flag.example.invalid [--site]\n" in out
    assert f"data_dir: {(home / 'from-flag').resolve()} [--data-dir]\n" in out
    assert f"ignored: accounts.atlassian.site ({variable}): replaced by --site\n" in err
    assert "ignored: data_dir (KB_MCP_DATA_DIR): replaced by --data-dir\n" in err


def test_check_reads_no_generic_atlassian_name(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """ATLASSIAN_SITE is another tool's: the site stays unset."""
    monkeypatch.setenv("ATLASSIAN_SITE", "https://other.example.invalid")
    assert main(["check", "--config", str(home / "none.toml"), "--summary", "detailed"]) == 0
    assert "\naccounts.atlassian.site: (not set) [default]\n" in capsys.readouterr().out


def test_a_flag_overrides_the_settings_file(home: Path, capsys: CaptureFixture[str]) -> None:
    """--data-dir wins over the file's data_dir."""
    config = home / "config.toml"
    config.write_text('data_dir = "~/from-file"\n', "utf-8")
    assert main(["check", "--config", str(config), "--data-dir", "~/from-flag"]) == 0
    assert capsys.readouterr().out == f"data_dir: {(home / 'from-flag').resolve()}\n"


# The site that the runs below are given, by --site.
SITE = "https://logged.example.invalid"
# Each line of a run's log file holds these fields, by plan 016.
LOG_FIELDS = {"timestamp", "level", "event", "logger", "run", "command"}
# A run that says something at each level, then ends.
SAYING = """
import structlog

def run(arguments, loaded):
    for level in ("debug", "info", "warning", "error"):
        getattr(structlog.get_logger(), level)(f"extra.{level}")
    return 0, None
"""


def the_log_file(home: Path) -> Path:
    """Give the one log file in the user's log folder under a scratch home."""
    (path,) = user_log_folder(home.resolve()).iterdir()
    return path


def logged(path: Path) -> list[dict[str, object]]:
    """Read a log file's lines, each a JSON object."""
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def logged_as(home: Path, event: str) -> list[dict[str, object]]:
    """Give the lines of the log files under a scratch home whose event is ``event``.

    Every run's file, a command's in the order of their names, so of their starts.
    """
    return [
        line
        for path in sorted(user_log_folder(home.resolve()).iterdir())
        for line in logged(path)
        if line["event"] == event
    ]


def test_check_writes_one_log_file_at_the_platform_s_default_from_run_start_to_run_end(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The user's alone, in their log folder; run.start says the settings as check's JSON.

    The secrets that check masks are redacted there, by their names.
    """
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    given = ["check", "--config", str(home / "none.toml"), "--site", SITE, "--format", "json"]
    assert main(given) == 0
    document = json.loads(capsys.readouterr().out)
    path = the_log_file(home)
    assert re.fullmatch(rf"check-[0-9]{{8}}T[0-9]{{6}}Z-{os.getpid()}\.jsonl", path.name)
    assert stat.S_IMODE(path.parent.stat().st_mode) == stat.S_IRWXU
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
    assert not any(secret in path.read_text("utf-8") for secret in SECRETS.values())
    start, end = logged(path)
    for line in (start, end):
        assert line.keys() >= LOG_FIELDS
        assert line["command"] == "check"
        assert re.fullmatch("[0-9a-f]{16}", str(line["run"]))
    assert start["run"] == end["run"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    masked = "[redacted]"  # by their names, at any depth
    document["settings"]["accounts"]["atlassian"]["api_token"] = masked
    document["layers"]["accounts.atlassian.api_token"] = masked
    document["settings"]["embedding_api_key"] = document["layers"]["embedding_api_key"] = masked
    assert {key: start[key] for key in ("level", "event", "version", "arguments")} == {
        "level": "info",
        "event": "run.start",
        "version": project["version"],
        "arguments": given,
    }
    assert start["settings"] == document
    assert (start["log_file"], start["telemetry"], start["telemetry_layer"]) == (
        str(path),
        None,
        "default",
    )
    assert (end["level"], end["event"], end["status"]) == ("info", "run.end", 0)
    assert isinstance(end["seconds"], float)
    assert end["seconds"] >= 0


def test_a_run_removes_every_command_s_log_files_past_30_days_but_not_another_program_s(
    home: Path,
) -> None:
    """``check`` removes ``doctor``'s and ``serve``'s as its own, by plan 016.

    A command that is rarely run, such as ``doctor``, so keeps none past 30 days, nor does
    one that plan 031 removed, whose files hold titles and queries. A file of the same shape
    named after no command, another program's in a shared folder, stays, as does a command's
    of yesterday.
    """
    folder = user_log_folder(home.resolve())
    folder.mkdir(parents=True)
    old = "20200101T000000Z"
    gone = [
        f"check-{old}-7.jsonl",
        f"doctor-{old}-8.jsonl",
        f"serve-{old}-9.jsonl",
        f"download-{old}-10.jsonl",
        f"mirror-{old}-11.jsonl",
        f"sync-{old}-12.jsonl",
    ]
    kept = [
        f"backup-{old}-7.jsonl",
        f"index-{datetime.now(UTC) - timedelta(days=1):%Y%m%dT%H%M%SZ}-7.jsonl",
    ]
    for name in [*gone, *kept]:
        (folder / name).write_text("{}\n", encoding="utf-8")
    assert main(["check", "--config", str(home / "none.toml"), "--site", SITE]) == 0
    (written,) = {path.name for path in folder.iterdir()} - set(kept)
    assert written.startswith("check-")
    assert written not in gone


def test_help_version_completions_and_completion_write_no_log_file(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """None of them is a run: no log folder is even made under the scratch home."""
    for asked in (["--help"], ["--version"], ["check", "--help"]):
        with pytest.raises(SystemExit) as stopped:
            main(asked)
        assert stopped.value.code == 0
    assert main(["completion"]) == 0
    capsys.readouterr()
    typed = "kb-mcp check --"
    child = subprocess.run(
        [sys.executable, "-m", "kb_mcp"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={
            "HOME": str(home),
            "PATH": os.environ["PATH"],
            "_ARGCOMPLETE": "1",
            "COMP_LINE": typed,
            "COMP_POINT": str(len(typed)),
            "_ARGCOMPLETE_STDOUT_FILENAME": str(home / "completions"),
        },
        cwd=home,
        check=False,
    )
    assert child.returncode == 0
    assert "--config" in (home / "completions").read_text("utf-8")
    assert not user_log_folder(home.resolve()).exists()


@pytest.mark.parametrize(
    ("level", "said"),
    [
        ([], []),
        (["-v"], [("info", "run.start"), ("info", "run.end")]),
        (["-vv"], [("info", "run.start"), ("info", "run.end")]),
        (["-q"], []),
    ],
)
def test_check_s_stderr_holds_its_level_s_lines_and_stdout_its_listing(
    home: Path, capsys: CaptureFixture[str], level: list[str], said: list[tuple[str, str]]
) -> None:
    """Uncoloured, piped; stdout alike at every level but -q, which empties it.

    The file holds the run from DEBUG, whatever the level.
    """
    assert main(["check", "--config", str(home / "none.toml"), "--site", SITE, *level]) == 0
    out, err = capsys.readouterr()
    assert out == ("" if level == ["-q"] else f"accounts.atlassian.site: {SITE}\n")
    assert said_on(err) == said
    assert "\x1b" not in err
    assert [line["event"] for line in logged(the_log_file(home))] == ["run.start", "run.end"]


def test_quiet_leaves_check_s_json_document_as_it_is(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """-q is of stderr and of a result as text: a document is the same with it as without."""
    given = ["check", "--config", str(home / "none.toml"), "--site", SITE, "--format", "json"]
    assert main(given) == 0
    document = capsys.readouterr().out
    assert main([*given, "-q"]) == 0
    assert capsys.readouterr() == (document, "")


@pytest.mark.parametrize(
    ("level", "shown"),
    [
        ([], ("warning", "error")),
        (["-v"], ("info", "warning", "error")),
        (["-vv"], ("debug", "info", "warning", "error")),
        (["-q"], ("error",)),
        (["--log-level", "debug"], ("debug", "info", "warning", "error")),
        (["--log-level", "info"], ("info", "warning", "error")),
        (["--log-level", "warning"], ("warning", "error")),
        (["--log-level", "error"], ("error",)),
    ],
)
def test_stderr_shows_what_is_of_the_level_or_above_and_the_file_all(
    home: Path,
    extra: Path,
    capsys: CaptureFixture[str],
    level: list[str],
    shown: tuple[str, ...],
) -> None:
    """Warning by default, info with -v, debug with -vv, error with -q, else as named."""
    (extra / "extra_run.py").write_text(SAYING, "utf-8")
    assert main(["extra", "--config", str(home / "none.toml"), *level]) == 0
    expected = [(each, f"extra.{each}") for each in shown]
    if "info" in shown:
        expected = [("info", "run.start"), *expected, ("info", "run.end")]
    assert said_on(capsys.readouterr().err) == expected
    assert [line["event"] for line in logged(the_log_file(home))] == [
        "run.start",
        *(f"extra.{each}" for each in ("debug", "info", "warning", "error")),
        "run.end",
    ]


def test_an_unwritable_log_folder_gives_one_warning_and_no_file(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """The run goes on, exit 0, its listing unchanged; the warning names the folder."""
    (home / "a-file").write_text("", "utf-8")
    config = home / "config.toml"
    config.write_text('[logs]\ndir = "~/a-file/logs"\n', "utf-8")
    assert main(["check", "--config", str(config)]) == 0
    out, err = capsys.readouterr()
    assert out == f"logs.dir: {home.resolve() / 'a-file' / 'logs'}\n"
    (warning,) = err.splitlines()
    assert said_on(warning) == [("warning", "log.unwritable")]
    assert str(home.resolve() / "a-file" / "logs") in warning
    assert (home / "a-file").is_file()


@pytest.mark.parametrize(
    ("raised", "ending"),
    [
        ("ValueError('the run broke')", (ExitStatus.FAILED, "error", "run.failed")),
        ("KeyboardInterrupt()", (ExitStatus.INTERRUPTED, "warning", "run.interrupted")),
    ],
)
def test_a_run_that_fails_or_is_interrupted_says_so_and_exits_with_its_status(
    home: Path,
    extra: Path,
    capsys: CaptureFixture[str],
    raised: str,
    ending: tuple[ExitStatus, str, str],
) -> None:
    """On stderr and in the file, its last line; a traceback shows no frame's locals."""
    status, *said = ending
    sentinel = "local-sentinel-5b2c"
    (extra / "extra_run.py").write_text(
        f"def run(arguments, loaded):\n    held = {sentinel!r}\n    raise {raised}\n", "utf-8"
    )
    assert main(["extra", "--config", str(home / "none.toml")]) == status
    _, err = capsys.readouterr()
    assert said_on(err) == [tuple(said)]
    path = the_log_file(home)
    *_, last = logged(path)
    assert [last["level"], last["event"]] == said
    assert isinstance(last["seconds"], float)
    assert sentinel not in err
    assert sentinel not in path.read_text("utf-8")
    assert ("Traceback (most recent call last):" in err) is (status == ExitStatus.FAILED)


@pytest.mark.parametrize(("variables", "coloured"), [({"NO_COLOR": "1"}, False), ({}, True)])
def test_stderr_on_a_terminal_is_coloured_unless_no_color(
    home: Path, variables: dict[str, str], *, coloured: bool
) -> None:
    """A child's -v lines on a pseudo-terminal have escape bytes, none under NO_COLOR.

    Stdout, piped, holds the listing alone.
    """
    controller, terminal = pty.openpty()
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kb_mcp",
            "check",
            "-v",
            "--site",
            "https://a.invalid",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=terminal,
        env={"HOME": str(home), "PATH": os.environ["PATH"], **variables},
        cwd=home,
    ) as child:
        os.close(terminal)
        said = read_until(controller, b"run.end")
        out, _ = child.communicate()
    os.close(controller)
    assert child.returncode == 0
    assert out == b"accounts.atlassian.site: https://a.invalid\n"
    assert b"run.start" in said
    assert (b"\x1b" in said) is coloured
