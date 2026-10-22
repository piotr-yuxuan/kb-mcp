"""``mirror``: write the Markdown mirror from the raw store, offline."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from atlassian_offline_mcp.mirror.app.mirror import mirror
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore

if TYPE_CHECKING:
    import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``mirror`` to the command."""
    parser = subparsers.add_parser("mirror", help="write the Markdown mirror from the raw store")
    add_settings_options(parser)
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> ExitStatus:
    """Mirror; exit 0, 1 when pandoc is missing or something was not mirrored, 2 for bad settings.

    Counts go to standard output; what was not mirrored goes to standard error, by its
    place in the raw store and the reason, never its content.
    """
    try:
        settings = settings_of(arguments)
    except SettingsError as error:
        sys.stderr.write(f"refused: {error}\n")
        return ExitStatus.REFUSED
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        sys.stderr.write(f"{error}\n")
        return ExitStatus.FAILED
    outcome = mirror(RawStore(settings.raw), settings.docs, settings.site, pandoc.markdown)
    sys.stdout.write(
        f"documents: {outcome.documents}\n"
        f"files written: {outcome.changes.written}\n"
        f"files unchanged: {outcome.changes.unchanged}\n"
        f"files removed: {outcome.changes.removed}\n"
    )
    for name, count in sorted(outcome.unsupported.items()):
        sys.stdout.write(f"not shown, {name}: {count}\n")
    for problem in outcome.problems:
        sys.stderr.write(f"not mirrored: {problem.where}: {problem.reason}\n")
    if outcome.problems:
        sys.stderr.write("nothing was removed, since something was not mirrored\n")
    return ExitStatus.FAILED if outcome.problems else ExitStatus.OK
