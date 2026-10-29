"""The MCP SDK's client over stdio: start a server, list what it says, or call one tool.

The evaluation's only use of the SDK. Each use starts the server as a child process,
with this process's environment, so that it reads the same settings; leaving the use,
on success, failure, deadline or interrupt, stops it. No subprocess call is made here:
the SDK's client owns the child.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError
from mcp_types import TextContent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence


class ServerError(Exception):
    """A server that did not start, or stopped before it answered; the message says how."""


@dataclass(frozen=True)
class Listing:
    """What a server lists: its instructions, and each tool's name, description and schema."""

    instructions: str
    tools: list[dict[str, object]]


@dataclass(frozen=True)
class Answered:
    """A tool's answer, as text, and whether the tool refused the call."""

    text: str
    refused: bool


def finished(session: Callable[[], Awaitable[None]]) -> None:
    """Run a session with a server to its end.

    Raise TimeoutError when its deadline passed, and ServerError when the server failed,
    such as one that exits before it answers.
    """
    failure = ""
    timed_out = False
    try:
        anyio.run(session)
    except* TimeoutError:
        timed_out = True
    except* (MCPError, OSError) as group:
        failure = type(group.exceptions[0]).__name__
    if timed_out:
        raise TimeoutError
    if failure:
        message = f"the server did not answer ({failure})"
        raise ServerError(message)


def started(server: Sequence[str]) -> Client:
    """Give a client that starts the server by this command line, with this environment."""
    command = StdioServerParameters(command=server[0], args=list(server[1:]), env=dict(os.environ))
    return Client(command)


def listed(server: Sequence[str], deadline_s: float) -> Listing:
    """Start the server, and give its instructions and tools as it lists them.

    Raises TimeoutError past ``deadline_s`` seconds, and ServerError.
    """
    found: list[Listing] = []

    async def session() -> None:
        with anyio.fail_after(deadline_s):
            async with started(server) as client:
                tools = (await client.list_tools()).tools
                fields = {"name", "description", "input_schema"}
                dumped = [
                    tool.model_dump(mode="json", by_alias=True, exclude_none=True, include=fields)
                    for tool in tools
                ]
                found.append(Listing(client.instructions or "", dumped))

    finished(session)
    return found[0]


def called(
    server: Sequence[str], tool: str, arguments: dict[str, object], deadline_s: float
) -> Answered:
    """Start the server, call one tool, and give its answer as text.

    Raises TimeoutError past ``deadline_s`` seconds, the server then stopped, and
    ServerError.
    """
    found: list[Answered] = []

    async def session() -> None:
        with anyio.fail_after(deadline_s):
            async with started(server) as client:
                result = await client.call_tool(tool, arguments)
                text = "\n".join(
                    part.text for part in result.content if isinstance(part, TextContent)
                )
                found.append(Answered(text, result.is_error))

    finished(session)
    return found[0]
