"""What a run says on stderr before it acts: the values that it ignores, in a scratch home."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.cli.commands import login as login_command
from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.cli.options.index import by_words_alone

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

SITE = "https://sandbox.example.invalid"
# The variables of the email, the API token and the embedding endpoint's key.
EMAIL = "ATLASSIAN_OFFLINE_MCP_EMAIL"
CREDENTIAL = "ATLASSIAN_OFFLINE_MCP_API_TOKEN"
KEY = "ATLASSIAN_OFFLINE_MCP_EMBEDDING_API_KEY"
SECRETS = {CREDENTIAL: "token-sentinel-4d1c", KEY: "key-sentinel-9a7e"}
UNKNOWN = "ATLASSIAN_OFFLINE_MCP_UNKNOWN"
WAIT = 30  # seconds for the server to answer and stop


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give each test a scratch home directory, so that none reads or writes the user's."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    return scratch


def test_login_says_that_it_ignores_the_email_and_the_token(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """It signs in in a browser: each is named with its layer, never with its value."""
    monkeypatch.setattr(login_command, "login", lambda *_, **__: None)
    monkeypatch.setenv(EMAIL, "someone@example.invalid")
    monkeypatch.setenv(CREDENTIAL, SECRETS[CREDENTIAL])
    assert main(["login", "--config", str(home / "none.toml"), "--site", SITE]) == 0
    out, err = capsys.readouterr()
    assert f"ignored: email ({EMAIL}): login signs in in a browser\n" in err
    assert f"ignored: api_token ({CREDENTIAL}): login signs in in a browser\n" in err
    assert SECRETS[CREDENTIAL] not in out + err
    assert "someone@example.invalid" not in out + err


@pytest.mark.parametrize("command", [["doctor"], ["download", "--space", "ENG"]])
def test_an_email_without_a_token_is_ignored(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], command: list[str]
) -> None:
    """Without a token the browser's session signs in; with one, the email is not ignored."""
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


def test_an_index_by_words_alone_ignores_the_model_and_the_endpoint_given(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Those that a layer gave: the file's model, the variable's key; not the default address."""
    (home / "data" / "docs").mkdir(parents=True)
    config = home / "config.toml"
    config.write_text('model = "tiny"\n', "utf-8")
    monkeypatch.setenv(KEY, SECRETS[KEY])
    assert main(["index", "--config", str(config), "--data-dir", str(home / "data")]) == 0
    out, err = capsys.readouterr()
    assert "ignored: model (config.toml): the lexical mode embeds nothing\n" in err
    assert f"ignored: embedding_api_key ({KEY}): the lexical mode embeds nothing\n" in err
    assert "embedding_url" not in err
    assert SECRETS[KEY] not in out + err


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_an_index_by_meaning_applies_its_model_and_endpoint(mode: str) -> None:
    """Outside the lexical mode the index embeds, with the model at the endpoint."""
    assert by_words_alone(None, {"search_mode": mode}) == {}


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
        "ATLASSIAN_OFFLINE_MCP_DATA_DIR": str(home / "data"),
        UNKNOWN: "1",
    }
    with subprocess.Popen(
        [sys.executable, "-m", "atlassian_offline_mcp", "serve"],
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
