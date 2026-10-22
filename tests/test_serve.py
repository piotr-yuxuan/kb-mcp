"""The MCP server, started as agents start it: the command with no arguments, over stdio."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.message import SessionMessage
from mcp_types import JSONRPCError, JSONRPCResponse, TextContent, jsonrpc_message_adapter

from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.search.app.indexing import Embedding, build_index
from tests.answers import TOOLS, estimate, parts
from tests.endpoint import Scripted, serving, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture

BAD_SETTINGS = 2
STANDING = 1500  # estimated tokens of the instructions and the tool listing together
WAIT = 30  # seconds for one answer of the server
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
sys.argv = ["atlassian-offline-mcp"]
runpy.run_module("atlassian_offline_mcp", run_name="__main__", alter_sys=True)
"""
ROOT = Path(__file__).parents[1]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Make a scratch home whose settings name a data directory with an index."""
    home, data = tmp_path / "home", tmp_path / "data"
    (home / ".config" / "atlassian-offline-mcp").mkdir(parents=True)
    settings = home / ".config" / "atlassian-offline-mcp" / "config.toml"
    settings.write_text(f"data_dir = {json.dumps(str(data))}\n", encoding="utf-8")
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
            command=sys.executable, args=["-m", "atlassian_offline_mcp"], env={"HOME": str(home)}
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


def test_stdout_holds_protocol_messages_and_no_socket_opens(home: Path) -> None:
    """Through the SDK's own pipes, every line is JSON-RPC and every request is answered.

    The transport hands on a line that is not a protocol message as an exception, which
    a client session would only log. The server dies at any use of the network.
    """
    received: list[object] = []

    async def exchange() -> None:
        command = StdioServerParameters(
            command=sys.executable, args=["-c", GUARDED], env={"HOME": str(home)}
        )
        async with stdio_client(command) as (read, write):

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
            listing = await ask({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert sorted(tool["name"] for tool in listing["tools"]) == TOOLS
            calls = [
                ("search", {"query": "kafka"}),
                ("read", {"ref": "196845"}),
                ("browse", {"project": "PROJ"}),
                ("status", {}),
            ]
            for number, (name, arguments) in enumerate(calls, 3):
                params = {"name": name, "arguments": arguments}
                call = {"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": params}
                result = await ask(call)
                assert result["isError"] is False
                assert "structuredContent" not in result

    anyio.run(exchange)
    assert [item for item in received if not isinstance(item, SessionMessage)] == []


def test_refused_settings_exit_before_serving(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """A data directory in a synchronised folder exits 2, without reading stdin."""
    dropbox = tmp_path / "Dropbox" / "data"
    config = str(tmp_path / "none.toml")
    assert main(["serve", "--config", config, "--data-dir", str(dropbox)]) == BAD_SETTINGS
    assert "settings refused: data_dir: under a Dropbox folder" in capsys.readouterr().err


def test_a_hybrid_search_answers_by_meaning_over_stdio_offline(tmp_path: Path) -> None:
    """Meaning finds a page without the query's words, reaching the endpoint and no other.

    The server may connect to the scripted endpoint's port alone. Once the endpoint is
    stopped, the next server answers by words and says why.
    """
    home, data = tmp_path / "home", tmp_path / "data"
    (home / ".config" / "atlassian-offline-mcp").mkdir(parents=True)
    settings = home / ".config" / "atlassian-offline-mcp" / "config.toml"
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
            f'search_mode = "hybrid"\nembedding_url = {json.dumps(url)}\n',
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
    settings = home / ".config" / "atlassian-offline-mcp" / "config.toml"
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
