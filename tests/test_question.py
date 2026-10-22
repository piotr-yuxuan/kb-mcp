"""The question before a command writes: who is asked, and what each answer does.

Terminals are injected as text that says it is one, and once a pseudo-terminal holds the
child's stdin and stderr. Each test has a scratch home.
"""

from __future__ import annotations

import importlib
import io
import os
import pty
import select
import subprocess
import sys
import time
from typing import TYPE_CHECKING, override

import pytest

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.config.domain.settings import Settings
from atlassian_offline_mcp.sources.atlassian.adapters import http
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import COOKIES, write_cookies
from tests.endpoint import Scripted, serving
from tests.test_download import SITE, FakeSite

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from atlassian_offline_mcp.config.domain.settings import Loaded

DECLINED = 1
REFUSED = 2
INTERRUPTED = 130
QUESTION = "Proceed? [y/N] "
REFUSAL = "refused: no terminal to ask on; pass --yes to run without the question\n"
WAIT = 30  # seconds for the child to ask, or to end
# Each command that writes, by plan 015: what it needs besides options to be parsed and
# to pass its declaration's checks, and the module that runs it.
WRITING = {
    "download": (["--site", SITE, "--space", "MFS"], "download"),
    "eval": (["golden.yaml"], "evaluate"),
    "index": ([], "index"),
    "login": (["--site", SITE], "login"),
    "mirror": ([], "mirror"),
}
# An embedding endpoint off this machine, over https and over http.
ELSEWHERE = {"ATLASSIAN_OFFLINE_MCP_EMBEDDING_URL": "https://embeddings.example/v1"}
IN_CLEAR = {"ATLASSIAN_OFFLINE_MCP_EMBEDDING_URL": "http://embeddings.example/v1"}
BY_MEANING = {"ATLASSIAN_OFFLINE_MCP_SEARCH_MODE": "hybrid"}
# What plan 015 refuses without the network, before anything is asked: a command that
# writes and its arguments, the variables set, and what the refusal names.
REFUSED_FIRST = [
    (["download", "--space", "MFS"], {}, "site: not set"),
    (["download", "--site", SITE], {}, "nothing to download"),
    (["download", *WRITING["download"][0], "--max-file-mb", "0"], {}, "--max-file-mb"),
    (["download", *WRITING["download"][0], "--since", "yesterday"], {}, "--since"),
    (["download", *WRITING["download"][0], "--until", "soon"], {}, "--until"),
    (["download", *WRITING["download"][0], "--back", "7x"], {}, "--back"),
    (["login"], {}, "site: not set"),
    (["index"], BY_MEANING | ELSEWHERE, "embedding_url: not an address of this machine"),
    (["index", "--allow-remote-embeddings"], BY_MEANING | IN_CLEAR, "over https only"),
    (["eval", "golden.yaml"], ELSEWHERE, "embedding_url: not an address of this machine"),
]


class Terminal(io.StringIO):
    """A terminal, as a run sees its stdin or its stderr: text that says it is one."""

    @override
    def isatty(self) -> bool:
        return True


class Interrupting(Terminal):
    """A terminal at which the user presses Ctrl-C as soon as a line is read."""

    @override
    def readline(self, size: int | None = -1) -> str:
        raise KeyboardInterrupt


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, so that none reads or writes the user's."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    return scratch


@pytest.fixture
def runs(monkeypatch: MonkeyPatch) -> list[tuple[argparse.Namespace, Loaded]]:
    """Make each command that writes record what its run was given, and do nothing."""
    recorded: list[tuple[argparse.Namespace, Loaded]] = []

    def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[int, None]:
        recorded.append((arguments, loaded))
        return 0, None

    for _, module in WRITING.values():
        monkeypatch.setattr(
            importlib.import_module(f"atlassian_offline_mcp.cli.commands.{module}"), "run", run
        )
    return recorded


def command_line(home: Path, name: str, *more: str) -> list[str]:
    """Give a command's arguments: no settings file, the data in the home, then ``more``."""
    data = ["--data-dir", str(home / "data")]
    return [name, "--config", str(home / "none.toml"), *data, *more, *WRITING[name][0]]


def tree(folder: Path) -> list[str]:
    """List what a folder holds, at any depth, as paths relative to it."""
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))


def given(monkeypatch: MonkeyPatch, stdin: io.StringIO, stderr: io.StringIO) -> None:
    """Make these the run's stdin and stderr."""
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)


@pytest.mark.parametrize("answer", ["y\n", "yes\n", "Y\n", " YES \n"])
def test_on_terminals_yes_lets_the_run_go_on(
    answer: str,
    home: Path,
    monkeypatch: MonkeyPatch,
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """The summary and the command come first, then the question, then the run."""
    stderr = Terminal()
    given(monkeypatch, Terminal(answer), stderr)
    assert main(command_line(home, "mirror")) == 0
    assert len(runs) == 1
    said = stderr.getvalue()
    assert said.startswith("mirror, with these settings:\n")
    assert said.endswith(QUESTION)
    assert f"atlassian-offline-mcp mirror \\\n  --config {home / 'none.toml'}" in said


@pytest.mark.parametrize("answer", ["n\n", "\n", "yess\n", ""])
@pytest.mark.parametrize("name", sorted(WRITING))
def test_on_terminals_any_other_answer_or_none_does_nothing(
    name: str,
    answer: str,
    home: Path,
    monkeypatch: MonkeyPatch,
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """Declined, or at the end of input: "Nothing done.", exit 1, the data as it was."""
    (home / "data").mkdir()
    before = tree(home)
    stderr = Terminal()
    given(monkeypatch, Terminal(answer), stderr)
    assert main(command_line(home, name)) == DECLINED
    assert runs == []
    ended = "" if answer else "\n"
    assert stderr.getvalue().endswith(f"{QUESTION}{ended}Nothing done.\n")
    assert tree(home) == before


def test_ctrl_c_at_the_question_exits_130_having_done_nothing(
    home: Path, monkeypatch: MonkeyPatch, runs: list[tuple[argparse.Namespace, Loaded]]
) -> None:
    """The shell's own status for an interrupted run, and the question's line ended."""
    stderr = Terminal()
    given(monkeypatch, Interrupting(), stderr)
    assert main(command_line(home, "index")) == INTERRUPTED
    assert runs == []
    assert stderr.getvalue().endswith(f"{QUESTION}\n")


@pytest.mark.parametrize("terminals", [(False, False), (True, False), (False, True)])
@pytest.mark.parametrize("name", sorted(WRITING))
def test_without_both_terminals_a_command_that_writes_is_refused(
    name: str,
    terminals: tuple[bool, bool],
    home: Path,
    monkeypatch: MonkeyPatch,
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """A pipe, CI or an agent: the summary, then exit 2 telling to pass --yes; stdin unread.

    ``terminals`` says whether stdin, then stderr, is one.
    """
    (home / "data").mkdir()
    before = tree(home)
    read_from = Terminal("y\n") if terminals[0] else io.StringIO("y\n")
    written_to = Terminal() if terminals[1] else io.StringIO()
    given(monkeypatch, read_from, written_to)
    assert main(command_line(home, name)) == REFUSED
    said = written_to.getvalue()
    assert said.startswith(f"{name}, with these settings:\n")
    assert said.endswith(REFUSAL)
    assert QUESTION not in said
    assert read_from.read() == "y\n"
    assert runs == []
    assert tree(home) == before


def test_quiet_leaves_out_the_summary_of_a_refusal_but_keeps_it_for_a_question(
    home: Path, monkeypatch: MonkeyPatch, runs: list[tuple[argparse.Namespace, Loaded]]
) -> None:
    """-q says the refusal alone; with a question to answer, the summary is still shown."""
    refused = io.StringIO()
    given(monkeypatch, io.StringIO(), refused)
    assert main(command_line(home, "mirror", "-q")) == REFUSED
    assert refused.getvalue() == REFUSAL
    asked = Terminal()
    given(monkeypatch, Terminal("n\n"), asked)
    assert main(command_line(home, "mirror", "-q")) == DECLINED
    assert asked.getvalue().startswith("mirror, with these settings:\n")
    assert QUESTION in asked.getvalue()
    assert runs == []


@pytest.mark.parametrize(
    ("name", "skip"),
    [*((name, "--yes") for name in sorted(WRITING)), ("mirror", "-y"), ("download", "--dry-run")],
)
def test_yes_or_a_dry_run_runs_without_reading_stdin(
    name: str,
    skip: str,
    home: Path,
    monkeypatch: MonkeyPatch,
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """On terminals too: the summary and the command, no question; -q, nothing at all.

    stdin interrupts the run at the first line read, so that a run reading it would exit
    130.
    """
    stderr = Terminal()
    given(monkeypatch, Interrupting(), stderr)
    assert main(command_line(home, name, skip)) == 0
    said = stderr.getvalue()
    assert said.startswith(f"{name}, with these settings:\n")
    assert f"atlassian-offline-mcp {name} \\\n" in said
    assert QUESTION not in said
    assert main(command_line(home, name, skip, "-q")) == 0
    assert stderr.getvalue() == said
    assert len(runs) == len(["said", "quiet"])
    assert getattr(runs[0][0], "dry_run", False) is (skip == "--dry-run")


def test_a_yes_variable_skips_nothing_and_is_said_to_be_ignored(
    home: Path, monkeypatch: MonkeyPatch, runs: list[tuple[argparse.Namespace, Loaded]]
) -> None:
    """Only the flag skips the question: the variable names no setting."""
    monkeypatch.setenv("ATLASSIAN_OFFLINE_MCP_YES", "1")
    asked = Terminal()
    given(monkeypatch, Terminal("n\n"), asked)
    assert main(command_line(home, "mirror")) == DECLINED
    assert "ignored: ATLASSIAN_OFFLINE_MCP_YES: names no setting\n" in asked.getvalue()
    assert QUESTION in asked.getvalue()
    given(monkeypatch, io.StringIO(), io.StringIO())
    assert main(command_line(home, "mirror")) == REFUSED
    assert runs == []


def test_yes_in_the_settings_file_is_refused(
    home: Path, capsys: CaptureFixture[str], runs: list[tuple[argparse.Namespace, Loaded]]
) -> None:
    """Only the flag skips the question: ``yes`` is no setting."""
    config = home / "config.toml"
    config.write_text("yes = true\n", "utf-8")
    assert main(["mirror", "--config", str(config)]) == REFUSED
    assert "settings refused: yes (config.toml): not a setting" in capsys.readouterr().err
    assert runs == []


@pytest.mark.parametrize("terminal", [True, False])
def test_a_download_declined_or_refused_asks_the_site_nothing(
    home: Path, monkeypatch: MonkeyPatch, *, terminal: bool
) -> None:
    """Nothing is spent before the question: no request, no file, the session as it was."""
    chosen = Settings(site=SITE, data_dir=(home / "atlassian-offline-mcp").resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    fake = FakeSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    before = tree(home)
    given(monkeypatch, Terminal("n\n"), Terminal() if terminal else io.StringIO())
    options = ["--site", SITE, "--space", "MFS", "--since", "7d"]
    status = main(["download", "--config", str(home / "none.toml"), *options])
    assert status == (DECLINED if terminal else REFUSED)
    assert fake.asked == []
    assert tree(home) == before


@pytest.mark.parametrize("refusal", REFUSED_FIRST)
def test_what_needs_no_network_is_refused_before_anything_is_asked(
    refusal: tuple[list[str], dict[str, str], str],
    home: Path,
    monkeypatch: MonkeyPatch,
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """On terminals, a yes waiting: exit 2 naming the fault, and no summary nor question.

    stdin is left unread, the run is never reached, and the data is as it was.
    """
    arguments, variables, named = refusal
    for variable, value in variables.items():
        monkeypatch.setenv(variable, value)
    (home / "data").mkdir()
    before = tree(home)
    stdin, stderr = Terminal("y\n"), Terminal()
    given(monkeypatch, stdin, stderr)
    name, *more = arguments
    data = ["--config", str(home / "none.toml"), "--data-dir", str(home / "data")]
    assert main([name, *data, *more]) == REFUSED
    [said] = stderr.getvalue().splitlines()
    assert said.startswith("refused: ")
    assert named in said
    assert stdin.read() == "y\n"
    assert runs == []
    assert tree(home) == before


@pytest.mark.parametrize(
    ("command", "status"), [(["check"], 0), (["doctor"], 1), (["model", "check", "tiny"], 0)]
)
def test_with_stdin_a_pipe_the_commands_that_only_read_run_and_read_none_of_it(
    command: list[str],
    status: int,
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """check, the doctor and model check never ask: their exit is their own, stdin unread.

    The doctor fails offline, without a site or pandoc.
    """
    monkeypatch.setenv("PATH", str(home))
    pipe = io.StringIO("y\n")
    monkeypatch.setattr(sys, "stdin", pipe)
    config = home / "config.toml"
    with serving(Scripted()) as url:
        config.write_text(f'embedding_url = "{url}"\n', "utf-8")
        assert main([*command, "--config", str(config)]) == status
    assert "refused" not in capsys.readouterr().err
    assert pipe.read() == "y\n"


def read_until(terminal: int, wanted: bytes) -> bytes:
    """Read what the child writes on its terminal until it holds ``wanted``, or ends."""
    seen = b""
    deadline = time.monotonic() + WAIT
    while wanted not in seen:
        if not select.select([terminal], [], [], max(0.0, deadline - time.monotonic()))[0]:
            break
        try:
            chunk = os.read(terminal, 1024)
        except OSError:  # EIO on Linux, once the child has closed its end
            break
        if not chunk:
            break
        seen += chunk
    return seen


def test_on_a_pseudo_terminal_no_leaves_the_data_then_yes_builds_the_index(home: Path) -> None:
    """The child asks on its terminal: n does nothing and exits 1; y builds, exit 0.

    The settings come from the environment, so that the child's arguments are literal.
    """
    data = home / "data"
    (data / "docs").mkdir(parents=True)
    environment = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "ATLASSIAN_OFFLINE_MCP_DATA_DIR": str(data),
    }
    outcomes = []
    for answer in (b"n\n", b"y\n"):
        controller, terminal = pty.openpty()
        with subprocess.Popen(
            [sys.executable, "-m", "atlassian_offline_mcp", "index"],
            stdin=terminal,
            stdout=subprocess.PIPE,
            stderr=terminal,
            env=environment,
            cwd=home,
        ) as child:
            os.close(terminal)
            said = read_until(controller, QUESTION.encode())
            os.write(controller, answer)
            said += read_until(controller, b"\0")
            assert child.stdout is not None
            out = child.stdout.read()
        os.close(controller)
        outcomes.append((child.returncode, said, out, tree(data)))
    (declined, asked, nothing, unchanged), (built, _, counts, grown) = outcomes
    assert b"index, with these settings:" in asked
    assert QUESTION.encode() in asked
    assert b"Nothing done." in asked
    assert (declined, nothing, unchanged) == (DECLINED, b"", ["docs"])
    assert (built, counts) == (0, b"documents: 0\nsections: 0\n")
    assert "index.sqlite" in grown
