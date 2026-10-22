"""``download``'s declaration; ``cli.commands.download`` runs it."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import add_output_options, add_settings_options
from atlassian_offline_mcp.kernel.content import PROJECT_KEY, SPACE_KEY

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_MAX_FILE_MB = 50


def key_of(pattern_name: str) -> Callable[[str], str]:
    """Return an argparse type that accepts a space key or a project key."""
    pattern = SPACE_KEY if pattern_name == "space" else PROJECT_KEY

    def check(text: str) -> str:
        if not pattern.fullmatch(text):
            message = f"not a {pattern_name} key: {text!r}"
            raise argparse.ArgumentTypeError(message)
        return text

    return check


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``download`` to the command."""
    parser = subparsers.add_parser(
        "download", help="download what changed in a period, with its files"
    )
    flags = add_settings_options(parser)
    add_output_options(parser)
    parser.add_argument(
        "--space", action="append", type=key_of("space"), help="a space key; repeat for more"
    )
    parser.add_argument(
        "--project", action="append", type=key_of("project"), help="a project key; repeat"
    )
    parser.add_argument(
        "--since", help="7d, 6mo, or an ISO date; by default, the start of what is covered"
    )
    parser.add_argument("--back", help="reach this much further back (6mo, 1y), or all")
    parser.add_argument("--until", help="an ISO date or time, excluded; by default, now")
    parser.add_argument(
        "--plan", action="store_true", help="say what a run would fetch, and fetch nothing"
    )
    parser.add_argument(
        "--max-file-mb", type=int, default=DEFAULT_MAX_FILE_MB, help="the largest file kept"
    )
    flags = {**flags, "space": "sources.confluence.spaces", "project": "sources.jira.projects"}
    parser.set_defaults(
        command=Command("download", "atlassian_offline_mcp.cli.commands.download", flags)
    )
