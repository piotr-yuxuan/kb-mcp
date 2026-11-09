"""Never logged: no run at debug says or leaves a secret, from the site to the agent (plan 020).

Plan 020's "Never logged". ``fetch`` runs against plan 004's scripted site, signed in by
an API token, then by the session that ``login`` saved; ``embed`` against the scripted
embeddings endpoint; a stdio ``serve``, in a fresh interpreter, answers one ``search``
by meaning. Every run has the token, its account's email and the endpoint's key in its
environment, at debug, and the session file holds a cookie: each secret a sentinel, and
each sent where it belongs, so that a run that never used one proves nothing. The token
and the credential's base64, which the Basic form holds, and the key, which the Bearer
form holds as it is, are then in no file of the scratch home or the data directory, nor
on stdout or stderr; the cookie is in the session file alone. Plan 015's
``tests/test_api_token.py`` holds the same of ``check`` and ``fetch``, and plan
016's ``tests/test_telemetry.py`` of the spans, metrics and records exported.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from mcp.client.stdio import StdioServerParameters

from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from tests.endpoint import Scripted, serving
from tests.test_api_token import CREDENTIAL, EMAIL, HOST, KEY, served
from tests.test_download import SITE, FakeSite
from tests.test_observed import said
from tests.test_serve import talk

if TYPE_CHECKING:
    import httpx
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

ROOT = Path(__file__).parents[1]
ADDRESS = "tests@example.invalid"
SENTINEL = "token-sentinel-2b7d"
ENCODED = base64.b64encode(f"{ADDRESS}:{SENTINEL}".encode()).decode()
API_KEY = "key-sentinel-6c1f"
COOKIE = "cookie-sentinel-4e9a"
# What no file, stdout nor stderr may hold: the Basic form holds the base64, and the
# Bearer form the key as it is.
SECRETS = (SENTINEL, ENCODED, API_KEY)
ENVIRONMENT = {EMAIL: ADDRESS, CREDENTIAL: SENTINEL, KEY: API_KEY}


@dataclass
class Keyed(Scripted):
    """The scripted endpoint, noting the Authorization header of each request."""

    authorisations: list[str | None] = field(default_factory=list)

    @override
    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Note the header, then answer as the scripted endpoint does."""
        self.authorisations.append(request.headers.get("authorization"))
        return super().__call__(request)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a scratch home, no waiting between requests, and the secrets in the environment."""
    scratch = tmp_path / "home"
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(scratch))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    return scratch


def found(content: bytes) -> list[str]:
    """Give each secret that ``content`` holds."""
    return [secret for secret in SECRETS if secret.encode() in content]


def left(folder: Path) -> dict[Path, bytes]:
    """Give each file under ``folder``, by its path, with what it holds."""
    return {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}


def test_no_run_at_debug_says_or_leaves_a_secret(
    home: Path, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Fetch by token, then by session, index, embed, then serve: each secret used, none shown.

    The site's one attached file that fails makes each fetch exit 1. The files are read
    after the first fetch too, as the second replaces its run report, both made within
    one second. The server, at debug too, may reach the endpoint's port alone; what it
    sends on stdout, the protocol, and its stderr, a file, are read as the in-process
    runs' are.
    """
    data = tmp_path / "data"
    session = data / "session" / COOKIES
    write_cookies(session, [{"name": "tenant.session.token", "value": COOKIE, "domain": HOST}])
    sent = served(monkeypatch, FakeSite().handle)
    endpoint = Keyed()
    with serving(endpoint) as url:
        config = tmp_path / "config.toml"
        config.write_text(
            f'model = "tiny"\nembedding_url = {json.dumps(url)}\n'
            f'[accounts.atlassian]\nsite = "{SITE}"\n'
            '[sources.confluence]\nspaces = ["MFS"]\n[sources.jira]\nprojects = ["PRB"]\n'
            "[rerank]\nenabled = false\n",  # no reranking server here
            "utf-8",
        )
        options = ["--config", str(config), "--data-dir", str(data), "-vv"]
        assert main(["fetch", "--yes", "--since", "2026-10-02", *options]) == ExitStatus.FAILED
        assert main(["prepare", "--yes", *options]) == ExitStatus.OK
        by_token, files_by_token = list(sent), left(tmp_path)
        with monkeypatch.context() as session_alone:
            session_alone.delenv(CREDENTIAL)
            assert main(["fetch", "--yes", *options]) == ExitStatus.FAILED
        assert main(["index", "--yes", *options]) == ExitStatus.OK
        assert main(["embed", "--yes", *options]) == ExitStatus.OK
        port = int(url.rpartition(":")[2].partition("/")[0])
        given = {"ports": [port], "limit": 1.0, "report": str(tmp_path / "report.json")}
        command = StdioServerParameters(
            command=sys.executable,
            args=["-m", "tests.guarded", json.dumps({**given, "arguments": ["serve", *options]})],
            env={"HOME": str(home), **ENVIRONMENT},
            cwd=ROOT,
        )
        with (tmp_path / "serve.err").open("w", encoding="utf-8") as errlog:
            received, _, results = talk(command, [("search", {"query": "fresh page"})], errlog)
    assert any(request.headers.get("authorization") == f"Basic {ENCODED}" for request in by_token)
    assert any(COOKIE in request.headers.get("cookie", "") for request in sent[len(by_token) :])
    assert endpoint.authorisations
    assert set(endpoint.authorisations) == {f"Bearer {API_KEY}"}
    assert [result["isError"] for result in results] == [False]
    assert "Ranked by words alone" not in json.dumps(results)
    out, err = capsys.readouterr()
    served_err = (tmp_path / "serve.err").read_text("utf-8")
    assert {("debug", "http.get"), ("debug", "http.post")} <= set(said(err))
    assert ("debug", "serve.call") in said(served_err)
    # The protocol's messages, as the client received them, values included.
    sinks = {"stdout": out, "stderr": err, "protocol": repr(received)}
    leaked = {sink: found(shown.encode()) for sink, shown in sinks.items()}
    assert {sink: secrets for sink, secrets in leaked.items() if secrets} == {}
    assert [sink for sink, shown in sinks.items() if COOKIE in shown] == []
    for files in (files_by_token, left(tmp_path)):
        assert {path: found(content) for path, content in files.items() if found(content)} == {}
        assert [path for path, content in files.items() if COOKIE.encode() in content] == [session]


@pytest.mark.parametrize(
    ("case", "named"),
    [
        (
            ({"KB_MCP_ACCOUNTS__ATLASSIAN__SITE": SENTINEL}, "", []),
            "accounts.atlassian.site (KB_MCP_ACCOUNTS__ATLASSIAN__SITE)",
        ),
        (
            ({}, f'[accounts.atlassian]\nsite = "{SENTINEL}"\n', []),
            "accounts.atlassian.site (config.toml)",
        ),
        (({}, "", ["--site", SENTINEL]), "accounts.atlassian.site (--site)"),
        (
            ({"KB_MCP_EMBEDDING_URL": API_KEY}, "", []),
            "embedding_url (KB_MCP_EMBEDDING_URL)",
        ),
    ],
)
def test_a_setting_refused_with_a_secret_as_its_value_does_not_echo_it(
    home: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    case: tuple[dict[str, str], str, list[str]],
    named: str,
) -> None:
    """A secret pasted where a setting goes: refused by its name and layer, never its value.

    By a variable, the settings file or a flag, at debug: ``case`` holds the variables,
    the file's text and the flags. Nothing under the scratch home holds it: a run
    refused before it starts has no log file.
    """
    variables, written, flags = case
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    config = home.parent / "config.toml"
    config.write_text(written, "utf-8")
    options = ["--config", str(config), "--data-dir", str(home.parent / "data"), "-vv", *flags]
    assert main(["fetch", "--yes", *options]) == ExitStatus.REFUSED
    out, err = capsys.readouterr()
    assert ("error", "settings.refused") in said(err)
    assert f"{named}: " in err
    assert found((out + err).encode()) == []
    assert [path for path, content in left(home).items() if found(content)] == []
