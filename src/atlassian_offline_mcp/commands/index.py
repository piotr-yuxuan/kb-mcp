"""``index``: build the search index from the Markdown mirror, with the setting's model."""

from __future__ import annotations

import contextlib
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.embedding import ModelError, connect, prefixes
from atlassian_offline_mcp.app.indexing import Embedding, MirrorMissingError, build_index
from atlassian_offline_mcp.commands._options import (
    add_embedding_options,
    add_settings_options,
    open_endpoint,
    settings_of,
)
from atlassian_offline_mcp.domain.settings import SettingsError

if TYPE_CHECKING:
    import argparse

BAD_SETTINGS = 2
WORDS_ALONE = 'or set search_mode = "lexical" to index by words alone'


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``index`` to the command."""
    parser = subparsers.add_parser("index", help="build the search index from the mirror")
    add_settings_options(parser)
    add_embedding_options(parser)
    parser.set_defaults(run=run)


def progress(done: int, total: int) -> None:
    """Say how many of the pieces to embed are done."""
    sys.stderr.write(f"embedded {done} of {total} pieces\n")


def run(arguments: argparse.Namespace) -> int:
    """Build the index; exit 1 when a file or a piece was left out, or nothing was built.

    By words alone in the lexical mode, which never calls the embedding endpoint. In the
    other modes the endpoint must answer with the setting's model; when it does not,
    the index in place stays, with its vectors.
    """
    try:
        settings = settings_of(arguments)
        opened = None if settings.search_mode == "lexical" else open_endpoint(arguments, settings)
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return BAD_SETTINGS
    with opened or contextlib.nullcontext():
        try:
            embedder = None if opened is None else connect(opened, settings.model)
            embedding = (
                None if embedder is None else Embedding(embedder, settings.vectors, progress)
            )
            report = build_index(settings.docs, settings.index, datetime.now(UTC), embedding)
        except ModelError as error:
            sys.stderr.write(f"index not built: {error}; {WORDS_ALONE}\n")
            return 1
        except (MirrorMissingError, OSError) as error:
            sys.stderr.write(f"index not built: {error}\n")
            return 1
    for path, reason in report.skipped:
        sys.stderr.write(f"skipped {path}: {reason}\n")
    for path in report.unembedded:
        sys.stderr.write(f"not embedded: a piece of {path}, which the model refused\n")
    types = ", ".join(f"{name}: {count}" for name, count in sorted(report.types.items()))
    sys.stdout.write(
        f"indexed {report.types.total()} documents ({types or 'none'}),"
        f" {report.sections} sections, into {settings.index}\n"
    )
    if embedding is not None:
        unknown = "" if prefixes(settings.model) else " (no prefixes known: texts as they are)"
        sys.stdout.write(
            f"{report.pieces} pieces by meaning, with {settings.model}{unknown};"
            f" {report.embedded} embedded now, the others kept\n"
        )
    if report.skipped:
        sys.stderr.write(f"{len(report.skipped)} files skipped: the index lacks them\n")
    return 1 if report.skipped or report.unembedded else 0
