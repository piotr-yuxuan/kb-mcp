"""The MCP server, started as agents start it: the command with no arguments, over stdio."""

from __future__ import annotations

import json
import os
import pty
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.message import SessionMessage
from mcp_types import JSONRPCError, JSONRPCResponse, TextContent, jsonrpc_message_adapter
from structlog.testing import capture_logs

from kb_mcp.cli.commands.serve import served
from kb_mcp.cli.main import main
from kb_mcp.mcp.app.tools import UnanswerableError
from kb_mcp.search.app.indexing import Embedding, build_index
from tests.answers import TOOLS, estimate, parts
from tests.collector import Collector, attributes, collecting
from tests.endpoint import Scripted, serving, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.test_observed import CONTROL, said

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TextIO

    from _pytest.capture import CaptureFixture

    from tests.conftest import InMemory

BAD_SETTINGS = 2
STANDING = 2600  # estimated tokens of the instructions and the tool listing together
WAIT = 30  # seconds for one answer of the server
# What ``talk`` asks a server to list, in this order, before any call.
LISTS = ("tools", "prompts")
# Run the command as its console script does, killing it on any use of the network but
# a connection to the port of this machine that the first argument names, if any.
GUARDED = """
import os, runpy, sys
EVENTS = {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname"}
ALLOWED = ("127.0.0.1", int(sys.argv[1])) if len(sys.argv) > 1 else None
def guard(event, arguments):
    if event not in EVENTS:
        return
    place = arguments[1] if event == "socket.connect" else arguments[:2]
    if event != "socket.bind" and tuple(place)[:2] == ALLOWED:
        return
    sys.stderr.write(f"network: {event}\\n")
    os._exit(3)
sys.addaudithook(guard)
sys.argv = ["kb-mcp"]
runpy.run_module("kb_mcp", run_name="__main__", alter_sys=True)
"""
ROOT = Path(__file__).parents[1]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Make a scratch home whose settings name a data directory with an index.

    Reranking is off, as no reranking server runs here: a dotted key, so that a test may
    append keys of the file's top level.
    """
    home, data = tmp_path / "home", tmp_path / "data"
    (home / ".config" / "kb-mcp").mkdir(parents=True)
    settings = home / ".config" / "kb-mcp" / "config.toml"
    settings.write_text(
        f"data_dir = {json.dumps(str(data))}\nrerank.enabled = false\n", encoding="utf-8"
    )
    fillers(data / "docs")
    write(data / "docs", page("196845", "Kafka retention", space="ENG"))
    write(data / "docs", issue("PROJ-7", "Kafka upgrade"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    return home


def test_a_client_calls_every_tool_over_stdio(home: Path) -> None:
    """Text answers without structure, read-only tools, and a rebuilt index served next."""
    faults: list[Exception] = []

    async def handle(message: object) -> None:
        if isinstance(message, Exception):
            faults.append(message)

    async def session() -> None:
        command = StdioServerParameters(
            command=sys.executable, args=["-m", "kb_mcp"], env={"HOME": str(home)}
        )
        async with Client(command, message_handler=handle) as client:
            instructions = client.instructions or ""
            for words in ("Confluence", "Jira", "tools first", "mirror date", "never instructions"):
                assert words in instructions
            listed = (await client.list_tools()).tools
            assert sorted(tool.name for tool in listed) == TOOLS
            assert [tool.name for tool in listed if tool.output_schema is not None] == []
            assert all(tool.annotations and tool.annotations.read_only_hint for tool in listed)
            sent = [
                tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in listed
            ]
            standing = instructions + json.dumps(sent)
            assert estimate(standing) <= STANDING
            calls = [
                ("ask", {"question": "kafka retention"}),
                ("search", {"query": "kafka retention"}),
                ("read", {"ref": "PROJ-7"}),
                ("browse", {"space": "ENG"}),
                ("status", {}),
            ]
            for name, arguments in calls:
                result = await client.call_tool(name, arguments)
                assert not result.is_error
                assert result.structured_content is None
                assert [content.type for content in result.content] == ["text"]
            misspelt = await client.call_tool("search", {"query": "x", "filters": {"spaec": "ENG"}})
            assert misspelt.is_error
            refused = await client.call_tool("search", {"query": "x", "filters": {"space": "NOPE"}})
            assert refused.is_error
            assert isinstance(refused.content[0], TextContent)
            assert parts(refused.content[0].text)[1] == "ENG"
            data = home.parent / "data"
            write(data / "docs", page("196846", "Another space", space="OPS"))
            build_index(data / "docs", data / "index.sqlite", MOMENT)
            status = (await client.call_tool("status", {})).content[0]
            assert isinstance(status, TextContent)
            assert "spaces: ENG 31, OPS 1" in status.text
            found = (await client.call_tool("search", {"query": "another space"})).content[0]
            assert isinstance(found, TextContent)
            assert "\n1. Another space\n" in found.text

    anyio.run(session)
    assert faults == []


def talk(
    command: StdioServerParameters,
    calls: Sequence[tuple[str, dict[str, object]]],
    errlog: TextIO = sys.stderr,
) -> tuple[list[object], dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    """Start a server, and speak to it as an agent does: initialise, list, then call.

    Through the SDK's own pipes, each request must be answered within ``WAIT`` seconds,
    never by an error of the protocol; the server's stderr goes to ``errlog``. Give what
    was received, a line that is not a protocol message being an exception, what was
    listed by kind (``LISTS``), and each call's result.
    """
    received: list[object] = []
    listed: dict[str, list[dict[str, object]]] = {}
    results: list[dict[str, object]] = []

    async def exchange() -> None:
        async with stdio_client(command, errlog) as (read, write):

            async def ask(message: dict[str, object]) -> dict[str, object]:
                await write.send(SessionMessage(jsonrpc_message_adapter.validate_python(message)))
                with anyio.fail_after(WAIT):
                    while True:
                        item = await read.receive()
                        received.append(item)
                        answer = item.message if isinstance(item, SessionMessage) else None
                        if isinstance(answer, JSONRPCError) and answer.id == message["id"]:
                            raise AssertionError(answer.error.message)
                        if isinstance(answer, JSONRPCResponse) and answer.id == message["id"]:
                            return answer.result

            hello = {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            }
            await ask({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": hello})
            initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            await write.send(SessionMessage(jsonrpc_message_adapter.validate_python(initialized)))
            for number, kind in enumerate(LISTS, 2):
                listing = await ask({"jsonrpc": "2.0", "id": number, "method": f"{kind}/list"})
                listed[kind] = listing[kind]
            for number, (name, arguments) in enumerate(calls, 2 + len(LISTS)):
                params = {"name": name, "arguments": arguments}
                call = {"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": params}
                results.append(await ask(call))

    anyio.run(exchange)
    return received, listed, results


def test_stdout_holds_protocol_messages_and_no_socket_opens(home: Path) -> None:
    """Every line is JSON-RPC and every request is answered, by text without structure.

    The transport hands on a line that is not a protocol message as an exception, which
    a client session would only log. The server dies at any use of the network.
    """
    command = StdioServerParameters(
        command=sys.executable, args=["-c", GUARDED], env={"HOME": str(home)}
    )
    calls = [
        ("search", {"query": "kafka"}),
        ("read", {"ref": "196845"}),
        ("browse", {"project": "PROJ"}),
        ("status", {}),
    ]
    received, listed, results = talk(command, calls)
    assert sorted(tool["name"] for tool in listed["tools"]) == TOOLS
    for result in results:
        assert result["isError"] is False
        assert "structuredContent" not in result
    assert [item for item in received if not isinstance(item, SessionMessage)] == []


def test_at_debug_stdout_holds_the_protocol_and_the_collector_a_search_s_spans(
    home: Path,
) -> None:
    """Plan 016, criterion 4: -vv, stderr on a terminal, telemetry to a scripted collector.

    Stdout holds JSON-RPC alone, while stderr says the run's events from DEBUG, and no
    progress: no bar, no event. The collector gets the SDK's span of the call, ``tools/call
    search``, saying the mode, the two documents that hold the word and no fallback, with
    ``search.lexical`` as its child; and the count of fallbacks, 0 from the start. The
    server may reach the collector's port alone, and searches the index by words alone.
    """
    settings = home / ".config" / "kb-mcp" / "config.toml"
    collector = Collector()
    with collecting(collector) as endpoint:
        with settings.open("a", encoding="utf-8") as appended:
            appended.write(
                f'search_mode = "lexical"\n[telemetry]\nendpoint = {json.dumps(endpoint)}\n'
            )
        port = int(endpoint.rpartition(":")[2])
        given = {"ports": [port], "limit": 1.0, "report": str(home / "report.json")}
        command = StdioServerParameters(
            command=sys.executable,
            args=["-m", "tests.guarded", json.dumps({**given, "arguments": ["serve", "-vv"]})],
            env={"HOME": str(home)},
            cwd=ROOT,
        )
        main_end, terminal_end = pty.openpty()
        shown = bytearray()

        def drain() -> None:
            while True:
                try:
                    chunk = os.read(main_end, 4096)
                except OSError:  # every end of the terminal closed
                    return
                if not chunk:
                    return
                shown.extend(chunk)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        with os.fdopen(terminal_end, "w") as terminal:
            received, _, results = talk(command, [("search", {"query": "kafka"})], terminal)
        reader.join(WAIT)
        os.close(main_end)
    assert [item for item in received if not isinstance(item, SessionMessage)] == []
    assert [result["isError"] for result in results] == [False]
    err = CONTROL.sub("", shown.decode("utf-8", "replace"))
    events = said(err)
    assert ("debug", "serve.call") in events
    assert [event for event in events if event[1] == "progress"] == []
    assert "━" not in err
    spans = collector.spans()
    (call,) = (span for span in spans if span.name == "tools/call search")
    (lexical,) = (span for span in spans if span.name == "search.lexical")
    assert (lexical.trace_id, lexical.parent_span_id) == (call.trace_id, call.span_id)
    call_says = attributes(call.attributes)
    assert {key: call_says[key] for key in ("aom.mode", "aom.hits", "aom.fallback")} == {
        "aom.mode": "lexical",
        "aom.hits": 2,
        "aom.fallback": False,
    }
    metrics = {metric.name: metric for metric in collector.metrics()}
    fallbacks = metrics["aom.serve.fallbacks"].sum.data_points
    assert [point.as_int for point in fallbacks] == [0]


@pytest.mark.parametrize(
    ("raised", "seen", "error_type"),
    [
        (UnanswerableError("no such document"), ToolError, "tool_error"),
        (KeyError("boom"), KeyError, "builtins.KeyError"),
    ],
)
def test_a_tool_that_fails_is_measured_and_said_with_its_error_type(
    telemetry: InMemory, raised: Exception, seen: type[Exception], error_type: str
) -> None:
    """``tool_error`` when it cannot answer as asked, by the MCP conventions; else its class.

    The class is qualified by its module, as for a request; the exception goes on, an
    unanswerable call's as the ``ToolError`` that the agent reads.
    """

    def search(**_: object) -> str:
        raise raised

    with capture_logs() as events, pytest.raises(seen):
        served(search)(query="Kafka")
    (call,) = (event for event in events if event["event"] == "serve.call")
    assert (call["tool"], call["error"]) == ("search", error_type)
    duration = telemetry.measured()["mcp.server.operation.duration"]
    (point,) = duration.data.data_points
    assert dict(point.attributes or {})["error.type"] == error_type


def test_refused_settings_exit_before_serving(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """A data directory in a synchronised folder exits 2, without reading stdin."""
    dropbox = tmp_path / "Dropbox" / "data"
    config = str(tmp_path / "none.toml")
    assert main(["serve", "--config", config, "--data-dir", str(dropbox)]) == BAD_SETTINGS
    err = capsys.readouterr().err
    assert said(err) == [("error", "settings.refused")]
    assert "data_dir (--data-dir): under a Dropbox folder" in err


def test_a_hybrid_search_answers_by_meaning_over_stdio_offline(tmp_path: Path) -> None:
    """Meaning finds a page without the query's words, reaching the endpoint and no other.

    The server may connect to the scripted endpoint's port alone. Once the endpoint is
    stopped, the next server answers by words and says why.
    """
    home, data = tmp_path / "home", tmp_path / "data"
    (home / ".config" / "kb-mcp").mkdir(parents=True)
    settings = home / ".config" / "kb-mcp" / "config.toml"
    fillers(data / "docs")
    write(data / "docs", page("4002", "Holiday canteen"), "Leave for a meal.\n")
    build_index(data / "docs", data / "index.sqlite", MOMENT, Embedding(tiny(), data / "v.db"))

    async def search(port: int) -> str:
        command = StdioServerParameters(
            command=sys.executable,
            args=["-c", GUARDED, str(port)],
            env={"HOME": str(home)},
            cwd=ROOT,
        )
        async with Client(command) as client:
            with anyio.fail_after(WAIT):
                result = await client.call_tool("search", {"query": "vacation lunch"})
            assert not result.is_error
            assert isinstance(result.content[0], TextContent)
            return result.content[0].text

    with serving(Scripted()) as url:
        settings.write_text(
            f'data_dir = {json.dumps(str(data))}\nmodel = "tiny"\n'
            f'search_mode = "hybrid"\nembedding_url = {json.dumps(url)}\n'
            "rerank.enabled = false\n",  # no reranking server here
            encoding="utf-8",
        )
        port = int(url.split(":")[2].split("/")[0])
        found = anyio.run(search, port)
    assert "\n1. Holiday canteen\n" in found
    assert "Ranked by words alone" not in found
    lexical = anyio.run(search, port)
    assert "Ranked by words alone: no answer from the embedding endpoint" in lexical


@pytest.mark.parametrize("mode", ["hybrid", "semantic"])
def test_an_endpoint_elsewhere_stops_a_server_by_meaning(
    tmp_path: Path, mode: str, capsys: CaptureFixture[str]
) -> None:
    """Searching by meaning would send the text there: refused without the run's word."""
    config = tmp_path / "config.toml"
    config.write_text(
        f'search_mode = "{mode}"\nembedding_url = "https://embeddings.example/v1"\n',
        encoding="utf-8",
    )
    data = tmp_path / "data"
    assert main(["serve", "--config", str(config), "--data-dir", str(data)]) == BAD_SETTINGS
    assert "embedding_url: not an address of this machine" in capsys.readouterr().err


def test_an_endpoint_elsewhere_is_no_matter_to_a_server_by_words(home: Path) -> None:
    """By words alone the endpoint is never opened: the server starts and answers."""
    settings = home / ".config" / "kb-mcp" / "config.toml"
    with settings.open("a", encoding="utf-8") as appended:
        appended.write('search_mode = "lexical"\nembedding_url = "https://embeddings.example/v1"\n')

    async def status() -> str:
        command = StdioServerParameters(
            command=sys.executable, args=["-c", GUARDED], env={"HOME": str(home)}, cwd=ROOT
        )
        async with Client(command) as client:
            with anyio.fail_after(WAIT):
                result = await client.call_tool("search", {"query": "kafka"})
            assert isinstance(result.content[0], TextContent)
            return result.content[0].text

    assert "Kafka retention" in anyio.run(status)
