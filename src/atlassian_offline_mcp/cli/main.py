"""The ``atlassian-offline-mcp`` command: it declares every subcommand and runs one.

The parser is built from ``cli.options`` alone, which is light, so that ``--help``
starts fast; the entry and the chosen run are imported once the arguments are parsed.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from typing import TYPE_CHECKING, override

from atlassian_offline_mcp.cli import options

if TYPE_CHECKING:
    from collections.abc import Sequence

# The entry that loads the settings and runs the chosen subcommand.
ENTRY = "atlassian_offline_mcp.cli.commands._shared"


class Version(argparse.Action):
    """``--version``: the installed package's version, read from its metadata when asked.

    Reading it costs as much as building the parser, which every completion does.
    """

    @override
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        """Print the program's name and version, and exit 0."""
        metadata = importlib.import_module("importlib.metadata")
        sys.stdout.write(f"{parser.prog} {metadata.version('atlassian-offline-mcp')}\n")
        parser.exit()


def parser(
    parser_class: type[argparse.ArgumentParser] = argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """Return the command's parser, of this class, with every subcommand declared."""
    program = parser_class(
        prog="atlassian-offline-mcp",
        description="An offline mirror of Confluence and Jira Cloud, served over MCP.",
    )
    program.add_argument(
        "--version", action=Version, nargs=0, default=argparse.SUPPRESS, help="show the version"
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
