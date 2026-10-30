"""What a run says on stderr before it acts, in a scratch home.

The values that it ignores; for a command that writes, its summary and the command to copy.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import select
import shlex
import subprocess
import sys
from functools import reduce
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from kb_mcp.cli.commands import login as login_command
from kb_mcp.cli.commands import model as model_command
from kb_mcp.cli.commands._shared import enter
from kb_mcp.cli.domain.command_line import command_line
from kb_mcp.cli.domain.summary import values_of
from kb_mcp.cli.main import main, parser
from kb_mcp.cli.options.index import by_words_alone
from kb_mcp.config.domain.settings import DEFAULT_MODEL
from kb_mcp.observability.app.observed import early
from kb_mcp.sources.registry import SOURCES
from tests.endpoint import nothing_listening
from tests.test_settings import user_log_folder

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Loaded

SITE = "https://sandbox.example.invalid"
# The variables of the email, the API token and the embedding endpoint's key.
EMAIL = "KB_MCP_EMAIL"
CREDENTIAL = "KB_MCP_API_TOKEN"
KEY = "KB_MCP_EMBEDDING_API_KEY"
SECRETS = {CREDENTIAL: "token-sentinel-4d1c", KEY: "key-sentinel-9a7e"}
UNKNOWN = "KB_MCP_UNKNOWN"
WAIT = 30  # seconds for the server to answer and stop
# The modules that run the commands that write, by plan 015.
WRITING = ("download", "evaluate", "index", "login", "mirror")
# Each command that writes, with options of its own, as given on its command line.
OWN_OPTIONS = {
    "download": ["--space", "ENG", "--space", "OPS", "--since", "7d", "--max-file-mb", "5"],
    "mirror": [],
    "index": ["--allow-remote-embeddings"],
    "eval": ["golden.yaml", "--model", "tiny", "--model", "qwen3-embedding:0.6b"],
    "login": ["--chrome", "chrome", "--keep-extensions"],
}
# What the command to copy never carries, by plan 015: the output's options and the
# question's.
EXCLUDED = {"--yes", "-y", "--dry-run", "-q", "-v", "-vv", "--log-level", "--format", "--summary"}


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

    for module in WRITING:
        monkeypatch.setattr(importlib.import_module(f"kb_mcp.cli.commands.{module}"), "run", run)
    return recorded


@pytest.mark.parametrize("summary", ["short", "detailed"])
def test_login_says_that_it_ignores_the_email_and_the_token(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], summary: str
) -> None:
    """It signs in in a browser: each is named once with its layer, never with its value.

    Neither is among the settings that its summary shows.
    """
    monkeypatch.setattr(login_command, "login", lambda *_, **__: None)
    monkeypatch.setenv(EMAIL, "someone@example.invalid")
    monkeypatch.setenv(CREDENTIAL, SECRETS[CREDENTIAL])
    options = ["--yes", "--config", str(home / "none.toml"), "--site", SITE, "--summary", summary]
    assert main(["login", *options]) == 0
    out, err = capsys.readouterr()
    ignored = [line for line in err.splitlines() if line.startswith("ignored: ")]
    assert ignored == [
        f"ignored: email ({EMAIL}): login signs in in a browser",
        f"ignored: api_token ({CREDENTIAL}): login signs in in a browser",
    ]
    assert "someone@example.invalid" not in out + err
    assert SECRETS[CREDENTIAL] not in out + err


@pytest.mark.parametrize(
    "command", [["doctor"], ["download", "--yes", "--site", SITE, "--space", "ENG"]]
)
@pytest.mark.usefixtures("runs")
def test_an_email_without_a_token_is_ignored(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], command: list[str]
) -> None:
    """Without a token the browser's session signs in; with one, the email is not ignored.

    The download's run is left out: what is ignored is said before it.
    """
    monkeypatch.setenv("PATH", str(home))
    monkeypatch.setenv(EMAIL, "someone@example.invalid")
    options = [*command, "--config", str(home / "none.toml")]
    main(options)
    ignored = f"ignored: email ({EMAIL}): without an API token, the browser's session signs in\n"
    assert ignored in capsys.readouterr().err
    monkeypatch.setenv(CREDENTIAL, SECRETS[CREDENTIAL])
    main(options)
    err = capsys.readouterr().err
    assert "ignored: email" not in err
    assert SECRETS[CREDENTIAL] not in err


@pytest.mark.parametrize(
    ("variables", "sign_in"),
    [
        ({}, "the session saved by login"),
        ({EMAIL: "someone@example.invalid", **SECRETS}, "an API token"),
    ],
)
@pytest.mark.usefixtures("runs")
def test_a_download_s_summary_says_how_it_signs_in(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    variables: dict[str, str],
    sign_in: str,
) -> None:
    """By the token when one is set, else by the session saved; and never the token itself."""
    for variable, value in variables.items():
        monkeypatch.setenv(variable, value)
    options = ["--yes", "--config", str(home / "none.toml"), "--site", SITE, "--space", "ENG"]
    assert main(["download", *options]) == 0
    err = capsys.readouterr().err
    assert f"\n  sign-in: {sign_in}\n" in err.split("kb-mcp download")[0]
    assert not any(secret in err for secret in SECRETS.values())


@pytest.mark.parametrize(
    ("given", "rule"),
    [
        ([], "period: since each target's last fetch; the last 7 days for one never fetched"),
        (["--since", "7d"], "period: from --since"),
    ],
)
@pytest.mark.usefixtures("runs")
def test_a_download_s_summary_says_where_its_windows_start(
    home: Path, capsys: CaptureFixture[str], given: list[str], rule: str
) -> None:
    """The rule in words, before the run reads the store: from --since, or the last fetch."""
    options = ["--yes", "--config", str(home / "none.toml"), "--site", SITE, "--space", "ENG"]
    assert main(["download", *options, *given]) == 0
    err = capsys.readouterr().err
    assert f"\n  {rule}\n" in err.split("kb-mcp download")[0]


def test_an_index_by_words_alone_ignores_the_model_and_the_endpoint_given(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Those that a layer gave: the file's model, the variable's key; not the default address."""
    (home / "data" / "docs").mkdir(parents=True)
    config = home / "config.toml"
    config.write_text('model = "tiny"\nsearch_mode = "lexical"\n', "utf-8")
    monkeypatch.setenv(KEY, SECRETS[KEY])
    assert main(["index", "--yes", "--config", str(config), "--data-dir", str(home / "data")]) == 0
    out, err = capsys.readouterr()
    ignored = [line for line in err.splitlines() if line.startswith("ignored: ")]
    assert ignored == [
        "ignored: model (config.toml): the lexical mode embeds nothing",
        f"ignored: embedding_api_key ({KEY}): the lexical mode embeds nothing",
    ]
    assert SECRETS[KEY] not in out + err


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_an_index_by_meaning_applies_its_model_and_endpoint(mode: str) -> None:
    """Outside the lexical mode the index embeds, with the model at the endpoint."""
    assert by_words_alone(None, {"search_mode": mode}) == {}


@pytest.mark.parametrize(
    ("given", "why"),
    [
        ((["eval", "--yes", "golden.yaml"], ["--model", "other:1b"]), "replaced by --model"),
        ((["model", "check"], ["other:1b"]), "replaced by the model named"),
    ],
)
@pytest.mark.usefixtures("runs")
def test_a_model_named_on_the_command_line_replaces_the_setting(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    given: tuple[list[str], list[str]],
    why: str,
) -> None:
    """The run uses ``eval``'s --model and ``model check``'s name; without them, the setting."""
    monkeypatch.setattr(model_command, "run", lambda *_: (0, None))
    monkeypatch.chdir(home)
    (home / "golden.yaml").write_text("", "utf-8")
    config = home / "config.toml"
    config.write_text('model = "tiny"\n', "utf-8")
    command, named = given
    assert main([*command, "--config", str(config)]) == 0
    assert "ignored" not in capsys.readouterr().err
    assert main([*command, *named, "--config", str(config)]) == 0
    assert f"ignored: model (config.toml): {why}\n" in capsys.readouterr().err


@pytest.mark.usefixtures("runs")
def test_the_summary_says_why_the_run_does_not_apply_a_setting_whatever_its_layer(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """At its default too, where no value is said to be ignored.

    ``eval``'s --model replaces the model; an index by words alone embeds nothing.
    """
    monkeypatch.chdir(home)
    (home / "golden.yaml").write_text("", "utf-8")
    none = str(home / "none.toml")
    assert main(["eval", "--yes", "golden.yaml", "--config", none, "--model", "other:1b"]) == 0
    err = capsys.readouterr().err
    assert f"\n  model: {DEFAULT_MODEL} (not applied: replaced by --model)\n" in err
    assert "ignored: " not in err
    monkeypatch.setenv("KB_MCP_SEARCH_MODE", "lexical")
    assert main(["index", "--yes", "--config", none]) == 0
    summary = capsys.readouterr().err.split("kb-mcp index")[0]
    marked = [
        line.strip().partition(": ")[0]
        for line in summary.splitlines()
        if line.endswith(" (not applied: the lexical mode embeds nothing)")
    ]
    assert marked == ["model", "chunking", "embedding_url", "embedding_api_key"]


def test_settings_that_the_command_never_reads_are_ignored_in_detail_alone(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The doctor reads no model and no key: said under --summary detailed, else left out."""
    monkeypatch.setenv("PATH", str(home))
    config = home / "config.toml"
    config.write_text('model = "tiny"\n', "utf-8")
    monkeypatch.setenv(KEY, SECRETS[KEY])
    main(["doctor", "--config", str(config)])
    assert "ignored" not in capsys.readouterr().err
    main(["doctor", "--config", str(config), "--summary", "detailed"])
    err = capsys.readouterr().err
    assert "ignored: model (config.toml): not read by doctor\n" in err
    assert f"ignored: embedding_api_key ({KEY}): not read by doctor\n" in err
    assert SECRETS[KEY] not in err


def test_a_variable_that_names_no_setting_is_said_by_every_command_but_completion(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The doctor names it, -q aside; ``completion``, which reads no setting, says nothing."""
    monkeypatch.setenv("PATH", str(home))
    monkeypatch.setenv(UNKNOWN, "1")
    main(["doctor", "--config", str(home / "none.toml")])
    assert f"ignored: {UNKNOWN}: names no setting\n" in capsys.readouterr().err
    main(["doctor", "--config", str(home / "none.toml"), "-q"])
    assert capsys.readouterr().err == ""
    assert main(["completion"]) == 0
    assert capsys.readouterr().err == ""


def test_serve_says_what_it_ignores_on_stderr_and_answers_its_first_line(home: Path) -> None:
    """The protocol alone goes to stdout, its first answer to the first line of stdin.

    stdin is a pipe, as an agent gives it: the server asks nothing, and reads nothing
    before the protocol does. The settings come from the environment, so that the
    child's arguments are literal.
    """
    (home / "data" / "docs").mkdir(parents=True)
    hello = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"},
        },
    }
    environment = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "KB_MCP_DATA_DIR": str(home / "data"),
        UNKNOWN: "1",
    }
    with subprocess.Popen(
        [sys.executable, "-m", "kb_mcp", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        cwd=home,
    ) as child:
        assert child.stdin is not None
        assert child.stdout is not None
        child.stdin.write(f"{json.dumps(hello)}\n")
        child.stdin.flush()
        assert select.select([child.stdout], [], [], WAIT)[0]
        first = json.loads(child.stdout.readline())
        rest, err = child.communicate(timeout=WAIT)
    assert child.returncode == 0
    assert (first["jsonrpc"], first["id"]) == ("2.0", 1)
    assert "serverInfo" in first["result"]
    assert all(json.loads(line)["jsonrpc"] == "2.0" for line in rest.splitlines())
    assert f"ignored: {UNKNOWN}: names no setting\n" in err


def test_a_command_that_writes_says_what_it_reads_what_it_ignores_then_its_command(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """The settings it reads and their values, in detail their layers; -q says nothing.

    In detail, the entry's own follow, which it reads for every command.
    """
    config = home / "config.toml"
    config.write_text(f'site = "{SITE}"\nmodel = "tiny"\n', "utf-8")
    monkeypatch.setenv(UNKNOWN, "1")
    data = (home / "data").resolve()
    options = ["mirror", "--yes", "--config", str(config), "--data-dir", str(data)]
    command = (
        "kb-mcp mirror \\\n"
        f"  --config {shlex.quote(str(config))} \\\n"
        f"  --data-dir {shlex.quote(str(data))} \\\n"
        f"  --site {SITE}\n"
    )
    assert main(options) == 0
    assert capsys.readouterr().err == (
        "mirror, with these settings:\n"
        f"  site: {SITE}\n"
        f"  data_dir: {data}\n"
        f"ignored: {UNKNOWN}: names no setting\n"
        f"{command}"
    )
    assert main([*options, "--summary", "detailed"]) == 0
    assert capsys.readouterr().err == (
        "mirror, with these settings:\n"
        f"  site: {SITE} [config.toml]\n"
        f"  data_dir: {data} [--data-dir]\n"
        f"  logs.dir: {user_log_folder(home.resolve())} [default]\n"
        "  telemetry.endpoint: (not set) [default]\n"
        f"ignored: {UNKNOWN}: names no setting\n"
        "ignored: model (config.toml): not read by mirror\n"
        f"{command}"
    )
    assert main([*options, "-q"]) == 0
    assert capsys.readouterr().err == ""
    assert len(runs) == len(["short", "detailed", "quiet"])


@pytest.mark.parametrize("command", ["mirror", "index"])
@pytest.mark.usefixtures("runs")
def test_the_entry_s_own_settings_given_are_read_and_listed_in_detail_alone(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], command: str
) -> None:
    """Every run logs into logs.dir, and reads telemetry.endpoint: neither is ignored.

    Given by a layer, each is listed with it under --summary detailed, after the
    command's own settings, and the run's log file is there; the short summary names
    neither.
    """
    logs = (home / "logs").resolve()
    config = home / "config.toml"
    config.write_text(f'[logs]\ndir = "{logs}"\n', "utf-8")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    options = [command, "--yes", "--config", str(config)]
    assert main([*options, "--summary", "detailed"]) == 0
    said = capsys.readouterr().err
    assert "ignored" not in said
    listed = said.split(f"kb-mcp {command} \\\n")[0].splitlines()
    # A setting's line ends with its layer; the command's own lines, if any, follow.
    assert [line for line in listed if line.endswith("]")][-2:] == [
        f"  logs.dir: {logs} [config.toml]",
        "  telemetry.endpoint: (not set) [OTEL_SDK_DISABLED]",
    ]
    assert [path.name.partition("-")[0] for path in logs.iterdir()] == [command]
    assert main(options) == 0
    said = capsys.readouterr().err
    assert "logs.dir" not in said
    assert "telemetry.endpoint" not in said


@pytest.mark.parametrize("variable", ["OTEL_EXPORTER_OTLP_ENDPOINT", "KB_MCP_TELEMETRY__ENDPOINT"])
@pytest.mark.parametrize("command", [["index", "--yes"], ["check"]], ids=["index", "check"])
@pytest.mark.usefixtures("runs")
def test_every_command_says_that_telemetry_is_on_and_what_turned_it_on(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    variable: str,
    command: list[str],
) -> None:
    """Whatever layer sets the endpoint, one line names it on stderr, at every level but -q.

    OpenTelemetry's variable, which other programs share, may turn telemetry on unseen,
    as may the setting's: a command that writes says so in its summary, one that only
    reads alike, without a summary. Without an endpoint, no such line. Nothing listens
    there.
    """
    options = [*command, "--config", str(home / "none.toml")]
    assert main(options) == 0
    assert not any(line.startswith("telemetry") for line in capsys.readouterr().err.splitlines())
    with nothing_listening() as url:
        endpoint = url.removesuffix("/v1")
        monkeypatch.setenv(variable, endpoint)
        for level in ([], ["-v"], ["-vv"], ["--log-level", "error"]):
            assert main([*options, *level]) == 0
            said = capsys.readouterr().err.splitlines()
            assert said.count(f"telemetry: on, to {endpoint} ({variable})") == 1
        assert main([*options, "-q"]) == 0
        assert "telemetry: on" not in capsys.readouterr().err


@pytest.mark.usefixtures("runs")
def test_the_level_error_leaves_out_the_values_ignored_alone(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """They are warnings; the summary and the command are what the run is, said still.

    Only -q leaves those out. A command that only reads then says nothing.
    """
    monkeypatch.setenv(UNKNOWN, "1")
    warning = f"ignored: {UNKNOWN}: names no setting\n"
    options = ["index", "--yes", "--config", str(home / "none.toml")]
    assert main(options) == 0
    said = capsys.readouterr().err
    assert said.startswith("index, with these settings:\n")
    assert "kb-mcp index \\\n" in said
    assert warning in said
    assert main([*options, "--log-level", "error"]) == 0
    assert capsys.readouterr().err == said.replace(warning, "")
    checked = ["check", "--config", str(home / "none.toml")]
    assert main(checked) == 0
    assert capsys.readouterr().err == warning
    assert main([*checked, "--log-level", "error"]) == 0
    assert capsys.readouterr().err == ""


def test_a_command_s_described_lines_end_its_summary(
    home: Path, capsys: CaptureFixture[str], runs: list[tuple[argparse.Namespace, Loaded]]
) -> None:
    """They are its own function's, of the arguments and the settings' values by path."""

    def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
        return (f"mirrors {settings['site']}", f"as {arguments.command.name}")

    given = ["mirror", "--yes", "--config", str(home / "none.toml"), "--site", SITE]
    arguments = parser().parse_args(given)
    arguments.command = dataclasses.replace(arguments.command, described=described)
    with early():
        assert enter(arguments, given, SOURCES) == 0
    summary = capsys.readouterr().err.split("kb-mcp mirror")[0]
    assert summary.endswith(
        f"  data_dir: {(home / 'kb-mcp').resolve()}\n  mirrors {SITE}\n  as mirror\n"
    )
    assert len(runs) == 1


def test_the_command_to_copy_is_preceded_by_an_empty_list_that_no_flag_can_say(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """A variable emptied the file's projects: the command, run again, would read the file."""
    config = home / "config.toml"
    config.write_text('[sources.jira]\nprojects = ["PLAT"]\n', "utf-8")
    variable = "KB_MCP_SOURCES__JIRA__PROJECTS"
    monkeypatch.setenv(variable, "[]")
    options = ["--yes", "--config", str(config), "--site", SITE, "--space", "ENG"]
    assert main(["download", *options]) == 0
    err = capsys.readouterr().err
    said, _, copied = err.partition("kb-mcp download")
    assert said.endswith(
        f"not in the command: sources.jira.projects ({variable}): empty, which --project"
        " cannot say\n"
    )
    assert "--project" not in copied
    [(_, loaded)] = runs
    assert loaded.settings.sources.jira.projects == ()


# A settings file whose table of Jira is empty, its one line commented out.
EMPTY_TABLE = '[sources.jira]\n# projects = ["PLAT"]\n'


@pytest.mark.parametrize(
    "layers",
    [
        ("", {"KB_MCP_SOURCES__JIRA__PROJECTS": "[]"}, []),
        ("[sources.jira]\nprojects = []\n", {}, []),
        (EMPTY_TABLE, {}, []),
        (EMPTY_TABLE, {"KB_MCP_SOURCES": "{}"}, []),
        (EMPTY_TABLE, {}, ["--project", "PRB"]),
    ],
)
@pytest.mark.usefixtures("runs")
def test_an_empty_list_that_replaced_no_value_given_is_neither_ignored_nor_named(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    layers: tuple[str, dict[str, str], list[str]],
) -> None:
    """The command, run again, reads the same projects: the file's, or the default.

    An empty table's settings are at their defaults, which no layer wrote: a stronger
    value replaces none of them. ``layers`` are the file's text, the variables and the
    flags.
    """
    text, variables, flags = layers
    config = home / "config.toml"
    config.write_text(text, "utf-8")
    for variable, value in variables.items():
        monkeypatch.setenv(variable, value)
    options = ["--yes", "--config", str(config), "--site", SITE, "--space", "ENG", *flags]
    assert main(["download", *options]) == 0
    err = capsys.readouterr().err
    assert "ignored: " not in err
    assert "not in the command: " not in err


@pytest.mark.usefixtures("runs")
def test_the_command_to_copy_is_followed_by_the_settings_that_no_flag_sets(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Run again elsewhere, the command would index by the defaults: each is named, with its layer.

    With every setting at its default but the file's path, which --config carries,
    nothing is named.
    """
    options = ["index", "--yes", "--config", str(home / "none.toml")]
    assert main(options) == 0
    assert "not in the command" not in capsys.readouterr().err
    mode, model = "KB_MCP_SEARCH_MODE", "KB_MCP_MODEL"
    monkeypatch.setenv(mode, "semantic")
    monkeypatch.setenv(model, "foo")
    assert main(options) == 0
    command = f"kb-mcp index \\\n  --config {shlex.quote(str(home / 'none.toml'))}\n"
    _, found, after = capsys.readouterr().err.partition(command)
    assert found
    assert [line.rpartition(": ")[0] for line in after.splitlines()] == [
        f"not in the command: model ({model})",
        f"not in the command: search_mode ({mode})",
    ]


@pytest.mark.usefixtures("runs")
def test_the_command_to_copy_names_no_setting_that_the_run_does_not_apply(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """``eval``'s --model replaces the file's model, and the command carries it."""
    monkeypatch.chdir(home)
    (home / "golden.yaml").write_text("", "utf-8")
    config = home / "config.toml"
    config.write_text('model = "tiny"\n', "utf-8")
    options = ["eval", "--yes", "golden.yaml", "--config", str(config)]
    assert main(options) == 0
    assert "not in the command: model (config.toml): " in capsys.readouterr().err
    assert main([*options, "--model", "other:1b"]) == 0
    assert "not in the command: model" not in capsys.readouterr().err


@pytest.mark.parametrize("name", sorted(OWN_OPTIONS))
def test_the_command_to_copy_gives_each_option_it_carries_the_run_s_value(
    name: str,
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    runs: list[tuple[argparse.Namespace, Loaded]],
) -> None:
    """Split by shlex and run with no settings' variable nor file, it gives the same values.

    The settings come from the file (site, projects), the environment (data_dir) and the
    flags (spaces); each that the command reads and a flag sets is carried, whatever its
    layer. Another option is carried when not at its default. The output's options are
    not, nor the email, the secrets, nor the model, which no flag sets; ``eval``'s
    --model, an option of its own, is.
    """
    monkeypatch.chdir(home)
    (home / "golden.yaml").write_text("", "utf-8")
    config = home / "config.toml"
    config.write_text(
        f'site = "{SITE}"\nmodel = "tiny"\n[sources.jira]\nprojects = ["PRB"]\n', "utf-8"
    )
    given = {
        "KB_MCP_DATA_DIR": "~/from-variable",
        EMAIL: "someone@example.invalid",
        **SECRETS,
    }
    for variable, value in given.items():
        monkeypatch.setenv(variable, value)
    output = ["--yes", "-v", "--summary", "detailed", "--format", "json"]
    main([name, "--config", str(config), *output, *OWN_OPTIONS[name]])
    err = capsys.readouterr().err
    assert not any(secret in err for secret in SECRETS.values())
    [(first_arguments, first)] = runs
    copied = command_line(
        first_arguments,
        values_of(first),
        first.layers,
        first.replaced,
        lambda path: path.expanduser().absolute(),
    )
    assert copied.command in err
    assert "someone@example.invalid" not in copied.command
    # The shell removes a backslash and the newline after it, then splits as shlex does.
    argv = shlex.split(copied.command.replace("\\\n", ""))
    assert argv[:2] == ["kb-mcp", name]
    assert not EXCLUDED & set(argv)
    config.unlink()
    for variable in given:
        monkeypatch.delenv(variable)
    elsewhere = home / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    main([*argv[1:], "--yes"])
    [_, (second_arguments, second)] = runs
    command = first_arguments.command
    for setting in set(command.flags.values()) & set(command.reads):
        path = setting.split(".")
        assert reduce(getattr, path, second.settings) == reduce(getattr, path, first.settings)
    for action in command.actions:
        if action.dest in command.flags:
            continue
        was, is_now = (getattr(each, action.dest) for each in (first_arguments, second_arguments))
        if was == action.default:
            assert not set(action.option_strings) & set(argv)
        if isinstance(was, Path):  # given under the home, the first run's directory
            was = home / was
        assert is_now == was
    # The file's model, which no flag sets, is left to the settings of the run to come.
    assert second.settings.model != first.settings.model


@pytest.mark.usefixtures("runs")
def test_the_command_to_copy_carries_each_path_absolute(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A path given relative would point elsewhere once the command runs from elsewhere.

    The settings take the data directory absolute alone.
    """
    monkeypatch.chdir(home)
    paths = {"--config": "cfg/c.toml", "--chrome": "bin/chrome"}
    given = [item for option, path in paths.items() for item in (option, path)]
    assert main(["login", "--yes", "--site", SITE, *given]) == 0
    err = capsys.readouterr().err
    argv = shlex.split(err[err.index("kb-mcp login") :].replace("\\\n", ""))
    assert {option: argv[argv.index(option) + 1] for option in paths} == {
        option: str(home.absolute() / path) for option, path in paths.items()
    }
