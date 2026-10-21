"""The ``atlassian-offline-mcp`` command: it finds its subcommands and runs one."""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp import commands

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments, run the chosen subcommand, and return its exit status."""
    parser = argparse.ArgumentParser(
        prog="atlassian-offline-mcp",
        description="An offline mirror of Confluence and Jira Cloud, served over MCP.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")
    # A module whose name begins with _ is shared by commands, not one of them.
    found = sorted(module.name for module in pkgutil.iter_modules(commands.__path__))
    for name in (name for name in found if not name.startswith("_")):
        importlib.import_module(f"{commands.__name__}.{name}").register(subparsers)
    # Agents start the command with no arguments, which serves MCP over stdio.
    arguments = parser.parse_args(list(sys.argv[1:] if argv is None else argv) or ["serve"])
    return int(arguments.run(arguments))
