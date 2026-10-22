"""``index``: build the search index from the Markdown mirror, with the setting's model."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from atlassian_offline_mcp.cli.commands._embedding import open_endpoint, prefixes_said
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.search.adapters.embedding import ModelError, connect
from atlassian_offline_mcp.search.app.indexing import Embedding, MirrorMissingError, build_index

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary
    from atlassian_offline_mcp.search.app.indexing import Report

WORDS_ALONE = 'set search_mode = "lexical" to index by words alone'


@dataclass(frozen=True)
class Indexed:
    """What a build did, the index it wrote, and the model that embedded, None by words alone."""

    report: Report
    index: Path
    model: str | None


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Indexed | None]:
    """Build the index; exit 1 when a file or a piece was left out, or nothing was built.

    By words alone in the lexical mode, which never calls the embedding endpoint. In the
    other modes the endpoint must answer with the setting's model; when it does not,
    the index in place stays, with its vectors, and nothing is given. Nothing built is
    an error; each file skipped and each piece that the endpoint refused is a warning,
    as is the count of files that the index lacks.
    """
    settings = loaded.settings
    opened = None if settings.search_mode == "lexical" else open_endpoint(arguments, settings)
    with opened or contextlib.nullcontext():
        try:
            embedder = None if opened is None else connect(opened, settings.model)
            embedding = (
                None
                if embedder is None
                else Embedding(embedder, settings.vectors, settings.chunking)
            )
            report = build_index(settings.docs, settings.index, datetime.now(UTC), embedding)
        except ModelError as error:
            structlog.get_logger().error("index.not_built", reason=str(error), hint=WORDS_ALONE)
            return ExitStatus.FAILED, None
        except (MirrorMissingError, OSError) as error:
            structlog.get_logger().error("index.not_built", reason=str(error))
            return ExitStatus.FAILED, None
    for path, reason in report.skipped:
        structlog.get_logger().warning("index.file_skipped", path=path, reason=reason)
    for path in report.unembedded:
        structlog.get_logger().warning("index.piece_refused", path=path)
    if report.skipped:
        structlog.get_logger().warning("index.lacks_files", count=len(report.skipped))
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
