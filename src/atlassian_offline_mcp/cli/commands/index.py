"""``index``: build the search index from the Markdown mirror, with the setting's model."""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.commands._embedding import open_endpoint, prefixes_said
from atlassian_offline_mcp.config.domain.settings import SettingsError
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.search.adapters.embedding import ModelError, connect
from atlassian_offline_mcp.search.app.indexing import Embedding, MirrorMissingError, build_index

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from atlassian_offline_mcp.config.domain.settings import Settings
    from atlassian_offline_mcp.kernel.output import Summary
    from atlassian_offline_mcp.search.app.indexing import Report

WORDS_ALONE = 'or set search_mode = "lexical" to index by words alone'


@dataclass(frozen=True)
class Indexed:
    """What a build did, the index it wrote, and the model that embedded, None by words alone."""

    report: Report
    index: Path
    model: str | None


def progress(done: int, total: int) -> None:
    """Say how many of the pieces to embed are done."""
    sys.stderr.write(f"embedded {done} of {total} pieces\n")


def run(arguments: argparse.Namespace, settings: Settings) -> tuple[ExitStatus, Indexed | None]:
    """Build the index; exit 1 when a file or a piece was left out, or nothing was built.

    By words alone in the lexical mode, which never calls the embedding endpoint. In the
    other modes the endpoint must answer with the setting's model; when it does not,
    the index in place stays, with its vectors, and nothing is given.
    """
    try:
        opened = None if settings.search_mode == "lexical" else open_endpoint(arguments, settings)
    except SettingsError as error:
        sys.stderr.write(f"settings refused: {error}\n")
        return ExitStatus.REFUSED, None
    with opened or contextlib.nullcontext():
        try:
            embedder = None if opened is None else connect(opened, settings.model)
            embedding = (
                None if embedder is None else Embedding(embedder, settings.vectors, progress)
            )
            report = build_index(settings.docs, settings.index, datetime.now(UTC), embedding)
        except ModelError as error:
            sys.stderr.write(f"index not built: {error}; {WORDS_ALONE}\n")
            return ExitStatus.FAILED, None
        except (MirrorMissingError, OSError) as error:
            sys.stderr.write(f"index not built: {error}\n")
            return ExitStatus.FAILED, None
    for path, reason in report.skipped:
        sys.stderr.write(f"skipped {path}: {reason}\n")
    for path in report.unembedded:
        sys.stderr.write(f"not embedded: a piece of {path}, which the endpoint refused\n")
    if report.skipped:
        sys.stderr.write(f"{len(report.skipped)} files skipped: the index lacks them\n")
    indexed = Indexed(report, settings.index, None if embedding is None else settings.model)
    return ExitStatus.FAILED if report.skipped or report.unembedded else ExitStatus.OK, indexed


def text(indexed: Indexed, summary: Summary) -> str:
    """Write the documents indexed and their sections; then the pieces by meaning, if any.

    Short gives their counts and the texts embedded now. Detailed gives the documents by
    type, the index, and the model with its prefixes.
    """
    report = indexed.report
    if summary == "short":
        written = f"documents: {report.types.total()}\nsections: {report.sections}\n"
        if indexed.model is not None:
            written += f"pieces: {report.pieces}\nembedded now: {report.embedded}\n"
        return written
    types = ", ".join(f"{name}: {count}" for name, count in sorted(report.types.items()))
    written = (
        f"indexed {report.types.total()} documents ({types or 'none'}),"
        f" {report.sections} sections, into {indexed.index}\n"
    )
    if indexed.model is not None:
        written += (
            f"{report.pieces} pieces by meaning, with {indexed.model}"
            f" ({prefixes_said(indexed.model)}); {report.embedded} embedded now,"
            " the others kept\n"
        )
    return written
