"""Build the search index from the Markdown mirror, and from nothing else.

With an embedding, each piece of each section also gets its vector: from the vector
store when it holds the piece's text, else from the model, then kept there. A piece
whose text the model refuses has no vector, and its document is named. Reading the files
and embedding are each a span; files and pieces are counted, as
``docs/reference/telemetry/index.md`` lists it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics, trace

from atlassian_offline_mcp.kernel.fields import RepresentationError
from atlassian_offline_mcp.mirror.adapters import markdown
from atlassian_offline_mcp.observability.adapters.progress import task
from atlassian_offline_mcp.search.adapters import sqlite_index, vector_store
from atlassian_offline_mcp.search.domain.chunking import passages
from atlassian_offline_mcp.search.domain.search import Embedded, sections

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from atlassian_offline_mcp.search.adapters.embedding import Embedder

TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# The files of the mirror, indexed or skipped, and the pieces by meaning, given a vector
# or refused one, that each build counts.
FILES = METER.create_counter("aom.index.files", unit="{file}", description="Files, by outcome")
PIECES = METER.create_counter(
    "aom.index.pieces", unit="{piece}", description="Pieces by meaning, by outcome"
)


class MirrorMissingError(Exception):
    """No mirror to index; the message names where it was looked for."""


@dataclass
class Report:
    """What a build indexed, and which files it skipped and why."""

    types: Counter[str] = field(default_factory=Counter)  # documents indexed per type
    sections: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # each path and reason
    pieces: int = 0  # pieces with a vector
    embedded: int = 0  # texts that the model embedded, the store lacking them
    unembedded: list[str] = field(default_factory=list)  # paths with a piece refused


@dataclass(frozen=True)
class Embedding:
    """What gives an index its vectors: a model, and the vector store."""

    embedder: Embedder
    store: Path


def build_index(
    docs: Path, index: Path, built_at: datetime, embedding: Embedding | None = None
) -> Report:
    """Index every document of the mirror at ``docs`` into a new index at ``index``.

    A file that cannot be read, that ``markdown.load`` refuses, or whose document is
    there already is skipped, and named in the report with a reason that holds no
    content. The index replaces the old one only once complete. Raises ModelError when
    the embedding fails; the old index then stays. A piece whose text the model refuses
    is left without a vector, and its document named in the report. The task ``files``
    reports the files read, each by its path, then the vector store its own. The spans
    ``index.files`` and ``index.embed`` hold reading the files and embedding the pieces;
    ``index.document`` says each file indexed at DEBUG, ``index.built`` the counts at
    INFO once the index is complete.
    """
    if not docs.is_dir():
        message = f"no mirror at {docs}: build it with `atlassian-offline-mcp mirror`"
        raise MirrorMissingError(message)
    report = Report()
    model = embedding.embedder if embedding else None
    embedded = Embedded(model.name, model.fingerprint, model.dimensions) if model else None
    pending: list[tuple[int, int, int, str, str]] = []  # each piece's section, span,
    # key and document
    texts: dict[str, str] = {}  # what each key's vector embeds
    log = structlog.get_logger()
    with sqlite_index.building(index, built_at, embedded) as writer:
        files = {file.relative_to(docs).as_posix(): file for file in markdown.documents(docs)}
        with TRACER.start_as_current_span("index.files"), task("files", len(files)) as indexed:
            for path in indexed.each(files, str):
                file = files[path]
                try:
                    # Line endings are kept as written, so that a body reads back exactly.
                    text = file.read_text(encoding="utf-8", newline="")
                    front, body = markdown.load(text, path)
                    cut = sections(body)
                    first = writer.add(path, front, cut)
                except UnicodeDecodeError:
                    reason = "not UTF-8"
                except OSError as error:
                    reason = f"not readable ({type(error).__name__})"
                except (RepresentationError, sqlite_index.DuplicateDocumentError) as error:
                    reason = str(error).removeprefix(f"{path}: ")
                else:
                    report.types[front.type] += 1
                    report.sections += len(cut)
                    for number, start, end, text in passages(front.title, cut) if model else ():
                        key = vector_store.key(model.fingerprint, text)
                        pending.append((first + number, start, end, key, path))
                        texts[key] = text
                    FILES.add(1, {"aom.outcome": "indexed"})
                    log.debug("index.document", path=path, type=front.type, sections=len(cut))
                    continue
                writer.skip()
                report.skipped.append((path, reason))
                FILES.add(1, {"aom.outcome": "skipped"})
        if embedding is not None:
            with TRACER.start_as_current_span("index.embed"):
                with vector_store.opened(embedding.store) as store:
                    found, report.embedded = store.vectors(texts, embedding.embedder.documents)
                kept = [(*piece[:3], found[piece[3]]) for piece in pending if piece[3] in found]
                writer.add_pieces(kept)
            report.pieces = len(kept)
            report.unembedded = sorted({piece[4] for piece in pending if piece[3] not in found})
            PIECES.add(len(kept), {"aom.outcome": "indexed"})
            PIECES.add(len(pending) - len(kept), {"aom.outcome": "refused"})
    log.info(
        "index.built",
        documents=report.types.total(),
        sections=report.sections,
        skipped=len(report.skipped),
        pieces=report.pieces,
        embedded=report.embedded,
    )
    return report
