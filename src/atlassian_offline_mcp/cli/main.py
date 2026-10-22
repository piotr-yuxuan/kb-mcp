"""The ``atlassian-offline-mcp`` command: it declares every subcommand and runs one.

The parser is built from ``cli.options`` alone, which is light, so that ``--help``
starts fast; the entry and the chosen run are imported once the arguments are parsed.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli import options

if TYPE_CHECKING:
    from collections.abc import Sequence

# The entry that loads the settings and runs the chosen subcommand.
ENTRY = "atlassian_offline_mcp.cli.commands._shared"


def parser(
    parser_class: type[argparse.ArgumentParser] = argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """Return the command's parser, of this class, with every subcommand declared."""
    program = parser_class(
        prog="atlassian-offline-mcp",
        description="An offline mirror of Confluence and Jira Cloud, served over MCP.",
    )
    subparsers = program.add_subparsers(required=True, metavar="command")
    # A module whose name begins with _ is shared by declarations, not one of them.
    found = sorted(module.name for module in pkgutil.iter_modules(options.__path__))
    for name in (name for name in found if not name.startswith("_")):
        importlib.import_module(f"{options.__name__}.{name}").register(subparsers)
    return program


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments, run the chosen subcommand, and return its exit status."""
    # Agents start the command with no arguments, which serves MCP over stdio.
    arguments = parser().parse_args(list(sys.argv[1:] if argv is None else argv) or ["serve"])
    return importlib.import_module(ENTRY).enter(arguments)
