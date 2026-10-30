"""The work log's step: its org files, read in place, as Markdown files of the mirror.

It reads the work log's folder, converts each document whose revision is not the one its
file holds, and hands every file to ``mirror_files``, which writes those that changed and
removes, under ``worklog/`` alone, those of documents gone. A document whose file holds
its revision keeps that file's body, dates and time of fetch, so that an edit elsewhere
in its org file moves neither; but a day, a meeting and a dated transcript are dated by
their day, afresh at each run, so that a file that held another date takes its day
without a conversion. A run that reports a problem removes nothing, and a file
not read holds back every document that draws on it, as ``worklog.writable`` says, so
that the last good copy of each file stays; a meeting whose link reaches no transcript
read is a warning, not a problem. Reading, building and writing are each a span; each
document is counted, and each conversion timed, by its kind, as
``docs/reference/telemetry/sync.md`` lists them.
"""

from __future__ import annotations

import copy
import time
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from kb_mcp.kernel.record import Record
from kb_mcp.mirror.adapters.markdown import WORKLOG, documents, dump, load
from kb_mcp.mirror.adapters.mirror_files import Changes, sync, worklog_owned
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.mirror.app.mirror import CONVERSION_DURATION, DOCUMENTS, Problem
from kb_mcp.mirror.domain.mirror import PARTICIPANT, FrontMatter, Link, PersonRole
from kb_mcp.mirror.domain.mirror_layout import one_line, worklog_path
from kb_mcp.observability.adapters.progress import task
from kb_mcp.sources.worklog.adapters import files
from kb_mcp.sources.worklog.domain.worklog import (
    DAY_TYPE,
    ENTRY,
    MEETING_TYPE,
    TODO,
    TODO_ARCHIVE,
    TRANSCRIPTS,
    Document,
    journal,
    linked_back,
    revision,
    transcripts,
    writable,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from kb_mcp.mirror.adapters.pandoc import Pandoc
    from kb_mcp.sources.worklog.domain.worklog import Source

SOURCE = "worklog"
TRACER = trace.get_tracer(__name__)


class Read(Record):
    """The work log's documents to write, in order, and the HTML transcripts left out.

    The documents are those read that draw on no file not read; ``held_back`` counts the
    others. Problems stop removals; warnings, such as two transcripts of one id, do not.
    """

    documents: tuple[Document, ...]
    html: int
    problems: tuple[Problem, ...]
    warnings: tuple[str, ...]
    held_back: int


class Outcome(Record):
    """What a run did: documents mirrored, files changed, HTML transcripts left out.

    Problems stop removals; warnings, such as two transcripts of one id, do not.
    ``held_back`` counts the documents read that a file not read held back.
    """

    documents: int
    changes: Changes
    html: int
    problems: tuple[Problem, ...]
    warnings: tuple[str, ...]
    held_back: int


class Planned(Record):
    """What a run would do: documents, those to convert, files to remove, HTML left out.

    ``held_back`` counts the documents read that a file not read would hold back.
    """

    documents: int
    to_convert: int
    to_remove: int
    html: int
    problems: tuple[Problem, ...]
    warnings: tuple[str, ...]
    held_back: int


def read_worklog(
    folder: Path, kept: Mapping[str, tuple[FrontMatter, str]], *, archives: bool
) -> Read:
    """Read the work log under ``folder``: its entries, days and meetings, then its transcripts.

    A meeting links to its transcript and the transcript back to it, both read in this
    one run. Without ``archives``, the archive file, ``transcripts/archive/``,
    ``meetings/archive/`` and the subtrees tagged ARCHIVE are left out. A file not read
    is a problem, named by its path, and the documents that draw on it are left out, as
    ``writable`` says, so that a run writes none of their files; so is a document whose
    file of ``kept``, the mirror's as ``existing`` reads them, has links. The span
    ``worklog.read`` holds the reading; ``worklog.read`` says at INFO what was read.
    ``worklog.unlinked``, a warning, says how many meetings' ``:MEETING:`` link no
    transcript read, and the first by its file, else its id: never a problem, so that it
    holds no removal back.
    """
    with TRACER.start_as_current_span("worklog.read"):
        listing = files.listed(folder, archives=archives)
        problems = [Problem(where=each.path, reason=each.reason) for each in listing.problems]
        sources: list[Source] = []
        for relative in listing.paths:
            try:
                sources.append(files.source(listing.root, relative))
            except files.UnreadableError as error:
                problems.append(Problem(where=str(relative), reason=str(error)))
        found = {each.path: each for each in sources}
        named, warnings = transcripts(
            [each for each in sources if each.path.parts[0] in TRANSCRIPTS], archives=archives
        )
        todo, archive = found.get(PurePosixPath(TODO)), found.get(PurePosixPath(TODO_ARCHIVE))
        journaled, unlinked = journal(todo, archive, archives=archives, transcripts=named)
        unread = {each.where for each in problems}
        linked = {identifier for identifier, (matter, _) in kept.items() if matter.links}
        every = (*journaled, *linked_back(named, journaled))
        documents_read = writable(every, unread, linked)
    log = structlog.get_logger()
    kinds = Counter(each.type for each in journaled)
    log.info(
        "worklog.read",
        entries=kinds[ENTRY],
        days=kinds[DAY_TYPE],
        meetings=kinds[MEETING_TYPE],
        transcripts=len(named),
        html=listing.html,
        problems=len(problems),
    )
    if unlinked:
        log.warning("worklog.unlinked", meetings=len(unlinked), first=unlinked[0])
    held_back = len(every) - len(documents_read)
    return Read(
        documents=tuple(documents_read),
        html=listing.html,
        problems=tuple(problems),
        warnings=tuple(warnings),
        held_back=held_back,
    )


def existing(docs: Path) -> dict[str, tuple[FrontMatter, str]]:
    """Return the work log's files under ``docs``, by their document's id: front matter, body.

    A damaged one is left out: it is the step's own, written again or removed.
    """
    kept: dict[str, tuple[FrontMatter, str]] = {}
    for file in documents(docs, WORKLOG):
        try:
            matter, body = load(file.read_text(encoding="utf-8"), str(file))
        except OSError, ValueError:
            continue
        kept[matter.id] = (matter, body)
    return kept


def mirror_worklog(folder: Path, docs: Path, pandoc: Pandoc, *, archives: bool = True) -> Outcome:
    """Mirror the work log under ``folder`` into ``docs/worklog/``, with ``pandoc``.

    Without ``archives``, the archive file, ``transcripts/archive/``,
    ``meetings/archive/`` and the subtrees tagged ARCHIVE are left out, and so their
    files removed. Raises ``PandocFailedError`` when pandoc gives no version, before any
    file is written: no revision can be named without it.

    The task ``work-log documents`` reports each document, by its title; the spans
    ``worklog.convert`` and ``worklog.write`` hold building the files and writing them.
    ``worklog.document`` says at DEBUG each document, by its path, id and title, and how
    it went; ``worklog.end`` at INFO the files written. Each document is counted by its
    outcome and kind, and each conversion timed. A document whose conversion failed, and
    that has no file, is no link's other end: the links to it are left out of the
    others' files, so that each link names a file.
    """
    log = structlog.get_logger()
    kept = existing(docs)
    read = read_worklog(folder, kept, archives=archives)
    problems = list(read.problems)
    converter = pandoc.org_converter()
    ready: dict[PurePosixPath, tuple[FrontMatter, str]] = {}
    failed: set[str] = set()
    with (
        TRACER.start_as_current_span("worklog.convert"),
        task("work-log documents", len(read.documents)) as built,
    ):
        for document in built.each(read.documents, lambda one: one.title):
            kind = {"kb_mcp.kind": document.type}
            name = revision(converter, document.text)
            old, body = kept.get(document.id, (None, ""))
            began = time.perf_counter()
            if old is not None and old.revision == name:
                outcome, fetched_at = "kept", old.fetched_at
                # A day is not in the revision: a file that held another date takes it.
                created, updated = (
                    (old.created, old.updated) if document.day is None else document.dates(None)
                )
            else:
                try:
                    body = pandoc.org_markdown(document.text)
                except PandocFailedError as error:
                    problems.append(
                        Problem(where=f"{document.source.path}, {document.id}", reason=str(error))
                    )
                    DOCUMENTS.add(1, {"kb_mcp.outcome": "failed", **kind})
                    failed.add(document.id)
                    continue
                outcome = "mirrored"
                created, updated = document.dates(None if old is None else old.created)
                fetched_at = document.source.fetched_at
                CONVERSION_DURATION.record(time.perf_counter() - began, kind)
            DOCUMENTS.add(1, {"kb_mcp.outcome": outcome, **kind})
            matter = FrontMatter(
                source=SOURCE,
                type=document.type,
                id=document.id,
                key=None,
                title=one_line(document.title),
                space=None,
                project=None,
                status=one_line(document.status),
                issue_type=None,
                labels=tuple(one_line(label) for label in document.labels),
                people=tuple(
                    PersonRole(role=PARTICIPANT, name=name)
                    for name in dict.fromkeys(one_line(each) for each in document.people)
                    if name
                ),
                links=tuple(Link(relation=relation, ref=ref) for relation, ref in document.links),
                created=created,
                updated=updated,
                version=None,
                revision=name,
                url=None,
                breadcrumb=tuple(one_line(part) for part in document.breadcrumb),
                fetched_at=fetched_at,
            )
            path = worklog_path(document.type, document.id, document.title)
            ready[path] = (matter, body)
            log.debug(
                "worklog.document",
                path=str(path),
                id=document.id,
                title=document.title,
                kind=document.type,
                outcome=outcome,
            )
    gone = failed - kept.keys()
    wanted: dict[PurePosixPath, bytes | Path] = {
        path: dump(
            copy.replace(
                matter, links=tuple(link for link in matter.links if link.ref not in gone)
            ),
            body,
        ).encode()
        for path, (matter, body) in ready.items()
    }
    with TRACER.start_as_current_span("worklog.write"):
        changes = sync(docs, wanted, worklog_owned, remove=not problems)
    log.info(
        "worklog.end",
        documents=len(wanted),
        written=changes.written,
        unchanged=changes.unchanged,
        removed=changes.removed,
        problems=len(problems),
    )
    return Outcome(
        documents=len(wanted),
        changes=changes,
        html=read.html,
        problems=tuple(problems),
        warnings=read.warnings,
        held_back=read.held_back,
    )


def plan_worklog(folder: Path, docs: Path, pandoc: Pandoc, *, archives: bool = True) -> Planned:
    """Say what mirroring the work log would do, converting and writing nothing.

    A document is to convert when no file holds its revision; a file is to remove when no
    document read has its path, unless a problem was found, as a run would then keep it.
    Pandoc runs for its version alone, which names revisions; raises
    ``PandocFailedError`` when it gives none. ``worklog.end`` says at INFO what a run
    would do.
    """
    kept = existing(docs)
    read = read_worklog(folder, kept, archives=archives)
    converter = pandoc.org_converter()
    held = {identifier: matter.revision for identifier, (matter, _) in kept.items()}
    to_convert = sum(
        1
        for document in read.documents
        if held.get(document.id) != revision(converter, document.text)
    )
    wanted = {worklog_path(each.type, each.id, each.title) for each in read.documents}
    to_remove = 0 if read.problems else len(worklog_owned(docs) - wanted)
    structlog.get_logger().info(
        "worklog.end",
        documents=len(read.documents),
        to_convert=to_convert,
        to_remove=to_remove,
        problems=len(read.problems),
    )
    return Planned(
        documents=len(read.documents),
        to_convert=to_convert,
        to_remove=to_remove,
        html=read.html,
        problems=read.problems,
        warnings=read.warnings,
        held_back=read.held_back,
    )
