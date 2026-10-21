"""``index``: build the search index from the Markdown mirror, with the setting's model."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.embedding import ModelError, NotPulledError, load
from atlassian_offline_mcp.app.indexing import Embedding, MirrorMissingError, build_index
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


def progress(done: int, total: int) -> None:
    """Say how many of the pieces to embed are done."""
    sys.stderr.write(f"embedded {done} of {total} pieces\n")


def run(arguments: argparse.Namespace) -> int:
    """Build the index; exit 1 when a file was skipped, the model failed, or nothing built.

    Without the setting's model pulled, the index is built for words alone, and exit 0.
    """
    try:
        settings = settings_of(arguments)
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return BAD_SETTINGS
    embedding, failed = None, False
    try:
        embedding = Embedding(load(settings.model, settings.models), settings.vectors, progress)
    except ModelError as error:
        sys.stderr.write(f"search by meaning off: {error}\n")
        failed = not isinstance(error, NotPulledError)
    try:
        report = build_index(settings.docs, settings.index, datetime.now(UTC), embedding)
    except (MirrorMissingError, OSError, ModelError) as error:
        sys.stderr.write(f"index not built: {error}\n")
        return 1
    for path, reason in report.skipped:
        sys.stderr.write(f"skipped {path}: {reason}\n")
    types = ", ".join(f"{name}: {count}" for name, count in sorted(report.types.items()))
    sys.stdout.write(
        f"indexed {report.types.total()} documents ({types or 'none'}),"
        f" {report.sections} sections, into {settings.index}\n"
    )
    if embedding is not None:
        sys.stdout.write(
            f"{report.pieces} pieces by meaning, with {settings.model};"
            f" {report.embedded} embedded now, the others kept\n"
        )
    if report.skipped:
        sys.stderr.write(f"{len(report.skipped)} files skipped: the index lacks them\n")
    return 1 if report.skipped or failed else 0
