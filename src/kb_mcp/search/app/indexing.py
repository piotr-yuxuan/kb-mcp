"""Build the search index from the Markdown mirror, and from nothing else.

With an embedding, each chunk of each section also gets its vector: from the vector
cache when it holds the chunk's text, else from the model, then kept there. A chunk
whose text the model refuses has no vector, and its document is named. Reading the files,
joining persons and embedding are each a span; files and chunks are counted, as
``docs/reference/telemetry/index.md`` and ``embed.md`` list it. ``update_index`` is
``index``'s: only the files whose bytes changed are read, and the index takes them
through its update. ``fill_and_prune`` is ``embed``'s: the chunks that the index's documents
want are filled, from the index alone, the mirror read for its digests; then the
vector cache is pruned to what the indexes on disk read. ``build_index`` builds an
index whole, as ``eval`` does.
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

import numpy as np
import structlog
from opentelemetry import metrics, trace
from pydantic import ConfigDict, Field

from kb_mcp.kernel.chunking import Chunking
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.outcome import Outcome, OutcomeWarning, Problem
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.adapters import markdown
from kb_mcp.observability.adapters.progress import task
from kb_mcp.search.adapters import sqlite_index, vector_cache
from kb_mcp.search.adapters.aliases import AliasFileError, read_aliases
from kb_mcp.search.adapters.embedding import connect, prefixes
from kb_mcp.search.adapters.model_api import Endpoint, ModelError
from kb_mcp.search.app.pruning import Pruned, Written, prune
from kb_mcp.search.domain.chunking import CHUNKERS
from kb_mcp.search.domain.indexes import (
    Change,
    DamagedIndexError,
    Put,
    Skipped,
    UnavailableIndexError,
    Whole,
)
from kb_mcp.search.domain.people import JoinOutcome, aliases_digest
from kb_mcp.search.domain.search import WORDS, Chunk, Embedded, sections

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from kb_mcp.kernel.output import Detail
    from kb_mcp.search.adapters.embedding import Embedder
    from kb_mcp.search.domain.indexes import Held, IndexedBody, SearchIndex, WordsIndex

TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# The files of the mirror, indexed or skipped, and the chunks by meaning, given a vector
# or refused one, that each build counts.
FILES = METER.create_counter("kb_mcp.index.files", unit="{file}", description="Files, by outcome")
CHUNKS = METER.create_counter(
    "kb_mcp.index.chunks", unit="{chunk}", description="Chunks by meaning, by outcome"
)


# Why a run stops that found the index written by another, twice, as it was about to.
CHANGED_MEANWHILE = "another kb-mcp index or kb-mcp embed wrote the index during this run, twice"
# The outcomes of an update's documents, as its counts and ``kb_mcp.index.files`` count them.
OUTCOMES = ("copied", "added", "replaced", "removed")
# Why an update kept nothing of the index in place, as the detailed text says it.
WHOLE = {
    "unavailable": "there being none that this version reads",
    "another version": "written by another version",
    "damaged": "it being damaged",
    "--rebuild": "as --rebuild asks",
}
# Why a document with a chunk without a vector is a problem.
REFUSED = "the model refused a chunk's text"


class MirrorMissingError(Exception):
    """No mirror to index; the message names where it was looked for."""


class ChangedMeanwhileError(Exception):
    """Another run wrote the index each time that this one was about to."""


class IndexCounts(Record):
    """What a build indexed, whom it joined, and, for an update, what it changed.

    ``persons`` is the join's whole outcome, what it left apart the build's warnings too;
    ``index`` is the index written.
    """

    model_config = ConfigDict(frozen=False)

    index: Path
    types: Counter[str] = Field(default_factory=Counter)  # documents indexed per type
    sections: int = 0
    chunks: int = 0  # chunks with a vector
    embedded: int = 0  # texts that the model embedded, the vector cache lacking them
    characters: int = 0  # of the texts that the chunks embed, whatever the vector cache held
    persons: JoinOutcome = Field(default_factory=JoinOutcome)  # that the documents' people make
    # An update's documents: kept from the index in place, new to it, put in place of
    # its own, or gone; those awaiting vectors, of an index that names a model.
    copied: int = 0
    added: int = 0
    replaced: int = 0
    removed: int = 0
    awaiting: int | None = None
    unchanged: bool = False  # nothing written, the index holding the mirror as it is
    rebuilt: Whole | None = None  # why an update kept nothing of the index in place

    def text(self, detail: Detail) -> str:
        """Write what the index holds and what changed of it: a line each, or one in detail."""
        if detail == "short":
            lines = [f"documents: {self.types.total()}", f"sections: {self.sections}"]
            lines += (
                ["nothing written"]
                if self.unchanged
                else [f"{name}: {getattr(self, name)}" for name in OUTCOMES]
            )
            lines += [f"rebuilt whole: {self.rebuilt}"] if self.rebuilt else []
            lines += [] if self.awaiting is None else [f"awaiting vectors: {self.awaiting}"]
            return "".join(f"{line}\n" for line in lines)
        types = ", ".join(f"{name}: {count}" for name, count in sorted(self.types.items()))
        holds = f"{self.types.total()} documents ({types or 'none'}), {self.sections} sections"
        done = ", ".join(f"{getattr(self, name)} {name}" for name in OUTCOMES)
        if self.unchanged:
            written = f"nothing changed: {self.index} holds {holds}"
        elif self.rebuilt:
            written = f"rebuilt {self.index} whole, {WHOLE[self.rebuilt]}: {holds}"
        else:
            written = f"updated {self.index}: documents {done}; it holds {holds}"
        if self.awaiting is not None:
            written += f"; {self.awaiting} await vectors from kb-mcp embed"
        return f"{written}\n"


def outcome_of(counts: IndexCounts, problems: Iterable[Problem]) -> Outcome[IndexCounts]:
    """Give a build's outcome, warned of what the join left apart."""
    return Outcome.of(
        counts,
        problems,
        (
            *(
                OutcomeWarning(where=each.name, reason=f"could be {len(each.persons)} persons")
                for each in counts.persons.ambiguous
            ),
            *(
                OutcomeWarning(where=each.name, reason=f"alias that changed nothing: {each.reason}")
                for each in counts.persons.unused
            ),
        ),
    )


@dataclass(frozen=True)
class Embedding:
    """What gives an index its vectors: a model, and the vector cache.

    ``chunking`` names how documents are cut into the chunks that the vectors stand for.
    """

    embedder: Embedder
    store: Path
    chunking: Chunking = "sections"


class Indexing(Record):
    """What a build of the index reads and writes, and how it embeds.

    ``endpoint`` opens the embedding endpoint, as the run allows it, or is None for an
    index by words alone, which never calls it. ``evaluation_indexes`` holds the indexes
    that eval builds, whose vectors a prune keeps. ``aliases`` is the user's alias file,
    which ``index`` reads, if there is one, to join names into persons.
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


def document_files(docs: Path) -> dict[str, Path]:
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
) -> Outcome[IndexCounts]:
    """Index every document of the mirror at ``docs`` into a new index at ``index``.

    A file that cannot be read, that ``markdown.load`` refuses, or whose document is
    there already is skipped, a problem by its path with a reason that holds no
    content; the index records it, with its digest, as it does each document's. Once the
    files are read, the documents' people are joined into persons through ``aliases``,
    the alias file's, else none, as for an evaluation's index: the counts count the
    persons, and the warnings say what the join left apart. The index replaces the old
    one only once complete. Raises ModelError when the embedding fails; the old index
    then stays. A chunk whose text the model refuses is left without a vector, and its
    document is a problem. With an embedding, the build holds the vector cache's lock shared,
    from before it reads the mirror until its index is in place, so that no prune
    deletes what it embeds; it waits for a prune in progress, and raises TimeoutError
    past ``WAIT_S``, the conversions'.
    """
    files = document_files(docs)
    report, skipped, refused = IndexCounts(index=index), [], []
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
    pending: list[tuple[int, int, int, str, str]] = []  # each chunk's section, range,
    # key and document
    texts: dict[str, str] = {}  # what each key's vector embeds
    log = structlog.get_logger()
    with (
        vector_cache.shared(embedding.store) if embedding else contextlib.nullcontext(),
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
                    skipped.append(Problem(where=path, reason=read.reason))
                    FILES.add(1, {"kb_mcp.outcome": "skipped"})
                    continue
                front, cut = read.front, read.sections
                report.types[front.type] += 1
                report.sections += len(cut)
                # Cut as the index records it.
                for number, start, end, text in (
                    CHUNKERS[embedded.chunking].cut(front, cut) if embedded else ()
                ):
                    key = vector_cache.vector_key(model.fingerprint, text)
                    pending.append((first + number, start, end, key, path))
                    texts[key] = text
                FILES.add(1, {"kb_mcp.outcome": "indexed"})
                log.debug("index.document", path=path, type=front.type, sections=len(cut))
        report.persons = writer.join(aliases or {})
        if embedding is not None:
            with TRACER.start_as_current_span("index.embed"):
                with vector_cache.opened(embedding.store) as store:
                    found, report.embedded = store.vectors(texts, embedding.embedder.documents)
                kept = [(*chunk[:4], found[chunk[3]]) for chunk in pending if chunk[3] in found]
                writer.add_chunks(kept)
            report.chunks = len(kept)
            report.characters = sum(len(text) for text in texts.values())
            refused = sorted({chunk[4] for chunk in pending if chunk[3] not in found})
            CHUNKS.add(len(kept), {"kb_mcp.outcome": "indexed"})
            CHUNKS.add(len(pending) - len(kept), {"kb_mcp.outcome": "refused"})
    log.info(
        "index.built",
        documents=report.types.total(),
        sections=report.sections,
        skipped=len(skipped),
        chunks=report.chunks,
        embedded=report.embedded,
        persons=report.persons.count,
    )
    return outcome_of(
        report, [*skipped, *(Problem(where=each, reason=REFUSED) for each in refused)]
    )


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
    path: Path,
    files: Mapping[str, Path],
    aliases: Mapping[str, str],
    built_at: datetime,
    whole: Whole | None,
) -> Outcome[IndexCounts]:
    """Update the index at ``path`` to the mirror's files, or rebuild it whole; give its outcome.

    Whole when ``whole`` says why, or when there is no index that this version reads,
    one written by another ``WORDS`` or before it was recorded, or one damaged, which
    the copy too may find. Another run that wrote the index meanwhile starts the update
    again, once, ``index.restarted`` saying so, then raises ChangedMeanwhileError.
    """
    index: WordsIndex = sqlite_index.SqliteIndex(path)
    restarted = False
    while True:
        held = state = None
        if whole is None:
            try:
                with index.reading() as reader:
                    held, state = reader.held(), reader.index_status()
            except DamagedIndexError:
                whole = "damaged"
            except UnavailableIndexError:
                whole = "unavailable"
        if held is not None and held.words != WORDS:
            held, whole = None, "another version"
        change = change_of(files, held, aliases, built_at)
        if change is None and held is not None and state is not None:  # nothing changed
            unchanged = IndexCounts(
                index=path,
                types=Counter(state.types),
                sections=state.sections,
                persons=JoinOutcome(count=state.persons.count),
                awaiting=state.awaiting if state.model else None,
                unchanged=True,
            )
            return outcome_of(
                unchanged,
                (
                    Problem(where=path, reason=held.skipped[path].reason)
                    for path in sorted(held.skipped)
                ),
            )
        try:
            done = index.update(change, None if held is None else held.build)
        except DamagedIndexError:
            whole = "damaged"
            continue
        if done is not None:
            written = IndexCounts(
                index=path,
                types=Counter(done.types),
                sections=done.sections,
                persons=done.persons,
                copied=done.copied,
                added=done.added,
                replaced=done.replaced,
                removed=done.removed,
                awaiting=done.awaiting,
                rebuilt=whole,
            )
            return outcome_of(
                written, (Problem(where=each.path, reason=each.reason) for each in done.skipped)
            )
        if restarted:
            raise ChangedMeanwhileError(CHANGED_MEANWHILE)
        restarted = True
        structlog.get_logger().info("index.restarted")


def update_index(
    indexing: Indexing, built_at: datetime, *, rebuild: bool = False
) -> Outcome[IndexCounts]:
    """Update the index to the mirror, reading only the files whose bytes changed.

    The alias file is read first. Nothing changed, nothing is written; else the index
    takes the change aside, as ``WordsIndex.update`` says, or is rebuilt whole when it
    cannot be read, was written by another ``WORDS``, is damaged, or ``rebuild`` asks.
    When the alias file is refused or cannot be read, there is no mirror, the index
    cannot be written, its lock is held too long, or another run writes it at each
    attempt, the index in place stays, the outcome fails by a problem of that input, and
    ``index.not_built`` is an error. Each file skipped is a problem and a warning event,
    as is their count, even when nothing is written; each name that could be several
    persons and each alias that changed nothing, once a build, a warning of both.
    ``index.built`` or ``index.unchanged`` says what it did.
    """
    log = structlog.get_logger()
    try:
        aliases = read_aliases(indexing.aliases)
        files = document_files(indexing.docs)
        whole = "--rebuild" if rebuild else None
        outcome = updated(indexing.index, files, aliases, built_at, whole)
    except (
        MirrorMissingError,
        AliasFileError,
        ChangedMeanwhileError,
        OSError,
        sqlite3.OperationalError,
    ) as error:
        structlog.get_logger().error("index.not_built", reason=str(error))
        # By the input that stopped it: the alias file, the mirror, else the index.
        failing = {AliasFileError: indexing.aliases, MirrorMissingError: indexing.docs}
        where = failing.get(type(error), indexing.index)
        return Outcome.of(problems=(Problem(where=str(where), reason=str(error)),))
    report = outcome.counts
    counts = {name: getattr(report, name) for name in OUTCOMES}
    if report.rebuilt:
        log.info("index.whole", reason=report.rebuilt)
    if report.unchanged:
        log.info(
            "index.unchanged",
            documents=report.types.total(),
            sections=report.sections,
            skipped=len(outcome.problems),
        )
    else:
        for name, count in (*counts.items(), ("skipped", len(outcome.problems))):
            FILES.add(count, {"kb_mcp.outcome": name})
        log.info(
            "index.built",
            documents=report.types.total(),
            sections=report.sections,
            skipped=len(outcome.problems),
            persons=report.persons.count,
            chained=list(report.persons.chained),
            **counts,
        )
    for each in outcome.problems:
        log.warning("index.file_skipped", path=each.where, reason=each.reason)
    if outcome.problems:
        log.warning("index.lacks_files", count=len(outcome.problems))
    for ambiguity in report.persons.ambiguous:
        log.warning(
            "index.person_ambiguous", spelling=ambiguity.name, persons=len(ambiguity.persons)
        )
    for alias in report.persons.unused:
        log.warning("index.alias_unused", alias=alias.name, key=alias.key, reason=alias.reason)
    return outcome


# The texts of the chunks wanted, each by its chunk, and what the index already holds.
type Wanted = dict[Chunk, str]


class Filled(Record):
    """What ``embed`` did to the index's chunks, then what the prune that followed did.

    ``added`` and ``removed`` count chunks; ``embedded`` the texts that the model embedded,
    the vector cache lacking them; ``found`` those that it held. ``chunks`` counts what
    the index then holds, ``documents`` its documents and ``skipped`` the files that it
    lacks, which the prune reads. ``unchanged`` says that nothing was written. ``kept``
    holds the keys of the chunks that the index then holds, which the prune keeps
    whatever an ``index`` renamed meanwhile; it is not shown.
    """

    index: Path
    model: str
    chunks: int
    documents: int
    skipped: int = 0
    added: int = 0
    removed: int = 0
    embedded: int = 0
    found: int = 0
    unchanged: bool = False
    kept: frozenset[str] = Field(default_factory=frozenset, exclude=True)
    pruned: Pruned | None = None

    def text(self, detail: Detail) -> str:
        """Write the chunks that the index holds and what changed of them, then the prune."""
        if detail == "short":
            written = f"chunks: {self.chunks}\n"
            written += (
                "nothing written\n"
                if self.unchanged
                else f"added: {self.added}\nremoved: {self.removed}\n"
            )
            written += f"embedded now: {self.embedded}\n"
        else:
            model = f"{self.model} ({prefixes_said(self.model)})"
            holds = f"{self.index} holds {self.chunks} chunks by meaning, with {model}"
            written = (
                f"nothing changed: {holds}\n"
                if self.unchanged
                else f"{self.chunks} chunks by meaning in {self.index}, with {model}:"
                f" {self.added} added, {self.removed} removed; {self.embedded} texts embedded"
                f" now, {self.found} found in the vector cache\n"
            )
        return written + ("" if self.pruned is None else self.pruned.text(detail))


def prefixes_said(model: str) -> str:
    """Say whether the prefixes that a model's card asks for are known here."""
    return "its prefixes known" if prefixes(model) else "no prefixes known: texts as they are"


def filled_outcome(
    filled: Filled, refused: Iterable[str], warned: Iterable[OutcomeWarning], held: Held
) -> Outcome[Filled]:
    """Give a fill's outcome: a problem by each document refused and each file lacking."""
    problems = [Problem(where=path, reason=REFUSED) for path in refused]
    problems += [
        Problem(where=path, reason=f"not in the index: {each.reason}")
        for path, each in sorted(held.skipped.items())
    ]
    return Outcome.of(filled, problems, warned)


def to_fill(index: SearchIndex) -> tuple[Held, Embedded | None, list[IndexedBody], set[Chunk]]:
    """Read in one use what ``embed`` fills: what is held, the model, documents and chunks.

    What the index holds of the mirror, the model it names, if any, its documents and
    its chunks. Raises UnavailableIndexError, naming ``kb-mcp index``, for an index that this code's
    cut did not write, as its chunks would land on other sections; and as ``reading``
    and ``held`` raise it.
    """
    with index.reading() as reader:
        held = reader.held()
        if held.words != WORDS:
            message = (
                "the index is cut otherwise than this version cuts, or records no files:"
                " run kb-mcp index first"
            )
            raise UnavailableIndexError(message)
        return held, reader.embedded(), reader.documents(), set(reader.chunks())


def filling(index: SearchIndex, indexing: Indexing) -> Outcome[Filled]:
    """Fill the chunks that the index's documents want, by the run's model and chunking.

    Before the endpoint is opened, the index is read and the mirror's files compared
    with it: ``embed.mirror_changed`` warns of any difference, naming ``kb-mcp index``,
    as does a warning of the outcome, and changes nothing else. The documents' bodies
    are cut again by this code, each chunk keyed by the model's fingerprint: those wanted
    and not held are added, their vectors from the vector cache, else from the model,
    under its lock shared; those held and not wanted are removed; nothing to add or
    remove, the same model, nothing is written, nor when the model refuses every chunk to
    add. Another run that wrote the index meanwhile starts the fill again, once, then
    raises ChangedMeanwhileError.
    Raises ModelError when the model fails. Each document with a chunk refused is a
    problem and a warning event; each file that the index lacks a problem;
    ``embed.filled`` or ``embed.unchanged`` says what it did, and
    ``kb_mcp.index.chunks`` counts the chunks added, removed and refused.
    """
    log = structlog.get_logger()
    held, before, stored, chunks = to_fill(index)
    try:
        files = document_files(indexing.docs)
    except MirrorMissingError:
        files = {}
    found = differences(digested(files), held)
    warned: list[OutcomeWarning] = []
    if found.changed or found.added or found.removed:
        said = f"{len(found.changed)} changed, {len(found.added)} added, {len(found.removed)}"
        warned.append(
            OutcomeWarning(
                where="mirror", reason=f"{said} removed since the index: run kb-mcp index"
            )
        )
        log.warning(
            "embed.mirror_changed",
            changed=len(found.changed),
            added=len(found.added),
            removed=len(found.removed),
            hint="run kb-mcp index",
        )
    restarted = False
    with indexing.endpoint() as endpoint:
        embedder = connect(endpoint, indexing.model)
        model = Embedded(
            model=embedder.name,
            fingerprint=embedder.fingerprint,
            dimensions=embedder.dimensions,
            chunking=indexing.chunking,
        )
        while True:
            wanted: Wanted = {
                Chunk(
                    path=each.path,
                    number=number + 1,
                    start=start,
                    end=end,
                    vector_key=vector_cache.vector_key(model.fingerprint, text),
                ): text
                for each in stored
                for number, start, end, text in CHUNKERS[model.chunking].cut(
                    each.front, sections(each.body)
                )
            }
            add = {chunk: text for chunk, text in wanted.items() if chunk not in chunks}
            remove = chunks - wanted.keys()
            kept = chunks - remove
            filled = Filled(
                index=indexing.index,
                model=indexing.model,
                chunks=len(kept),
                documents=len(held.documents),
                skipped=len(held.skipped),
                kept=frozenset(chunk.vector_key for chunk in kept),
            )
            if not add and not remove and before == model:
                log.info("embed.unchanged", chunks=filled.chunks)
                return filled_outcome(replace(filled, unchanged=True), (), warned, held)
            texts = {chunk.vector_key: text for chunk, text in add.items()}
            with vector_cache.shared(indexing.vectors):
                with (
                    TRACER.start_as_current_span("index.embed"),
                    vector_cache.opened(indexing.vectors) as store,
                ):
                    vectors, embedded = store.vectors(texts, embedder.documents)
                given = {
                    chunk: np.frombuffer(vectors[chunk.vector_key], dtype=vector_cache.LAYOUT)
                    for chunk in add
                    if chunk.vector_key in vectors
                }
                build = (
                    index.fill(held.build, model, given, remove)
                    if given or remove or before != model
                    else held.build  # every chunk to add refused: nothing to write
                )
            if build is not None:
                refused = sorted({chunk.path for chunk in add.keys() - given.keys()})
                filled = replace(
                    filled,
                    chunks=len(kept) + len(given),
                    added=len(given),
                    removed=len(remove),
                    embedded=embedded,
                    found=len(texts.keys() & vectors.keys()) - embedded,
                    kept=filled.kept | {chunk.vector_key for chunk in given},
                    unchanged=build == held.build,
                )
                counts = {"added": filled.added, "removed": filled.removed}
                for outcome, count in (*counts.items(), ("refused", len(add) - len(given))):
                    CHUNKS.add(count, {"kb_mcp.outcome": outcome})
                for path in refused:
                    log.warning("index.chunk_refused", path=path)
                if filled.unchanged:
                    log.info("embed.unchanged", chunks=filled.chunks)
                    return filled_outcome(filled, refused, warned, held)
                log.info(
                    "embed.filled",
                    **counts,
                    embedded=filled.embedded,
                    found=filled.found,
                    refused=len(refused),
                    chunks=filled.chunks,
                )
                return filled_outcome(filled, refused, warned, held)
            if restarted:
                raise ChangedMeanwhileError(CHANGED_MEANWHILE)
            restarted = True
            log.info("index.restarted")
            held, before, stored, chunks = to_fill(index)


def fill_and_prune(indexing: Indexing) -> Outcome[Filled]:
    """Fill the index's chunks, as ``filling`` does, then prune the vector cache.

    When there is no index, one that this code's cut did not write, one damaged, the
    model fails, the index cannot be written, its lock is held too long, or another run
    wrote it at each attempt, the index in place stays, the outcome fails by a problem
    of the index, and ``index.not_built`` is an error. The prune holds back for an index
    that lacks a file of the mirror or holds no document, and keeps the vectors of the
    chunks that the index holds, as this run wrote it.
    """
    try:
        outcome = filling(sqlite_index.SqliteIndex(indexing.index), indexing)
    except (
        UnavailableIndexError,
        ModelError,
        ChangedMeanwhileError,
        OSError,
        sqlite3.OperationalError,
    ) as error:
        structlog.get_logger().error("index.not_built", reason=str(error))
        not_built = Problem(where=str(indexing.index), reason=str(error))
        return Outcome.of(problems=(not_built,))
    filled = outcome.counts
    written = Written(skipped=filled.skipped, documents=filled.documents, keys=filled.kept)
    pruned = prune(indexing.vectors, indexing.index, indexing.evaluation_indexes, written)
    return replace(outcome, counts=replace(filled, pruned=pruned))
