"""``serve``'s declaration; ``cli.commands.serve`` runs it."""

from __future__ import annotations

import argparse

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    endpoint_by_meaning,
)
from atlassian_offline_mcp.kernel.tools import TOOLS, Tool


def tool_names(value: str) -> tuple[Tool, ...]:
    """Read --tools: names of tools, comma-separated, in the server's order whatever theirs."""
    names = {name.strip() for name in value.split(",")}
    if not names <= set(TOOLS):
        message = f"one or more of {', '.join(TOOLS)}, comma-separated"
        raise argparse.ArgumentTypeError(message)
    return tuple(tool for tool in TOOLS if tool in names)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``serve`` to the command."""
    parser = subparsers.add_parser("serve", help="serve the mirror over MCP on stdio")
    actions, flags = add_settings_options(parser)
    add_output_options(parser, result=False)
    remote = add_embedding_options(parser)
    tools = parser.add_argument(
        "--tools",
        type=tool_names,
        default=TOOLS,
        metavar=",".join(TOOLS),
        help="the tools to serve, comma-separated; by default, every one",
    )
    parser.set_defaults(
        command=Command(
            "serve",
            "atlassian_offline_mcp.cli.commands.serve",
            reads=("data_dir", "search_mode", "embedding_url", "embedding_api_key"),
            flags=flags,
            actions=(*actions, remote, tools),
            refused=endpoint_by_meaning,
            traced=False,
        )
    )
