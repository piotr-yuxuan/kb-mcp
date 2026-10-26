"""Build the search index from the Markdown mirror, and from nothing else.

With an embedding, each piece of each section also gets its vector: from the vector
store when it holds the piece's text, else from the model, then kept there. A piece
whose text the model refuses has no vector, and its document is named. Reading the files
and embedding are each a span; files and pieces are counted, as
``docs/reference/telemetry/index.md`` lists it. ``refresh`` is what ``index`` and
``sync`` run alike: ``index_mirror``'s build, which opens the endpoint, if any, then
builds; then, for an index by meaning, the prune of the vector store to what the indexes
on disk read.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics, trace

from atlassian_offline_mcp.kernel.fields import RepresentationError
from atlassian_offline_mcp.mirror.adapters import markdown
from atlassian_offline_mcp.observability.adapters.progress import task
from atlassian_offline_mcp.search.adapters import sqlite_index, vector_store
from atlassian_offline_mcp.search.adapters.embedding import ModelError, connect
from atlassian_offline_mcp.search.app.pruning import prune
from atlassian_offline_mcp.search.domain.chunking import CHUNKERS
from atlassian_offline_mcp.search.domain.search import Embedded, sections

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from atlassian_offline_mcp.kernel.chunking import Chunking
    from atlassian_offline_mcp.search.adapters.embedding import Embedder, Endpoint
    from atlassian_offline_mcp.search.app.pruning import Pruned

TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# The files of the mirror, indexed or skipped, and the pieces by meaning, given a vector
# or refused one, that each build counts.
FILES = METER.create_counter("aom.index.files", unit="{file}", description="Files, by outcome")
PIECES = METER.create_counter(
    "aom.index.pieces", unit="{piece}", description="Pieces by meaning, by outcome"
)


# What to do when the endpoint does not answer with the model.
WORDS_ALONE = 'set search_mode = "lexical" to index by words alone'


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
    characters: int = 0  # of the texts that the pieces embed, whatever the store held

    @property
    def whole(self) -> bool:
        """Whether every file was indexed, and every piece given a vector."""
        return not (self.skipped or self.unembedded)


@dataclass(frozen=True)
class Embedding:
    """What gives an index its vectors: a model, and the vector store.

    ``chunking`` names how documents are cut into the pieces that the vectors stand for.
    """

    embedder: Embedder
    store: Path
    chunking: Chunking = "sections"


@dataclass(frozen=True)
class Indexing:
    """What a build of the index reads and writes, and how it embeds.

    ``endpoint`` opens the embedding endpoint, as the run allows it, or is None for an
    index by words alone, which never calls it. ``evaluation_indexes`` holds the indexes
    that eval builds, whose vectors a prune keeps.
    """

    docs: Path
    index: Path
    vectors: Path
    evaluation_indexes: Path
    model: str
    chunking: Chunking
    endpoint: Callable[[], Endpoint] | None


@dataclass(frozen=True)
class Indexed:
    """What a build did, the index it wrote, and the model that embedded, None by words alone.

    ``pruned`` says what the prune of the vector store that followed did: None by words
    alone, which never opens the store, and from ``index_mirror``, which does not prune.
    """

    report: Report
    index: Path
    model: str | None
    pruned: Pruned | None = None


def build_index(
    docs: Path, index: Path, built_at: datetime, embedding: Embedding | None = None
) -> Report:
    """Index every document of the mirror at ``docs`` into a new index at ``index``.

    A file that cannot be read, that ``markdown.load`` refuses, or whose document is
    there already is skipped, and named in the report with a reason that holds no
    content. The index replaces the old one only once complete. Raises ModelError when
    the embedding fails; the old index then stays. A piece whose text the model refuses
    is left without a vector, and its document named in the report. With an embedding,
    the build holds the vector store's lock shared, from before it reads the mirror until
    its index is in place, so that no prune deletes what it embeds; it waits for a prune
    in progress, and raises TimeoutError past ``vector_store.WAIT_S``. The task ``files``
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
    embedded = (
        Embedded(model.name, model.fingerprint, model.dimensions, embedding.chunking)
        if model
        else None
    )
    pending: list[tuple[int, int, int, str, str]] = []  # each piece's section, span,
    # key and document
    texts: dict[str, str] = {}  # what each key's vector embeds
    log = structlog.get_logger()
    with (
        vector_store.shared(embedding.store) if embedding else contextlib.nullcontext(),
        sqlite_index.building(index, built_at, embedded) as writer,
    ):
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
                    # Cut as the index records it.
                    for number, start, end, text in (
                        CHUNKERS[embedded.chunking].cut(front, cut) if embedded else ()
                    ):
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
                kept = [(*piece[:4], found[piece[3]]) for piece in pending if piece[3] in found]
                writer.add_pieces(kept)
            report.pieces = len(kept)
            report.characters = sum(len(text) for text in texts.values())
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


def index_mirror(indexing: Indexing, built_at: datetime) -> Indexed | None:
    """Build the index from the whole mirror, by words alone or with vectors too.

    With an endpoint, it must answer with the model; when it does not, or there is no
    mirror, or the index cannot be written (a file's error, or the database's operational
    one, such as a full disk or a lock), the index in place stays, with its vectors,
    nothing is returned, and ``index.not_built`` is an error. Each file skipped and each
    piece that the endpoint refused is a warning, as is the count of files that the index
    lacks.
    """
    log = structlog.get_logger()
    opened = None if indexing.endpoint is None else indexing.endpoint()
    try:
        with opened or contextlib.nullcontext():
            embedder = None if opened is None else connect(opened, indexing.model)
            embedding = (
                None
                if embedder is None
                else Embedding(embedder, indexing.vectors, indexing.chunking)
            )
            report = build_index(indexing.docs, indexing.index, built_at, embedding)
    except ModelError as error:
        structlog.get_logger().error("index.not_built", reason=str(error), hint=WORDS_ALONE)
        return None
    except (MirrorMissingError, OSError, sqlite3.OperationalError) as error:
        structlog.get_logger().error("index.not_built", reason=str(error))
        return None
    for path, reason in report.skipped:
        log.warning("index.file_skipped", path=path, reason=reason)
    for path in report.unembedded:
        log.warning("index.piece_refused", path=path)
    if report.skipped:
        log.warning("index.lacks_files", count=len(report.skipped))
    return Indexed(report, indexing.index, None if embedding is None else indexing.model)


def refresh(indexing: Indexing, built_at: datetime) -> Indexed | None:
    """Build the index as ``index_mirror`` does; then, by meaning, prune the vector store.

    An index by words alone never opens the store, and prunes nothing. The prune holds
    back after a build that skipped a file or indexed no document, as the index then
    lacks what the mirror still holds.
    """
    indexed = index_mirror(indexing, built_at)
    if indexed is None or indexed.model is None:
        return indexed
    pruned = prune(
        indexing.vectors,
        indexing.index,
        indexing.evaluation_indexes,
        skipped=len(indexed.report.skipped),
        documents=indexed.report.types.total(),
    )
    return replace(indexed, pruned=pruned)
