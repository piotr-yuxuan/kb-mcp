"""Build the search index from the Markdown mirror, and from nothing else.

With an embedding, each piece of each section also gets its vector: from the vector
store when it holds the piece's text, else from the model, then kept there. A piece
whose text the model refuses has no vector, and its document is named. Reading the files,
joining persons and embedding are each a span; files and pieces are counted, as
``docs/reference/telemetry/index.md`` and ``embed.md`` list it. ``update_index`` is
``index``'s: only the files whose bytes changed are read, and the index takes them
through its update. ``refresh`` is ``embed``'s: ``index_mirror``'s build, which opens
the endpoint, then builds; then the prune of the vector store to what the indexes on
disk read.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
from collections import Counter
from collections.abc import Callable
from copy import replace
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics, trace
from pydantic import ConfigDict, Field

from kb_mcp.kernel.chunking import Chunking
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.adapters import markdown
from kb_mcp.observability.adapters.progress import task
from kb_mcp.search.adapters import sqlite_index, vector_store
from kb_mcp.search.adapters.aliases import AliasFileError, read_aliases
from kb_mcp.search.adapters.embedding import connect
from kb_mcp.search.adapters.model_api import Endpoint, ModelError
from kb_mcp.search.app.pruning import Pruned, prune
from kb_mcp.search.domain.chunking import CHUNKERS
from kb_mcp.search.domain.indexes import (
    Change,
    DamagedIndexError,
    Put,
    Skipped,
    UnavailableIndexError,
    Whole,
)
from kb_mcp.search.domain.people import Outcome, aliases_digest
from kb_mcp.search.domain.search import WORDS, Embedded, sections

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from kb_mcp.search.adapters.embedding import Embedder
    from kb_mcp.search.domain.indexes import Held, WordsIndex

TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# The files of the mirror, indexed or skipped, and the pieces by meaning, given a vector
# or refused one, that each build counts.
FILES = METER.create_counter("kb_mcp.index.files", unit="{file}", description="Files, by outcome")
PIECES = METER.create_counter(
    "kb_mcp.index.pieces", unit="{piece}", description="Pieces by meaning, by outcome"
)


# What to do when the endpoint does not answer with the model.
WORDS_ALONE = "run kb-mcp index for an index by words alone"
# Why a run stops that found the index written by another, twice, as it was about to.
CHANGED_MEANWHILE = "another kb-mcp index or kb-mcp embed wrote the index during this run, twice"
# The outcomes of an update's documents, as its report and ``kb_mcp.index.files`` count them.
OUTCOMES = ("copied", "added", "replaced", "removed")


class MirrorMissingError(Exception):
    """No mirror to index; the message names where it was looked for."""


class ChangedMeanwhileError(Exception):
    """Another run wrote the index each time that this one was about to."""


class Report(Record):
    """What a build indexed, which files it skipped and why, and whom it joined."""

    model_config = ConfigDict(frozen=False)

    types: Counter[str] = Field(default_factory=Counter)  # documents indexed per type
    sections: int = 0
    skipped: list[tuple[str, str]] = Field(default_factory=list)  # each path and reason
    pieces: int = 0  # pieces with a vector
    embedded: int = 0  # texts that the model embedded, the store lacking them
    unembedded: list[str] = Field(default_factory=list)  # paths with a piece refused
    characters: int = 0  # of the texts that the pieces embed, whatever the store held
    persons: Outcome = Field(default_factory=Outcome)  # that the documents' people make
    # An update's documents: kept from the index in place, new to it, put in place of
    # its own, or gone; those awaiting vectors, of an index that names a model.
    copied: int = 0
    added: int = 0
    replaced: int = 0
    removed: int = 0
    awaiting: int | None = None
    unchanged: bool = False  # nothing written, the index holding the mirror as it is
    rebuilt: Whole | None = None  # why an update kept nothing of the index in place

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


class Indexing(Record):
    """What a build of the index reads and writes, and how it embeds.

    ``endpoint`` opens the embedding endpoint, as the run allows it, or is None for an
    index by words alone, which never calls it. ``evaluation_indexes`` holds the indexes
    that eval builds, whose vectors a prune keeps. ``aliases`` is the user's alias file,
    which each build reads, if there is one, to join names into persons.
    """

    docs: Path
    index: Path
    vectors: Path
    evaluation_indexes: Path
    aliases: Path
    model: str
    chunking: Chunking
    endpoint: Callable[[], Endpoint] | None


class Differences(Record):
    """How the mirror's files differ from what an index holds of them, by path."""

    changed: frozenset[str]  # held as a document or as skipped, its bytes now other
    added: frozenset[str]  # held as neither
    removed: frozenset[str]  # held as either, with no file now


class Indexed(Record):
    """What a build did, the index it wrote, and the model that embedded, None by words alone.

    ``pruned`` says what the prune of the vector store that followed did: None by words
    alone, which never opens the store, and from ``index_mirror``, which does not prune.
    """

    report: Report
    index: Path
    model: str | None
    pruned: Pruned | None = None


def mirror_files(docs: Path) -> dict[str, Path]:
    """Give each document file of the mirror at ``docs`` by its path, in the mirror's order.

    A name not in UTF-8, which no text in the index could hold, goes in ASCII escapes.
    Raises MirrorMissingError when there is no mirror.
    """
    if not docs.is_dir():
        message = f"no mirror at {docs}: nothing is prepared yet; `kb-mcp prepare` writes it"
        raise MirrorMissingError(message)
    return {
        os.fsencode(file.relative_to(docs).as_posix()).decode(errors="backslashreplace"): file
        for file in markdown.documents(docs)
    }


def digested(files: Mapping[str, Path]) -> dict[str, str | None]:
    """Give the SHA-256 of each file's bytes, by path; None for a file that cannot be read."""
    digests: dict[str, str | None] = {}
    for path, file in files.items():
        try:
            digests[path] = hashlib.sha256(file.read_bytes()).hexdigest()
        except OSError:
            digests[path] = None
    return digests


def differences(digests: Mapping[str, str | None], held: Held) -> Differences:
    """Compare the mirror's files, by their digests, with what an index holds of them.

    A file that still cannot be read, skipped with no digest, is no change.
    """
    holds = held.documents | {path: each.digest for path, each in held.skipped.items()}
    return Differences(
        changed=frozenset(
            path for path in digests.keys() & holds.keys() if digests[path] != holds[path]
        ),
        added=frozenset(digests.keys() - holds.keys()),
        removed=frozenset(holds.keys() - digests.keys()),
    )


def read_document(file: Path, path: str) -> Put | Skipped:
    """Read the file of the mirror that ``path`` names: its document, or why it gives none.

    Its digest is that of the bytes read; a file that cannot be read has none. A file not
    in UTF-8, or that ``markdown.load`` refuses, gives a reason that holds no content.
    """
    digest = None
    try:
        data = file.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        # Line endings are kept as written, so that a body reads back exactly.
        front, body = markdown.load(data.decode("utf-8"), path)
    except UnicodeDecodeError:
        reason = "not UTF-8"
    except OSError as error:
        reason = f"not readable ({type(error).__name__})"
    except RepresentationError as error:
        reason = str(error).removeprefix(f"{path}: ")
    else:
        return Put(path=path, digest=digest, front=front, sections=tuple(sections(body)))
    return Skipped(path=path, digest=digest, reason=reason)


def build_index(
    docs: Path,
    index: Path,
    built_at: datetime,
    embedding: Embedding | None = None,
    aliases: Mapping[str, str] | None = None,
) -> Report:
    """Index every document of the mirror at ``docs`` into a new index at ``index``.

    A file that cannot be read, that ``markdown.load`` refuses, or whose document is
    there already is skipped, and named in the report with a reason that holds no
    content; the index records it, with its digest, as it does each document's. Once the
    files are read, the documents' people are joined into persons,
    through ``aliases``, the alias file's, else none, as for an evaluation's index: the
    report counts the persons and gives what the join left apart. The index replaces
    the old one only once complete. Raises ModelError when the embedding fails; the old
    index then stays. A piece whose text the model refuses is left without a vector,
    and its document named in the report. With an embedding,
    the build holds the vector store's lock shared, from before it reads the mirror until
    its index is in place, so that no prune deletes what it embeds; it waits for a prune
    in progress, and raises TimeoutError past ``vector_store.WAIT_S``. The task ``files``
    reports the files read, each by its path, then the vector store its own. The spans
    ``index.files``, ``Writer.join``'s ``index.join`` and ``index.embed`` hold reading the
    files, joining persons and embedding the pieces;
    ``index.document`` says each file indexed at DEBUG, ``index.built`` the counts at
    INFO once the index is complete.
    """
    files = mirror_files(docs)
    report = Report()
    model = embedding.embedder if embedding else None
    embedded = (
        Embedded(
            model=model.name,
            fingerprint=model.fingerprint,
            dimensions=model.dimensions,
            chunking=embedding.chunking,
        )
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
        with TRACER.start_as_current_span("index.files"), task("files", len(files)) as indexed:
            for path in indexed.each(files, str):
                read = read_document(files[path], path)
                if isinstance(read, Put):
                    try:
                        first = writer.add(read)
                    except sqlite_index.DuplicateDocumentError as error:
                        reason = str(error).removeprefix(f"{path}: ")
                        read = Skipped(path=path, digest=read.digest, reason=reason)
                if isinstance(read, Skipped):
                    writer.skip(read)
                    report.skipped.append((path, read.reason))
                    FILES.add(1, {"kb_mcp.outcome": "skipped"})
                    continue
                front, cut = read.front, read.sections
                report.types[front.type] += 1
                report.sections += len(cut)
                # Cut as the index records it.
                for number, start, end, text in (
                    CHUNKERS[embedded.chunking].cut(front, cut) if embedded else ()
                ):
                    key = vector_store.key(model.fingerprint, text)
                    pending.append((first + number, start, end, key, path))
                    texts[key] = text
                FILES.add(1, {"kb_mcp.outcome": "indexed"})
                log.debug("index.document", path=path, type=front.type, sections=len(cut))
        report.persons = writer.join(aliases or {})
        if embedding is not None:
            with TRACER.start_as_current_span("index.embed"):
                with vector_store.opened(embedding.store) as store:
                    found, report.embedded = store.vectors(texts, embedding.embedder.documents)
                kept = [(*piece[:4], found[piece[3]]) for piece in pending if piece[3] in found]
                writer.add_pieces(kept)
            report.pieces = len(kept)
            report.characters = sum(len(text) for text in texts.values())
            report.unembedded = sorted({piece[4] for piece in pending if piece[3] not in found})
            PIECES.add(len(kept), {"kb_mcp.outcome": "indexed"})
            PIECES.add(len(pending) - len(kept), {"kb_mcp.outcome": "refused"})
    log.info(
        "index.built",
        documents=report.types.total(),
        sections=report.sections,
        skipped=len(report.skipped),
        pieces=report.pieces,
        embedded=report.embedded,
        people=report.persons.count,
    )
    return report


def change_of(
    files: Mapping[str, Path], held: Held | None, aliases: Mapping[str, str], built_at: datetime
) -> Change | None:
    """Say what an update changes of an index that holds ``held`` of the mirror's ``files``.

    None when nothing changed: no file new, changed or gone, the same alias file, so the
    same files skipped. Else the documents of files changed or gone are removed, and
    every file new or changed is read, with every file skipped, as what kept one out may
    be gone. With nothing held, the change is whole, every file read. The span
    ``index.files`` and the task ``files`` hold the reading, ``index.document`` saying
    each document read, at DEBUG.
    """
    paths, removed = files.keys(), frozenset[str]()
    if held is not None:
        found = differences(digested(files), held)
        if not (
            found.changed or found.added or found.removed or held.aliases != aliases_digest(aliases)
        ):
            return None
        paths = found.changed | found.added | (held.skipped.keys() & files.keys())
        removed = (found.changed | found.removed) & held.documents.keys()
    put: list[Put] = []
    skipped: list[Skipped] = []
    log = structlog.get_logger()
    chosen = [path for path in files if path in paths]
    with TRACER.start_as_current_span("index.files"), task("files", len(chosen)) as reading:
        for path in reading.each(chosen, str):
            read = read_document(files[path], path)
            if isinstance(read, Skipped):
                skipped.append(read)
                continue
            put.append(read)
            log.debug(
                "index.document", path=path, type=read.front.type, sections=len(read.sections)
            )
    return Change(
        removed=removed,
        put=tuple(put),
        skipped=tuple(skipped),
        aliases=dict(aliases),
        built_at=built_at,
        whole=held is None,
    )


def updated(
    index: WordsIndex,
    files: Mapping[str, Path],
    aliases: Mapping[str, str],
    built_at: datetime,
    whole: Whole | None,
) -> Report:
    """Update the index to the mirror's files, or rebuild it whole, and report it.

    Whole when ``whole`` says why, or when there is no index that this version reads,
    one written by another ``WORDS`` or before it was recorded, or one damaged, which
    the copy too may find. Another run that wrote the index meanwhile starts the update
    again, once, ``index.restarted`` saying so, then raises ChangedMeanwhileError.
    """
    restarted = False
    while True:
        held = summary = None
        if whole is None:
            try:
                with index.reading() as reader:
                    held, summary = reader.held(), reader.summary()
            except DamagedIndexError:
                whole = "damaged"
            except UnavailableIndexError:
                whole = "unavailable"
        if held is not None and held.words != WORDS:
            held, whole = None, "another version"
        change = change_of(files, held, aliases, built_at)
        if change is None and held is not None and summary is not None:  # nothing changed
            return Report(
                types=Counter(summary.types),
                sections=summary.sections,
                skipped=[(path, held.skipped[path].reason) for path in sorted(held.skipped)],
                persons=Outcome(count=summary.people.count),
                awaiting=summary.awaiting if summary.model else None,
                unchanged=True,
            )
        try:
            done = index.update(change, None if held is None else held.build)
        except DamagedIndexError:
            whole = "damaged"
            continue
        if done is not None:
            return Report(
                types=Counter(done.types),
                sections=done.sections,
                skipped=[(each.path, each.reason) for each in done.skipped],
                persons=done.persons,
                copied=done.copied,
                added=done.added,
                replaced=done.replaced,
                removed=done.removed,
                awaiting=done.awaiting,
                rebuilt=whole,
            )
        if restarted:
            raise ChangedMeanwhileError(CHANGED_MEANWHILE)
        restarted = True
        structlog.get_logger().info("index.restarted")


def update_index(
    indexing: Indexing, built_at: datetime, *, rebuild: bool = False
) -> Indexed | None:
    """Update the index to the mirror, reading only the files whose bytes changed.

    The alias file is read first. Nothing changed, nothing is written; else the index
    takes the change aside, as ``WordsIndex.update`` says, or is rebuilt whole when it
    cannot be read, was written by another ``WORDS``, is damaged, or ``rebuild`` asks.
    When the alias file is refused or cannot be read, there is no mirror, the index
    cannot be written, its lock is held too long, or another run writes it at each
    attempt, the index in place stays, nothing is returned, and ``index.not_built`` is
    an error. Each file skipped is a warning, as is their count, even when nothing is
    written; each name that could be several persons and each alias that changed
    nothing, once a build. ``index.built`` or ``index.unchanged`` says what it did.
    """
    log = structlog.get_logger()
    try:
        aliases = read_aliases(indexing.aliases)
        files = mirror_files(indexing.docs)
        index = sqlite_index.SqliteIndex(indexing.index)
        report = updated(index, files, aliases, built_at, "--rebuild" if rebuild else None)
    except (
        MirrorMissingError,
        AliasFileError,
        ChangedMeanwhileError,
        OSError,
        sqlite3.OperationalError,
    ) as error:
        structlog.get_logger().error("index.not_built", reason=str(error))
        return None
    counts = {name: getattr(report, name) for name in OUTCOMES}
    if report.rebuilt:
        log.info("index.whole", reason=report.rebuilt)
    if report.unchanged:
        log.info(
            "index.unchanged",
            documents=report.types.total(),
            sections=report.sections,
            skipped=len(report.skipped),
        )
    else:
        for name, count in (*counts.items(), ("skipped", len(report.skipped))):
            FILES.add(count, {"kb_mcp.outcome": name})
        log.info(
            "index.built",
            documents=report.types.total(),
            sections=report.sections,
            skipped=len(report.skipped),
            people=report.persons.count,
            **counts,
        )
    warned(report)
    return Indexed(report=report, index=indexing.index, model=None)


def warned(report: Report) -> None:
    """Warn of each file that a build skipped, of their count, and of what its join left apart."""
    log = structlog.get_logger()
    for path, reason in report.skipped:
        log.warning("index.file_skipped", path=path, reason=reason)
    for path in report.unembedded:
        log.warning("index.piece_refused", path=path)
    if report.skipped:
        log.warning("index.lacks_files", count=len(report.skipped))
    for ambiguity in report.persons.ambiguous:
        log.warning(
            "index.person_ambiguous", spelling=ambiguity.name, people=len(ambiguity.persons)
        )
    for alias in report.persons.unused:
        log.warning("index.alias_unused", alias=alias.name, key=alias.key, reason=alias.reason)


def index_mirror(indexing: Indexing, built_at: datetime) -> Indexed | None:
    """Build the index from the whole mirror, by words alone or with vectors too.

    The alias file is read first, before any request to the endpoint. With an endpoint,
    it must answer with the model; when it does not, or the alias file is refused or
    cannot be read, or there is no mirror, or the index cannot be written (a file's
    error, or the database's operational one, such as a full disk or a lock), the index
    in place stays, with its vectors, nothing is returned, and ``index.not_built`` is an
    error. Each file skipped and each piece that the endpoint refused is a warning, as
    is the count of files that the index lacks, each name that could be several persons
    and each alias that changed nothing; the last two leave the report whole.
    """
    opened = None if indexing.endpoint is None else indexing.endpoint()
    try:
        with opened or contextlib.nullcontext():
            aliases = read_aliases(indexing.aliases)
            embedder = None if opened is None else connect(opened, indexing.model)
            embedding = (
                None
                if embedder is None
                else Embedding(embedder, indexing.vectors, indexing.chunking)
            )
            report = build_index(indexing.docs, indexing.index, built_at, embedding, aliases)
    except ModelError as error:
        structlog.get_logger().error("index.not_built", reason=str(error), hint=WORDS_ALONE)
        return None
    except (MirrorMissingError, AliasFileError, OSError, sqlite3.OperationalError) as error:
        structlog.get_logger().error("index.not_built", reason=str(error))
        return None
    warned(report)
    return Indexed(
        report=report, index=indexing.index, model=None if embedding is None else indexing.model
    )


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
