"""The ``atlassian-offline-mcp`` command: it finds its subcommands and runs one."""

from __future__ import annotations

import argparse
import importlib
import pkgutil
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
    for module in sorted(pkgutil.iter_modules(commands.__path__), key=lambda found: found.name):
        importlib.import_module(f"{commands.__name__}.{module.name}").register(subparsers)
    arguments = parser.parse_args(argv)
    return int(arguments.run(arguments))
