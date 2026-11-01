# PYTHON_ARGCOMPLETE_OK
"""The ``kb-mcp`` command: it declares every subcommand and runs one.

The parser is built from ``cli.options`` alone, which is light, so that ``--help`` and
shell completion, which runs the command at every Tab, start fast; what observes the run,
the entry and the chosen run are imported once the arguments are parsed, and for a run
that is not observed, such as ``completion``, which shells run at each start, the run
alone. The first line lets argcomplete's global completion find the command.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from typing import TYPE_CHECKING, override

import argcomplete

from kb_mcp.cli import options
from kb_mcp.cli.domain.command import PROGRAM
from kb_mcp.kernel.exit_status import MEANINGS
from kb_mcp.sources.registry import SOURCES, refuse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.sources.declaration import Declared

# The entry that loads the settings and runs the chosen subcommand.
ENTRY = "kb_mcp.cli.commands._shared"
# What observes a run: its logs, from the start on stderr, never on stdout.
OBSERVED = "kb_mcp.observability.app.observed"
# The commands that plan 031 removed, whose log files, which hold titles and queries, a
# run still removes once past their 30 days.
RETIRED = ("download", "mirror", "sync")


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
        sys.stdout.write(f"{parser.prog} {metadata.version('kb-mcp')}\n")
        parser.exit()


def parser(
    parser_class: type[argparse.ArgumentParser] = argparse.ArgumentParser,
    sources: Sequence[Declared] = SOURCES,
) -> argparse.ArgumentParser:
    """Return the command's parser, of this class, with every subcommand declared.

    Each declaration is given the registry, ``sources``, ``SOURCES`` unless a test gives
    one of its own, as ``fetch``'s takes its sources and their options. Its help ends
    with who asks before acting, the subcommands whose declaration says they write, and
    every exit status with what it means. What it parses holds ``commands``, every
    subcommand's name and each of ``RETIRED``, whose old log files a run removes, and
    ``sources``, the registry, which a run and its declaration's checks read.
    """
    program = parser_class(
        prog=PROGRAM,
        description=(
            "Knowledge base MCP: an offline mirror of Confluence and Jira Cloud, served over MCP."
        ),
    )
    program.add_argument(
        "--version", action=Version, nargs=0, default=argparse.SUPPRESS, help="show the version"
    )
    subparsers = program.add_subparsers(required=True, metavar="command")
    # A module whose name begins with _ is shared by declarations, not one of them.
    found = sorted(module.name for module in pkgutil.iter_modules(options.__path__))
    for name in (name for name in found if not name.startswith("_")):
        importlib.import_module(f"{options.__name__}.{name}").register(subparsers, sources)
    program.set_defaults(
        commands=frozenset({*subparsers.choices, *RETIRED}), sources=tuple(sources)
    )
    writing = ", ".join(
        name
        for name, declared in subparsers.choices.items()
        if declared.get_default("command").writes
    )
    program.epilog = (
        f"The commands that write under the data directory ({writing}) first say what they"
        " will do, with the command to copy, then ask; --yes, or --dry-run where taken,"
        " runs them without asking, and with no terminal to ask on, they are refused. Exit"
        " statuses: "
        + "; ".join(f"{status.value} {meaning}" for status, meaning in MEANINGS.items())
        + "."
    )
    return program


def main(argv: Sequence[str] | None = None, sources: Sequence[Declared] = SOURCES) -> int:
    """Parse the arguments, run the chosen subcommand, and return its exit status.

    ``sources`` is the registry, ``SOURCES`` unless a test gives one of its own: first
    refused, raising ValueError, when it breaks a rule of every registry, then handed to
    the parser and to the entry, whose settings hold each of its sources' tables. When
    the shell asks for completions, argcomplete answers them and exits instead, as
    --help and --version do. A command that is not ``observed``, ``completion``, is run
    as they are: its run alone is imported, and writes its output. Else, from then on,
    events and records go to stderr from WARNING, never to stdout, until the run's
    settings are read.
    """
    refuse(sources)
    program = parser(sources=sources)
    argcomplete.autocomplete(program)
    # Agents start the command with no arguments, which serves MCP over stdio.
    given = list(sys.argv[1:] if argv is None else argv) or ["serve"]
    arguments = program.parse_args(given)
    if not arguments.command.observed:
        return importlib.import_module(arguments.command.run).run(arguments)
    with importlib.import_module(OBSERVED).early():
        return importlib.import_module(ENTRY).enter(arguments, given, sources)
