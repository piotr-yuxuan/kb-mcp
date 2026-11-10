"""``serve``: the MCP server over stdio, answering from the index and the embedding endpoint.

This module alone knows the MCP SDK. The tools are the methods of
``mcp.app.tools.Library``, registered as they are, so that their signatures are the
tools' schemas. The SDK traces each message of the protocol; each tool call is measured
here, as the SDK measures none, as ``docs/reference/telemetry/serve.md`` lists it.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import time
from typing import TYPE_CHECKING

import structlog
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.prompts import Prompt
from mcp.server.mcpserver.prompts.base import PromptArgument
from mcp.server.mcpserver.tools import Tool
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, ToolAnnotations
from opentelemetry import metrics

from kb_mcp.cli.commands._embedding import open_endpoint
from kb_mcp.cli.domain.echo import values_of
from kb_mcp.kernel.endpoint import RERANKING
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.names import PROGRAM
from kb_mcp.mcp.app.surface import surface
from kb_mcp.mcp.app.tools import FALLBACKS, Library, UnanswerableError, search_filters
from kb_mcp.search.adapters.embedding import connect
from kb_mcp.search.adapters.model_api import endpoint
from kb_mcp.search.adapters.reranking import SEARCH, rerank
from kb_mcp.search.adapters.sqlite_index import SqliteIndex
from kb_mcp.search.app.meaning import Meaning
from kb_mcp.search.app.reranking import Reranking
from kb_mcp.search.domain.indexes import UnavailableIndexError

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from kb_mcp.config.domain.settings import Loaded

# What people read for the server, beside the name that clients key it by, as MCP
# separates them since its revision of 2025-06-18.
TITLE = "Knowledge base MCP"
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
METER = metrics.get_meter(__name__)
# The buckets of an operation's duration, in seconds, that the MCP conventions advise.
BUCKETS_S = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30, 60, 120, 300)
# How long each tool call took, from the tool's call to its answer, by the MCP
# conventions; how long each answer is, in bytes, by tool.
OPERATION_DURATION = METER.create_histogram(
    "mcp.server.operation.duration",
    unit="s",
    description="MCP request or notification duration as observed on the receiver.",
    explicit_bucket_boundaries_advisory=BUCKETS_S,
)
ANSWER_SIZE = METER.create_histogram(
    "kb_mcp.serve.answer.size", unit="By", description="How long a tool's answer is"
)


def served(method: Callable[..., str], filters: type) -> Callable[..., str]:
    """Wrap a tool so that an unanswerable call reaches the agent with its message, measured.

    Its parameter ``filters``, if it has one, takes ``filters``, which the SDK writes in
    its schema. The SDK shows the agent the message of a ``ToolError`` alone; any other exception
    becomes a bare "Error executing tool". Each call's duration goes in
    ``mcp.server.operation.duration``, an unanswerable one's with the ``error.type``
    ``tool_error``, as the MCP conventions have it, and one that raises any other
    exception, which goes on, with its class, qualified by its module; each answer's
    size, in ``kb_mcp.serve.answer.size``; and ``serve.call`` says at DEBUG the tool, its
    arguments, the error, the seconds and the size.
    """
    name = method.__name__

    @functools.wraps(method)
    def tool(*arguments: object, **options: object) -> str:
        measured = {
            "mcp.method.name": "tools/call",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": name,
        }
        answer, began = "", time.perf_counter()
        try:
            answer = method(*arguments, **options)
        except UnanswerableError as error:
            measured["error.type"] = "tool_error"
            raise ToolError(str(error)) from None
        except Exception as error:
            measured["error.type"] = f"{type(error).__module__}.{type(error).__qualname__}"
            raise
        finally:
            seconds = time.perf_counter() - began
            OPERATION_DURATION.record(seconds, measured)
            structlog.get_logger().debug(
                "serve.call",
                tool=name,
                arguments=options,
                error=measured.get("error.type"),
                seconds=round(seconds, 3),
                size=len(answer.encode()),
            )
        ANSWER_SIZE.record(len(answer.encode()), {"gen_ai.tool.name": name})
        return answer

    signature = inspect.signature(method, eval_str=True)
    tool.__signature__ = signature.replace(
        parameters=[
            each.replace(annotation=filters | None) if each.name == "filters" else each
            for each in signature.parameters.values()
        ]
    )
    return tool


def checking(render: Callable[..., str]) -> Callable[..., str]:
    """Wrap a prompt so that an argument refused reaches the client as invalid params."""

    @functools.wraps(render)
    def prompt(**arguments: str) -> str:
        try:
            return render(**arguments)
        except UnanswerableError as error:
            raise MCPError(INVALID_PARAMS, str(error)) from None

    return prompt


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, None]:
    """Serve the tools named, and the prompts that they allow, until the client closes stdin.

    Their filter ``source`` takes the sources that a prepare takes by default, those that
    keep a store and those configured, then those that the index holds, if it exists. The
    lexical mode
    never opens the embedding endpoint, nor does a server not reranking
    open the reranking server's. The protocol is the output:
    no result is given. ``kb_mcp.serve.fallbacks`` is 0 from the start, so that a chart of
    it has data before any search falls back.
    """
    settings = loaded.settings
    FALLBACKS.add(0, {"kb_mcp.mode": settings.search_mode})
    opened = None if settings.search_mode == "lexical" else open_endpoint(arguments, settings)
    with opened or contextlib.nullcontext(), contextlib.ExitStack() as stack:
        meaning = None if opened is None else Meaning(functools.partial(connect, opened))
        reranking = None
        if settings.rerank.enabled:
            reranker = stack.enter_context(
                endpoint(settings.rerank.url, None, RERANKING, remote_allowed=False)
            )
            score = functools.partial(rerank, reranker, settings.rerank.model, bounds=SEARCH)
            reranking = Reranking(score, settings.rerank.depth)
        index = SqliteIndex(settings.index)
        library = Library(index, settings.docs, meaning, settings.search_mode, reranking)
        offered = surface(library, arguments.tools)
        values = values_of(loaded)
        held: list[str] = []
        with contextlib.suppress(UnavailableIndexError), index.reading() as reader:
            held = sorted(name for name, _ in reader.values("source"))
        configured = [each.name for each in arguments.sources if each.prepared_by_default(values)]
        filters = search_filters(list(dict.fromkeys([*configured, *held])))
        tools = [
            Tool.from_function(
                served(getattr(library, name), filters),
                description=offered.descriptions[name],
                annotations=READ_ONLY,
                structured_output=False,
            )
            for name in offered.tools
        ]
        server = MCPServer(
            PROGRAM,
            title=TITLE,
            instructions=offered.instructions,
            tools=tools,
            log_level="WARNING",
        )
        for prompt in offered.prompts:
            wanted = [
                PromptArgument(name=name, description=said, required=True)
                for name, said in prompt.arguments
            ]
            server.add_prompt(
                Prompt(
                    name=prompt.name,
                    description=prompt.description,
                    arguments=wanted,
                    fn=checking(prompt.render),
                )
            )
        server.run("stdio")
    return ExitStatus.OK, None
