"""``index``: build the search index from the Markdown mirror."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.app.indexing import MirrorMissingError, build_index
from atlassian_offline_mcp.commands._options import add_settings_options, settings_of
from atlassian_offline_mcp.domain.settings import SettingsError

if TYPE_CHECKING:
    import argparse

BAD_SETTINGS = 2


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``index`` to the command."""
    parser = subparsers.add_parser("index", help="build the search index from the mirror")
    add_settings_options(parser)
    parser.set_defaults(run=run)


def run(arguments: argparse.Namespace) -> int:
    """Build the index; exit 1 when a file was skipped or nothing could be built."""
    try:
        settings = settings_of(arguments)
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return BAD_SETTINGS
    try:
        report = build_index(settings.docs, settings.index, datetime.now(UTC))
    except (MirrorMissingError, OSError) as error:
        sys.stderr.write(f"index not built: {error}\n")
        return 1
    for path, reason in report.skipped:
        sys.stderr.write(f"skipped {path}: {reason}\n")
    types = ", ".join(f"{name}: {count}" for name, count in sorted(report.types.items()))
    sys.stdout.write(
        f"indexed {report.types.total()} documents ({types or 'none'}),"
        f" {report.sections} sections, into {settings.index}\n"
    )
    if report.skipped:
        sys.stderr.write(f"{len(report.skipped)} files skipped: the index lacks them\n")
        return 1
    return 0
