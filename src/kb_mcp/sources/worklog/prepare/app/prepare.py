"""The work log's prepare: its org files, read in place, as Markdown files of the mirror.

It reads the work log's folder, converts each document whose revision is not the one its
file holds, and hands every file to ``mirror_files``, which writes those that changed and
removes, under ``worklog/`` alone, those of documents gone. A document whose file holds
its revision keeps that file's body, dates and time of fetch, so that an edit elsewhere
in its org file moves neither; but a day, a meeting and a dated transcript are dated by
their day, afresh at each run, so that a file that held another date takes its day
without a conversion. A run that reports a problem removes nothing but the old file of a
document written under another path, its title changed, and a file not read holds back
what draws on it alone, as ``worklog.writable`` says: every document for ``todo.org`` or
its archive, else its own, so that the last good copy of each file stays, and each
problem says what it held back; a meeting whose link reaches no transcript found is a
warning, not a problem. Reading, building and writing are each a span; each document is
counted, and each conversion timed, by its document type, as
``docs/reference/telemetry/prepare.md`` lists them.
"""

from __future__ import annotations

import copy
import time
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from kb_mcp.kernel.names import DAY_TYPE, ENTRY_TYPE, MEETING_TYPE
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.adapters.instruments import CONVERSION_DURATION, DOCUMENTS
from kb_mcp.mirror.adapters.markdown import documents, dump, load
from kb_mcp.mirror.adapters.mirror_files import Changes, write_changed
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.mirror.domain.mirror import PARTICIPANT, Link, Mention, Problem
from kb_mcp.mirror.domain.mirror_text import one_line
from kb_mcp.observability.adapters.progress import task
from kb_mcp.sources.worklog.prepare.adapters import files
from kb_mcp.sources.worklog.prepare.adapters.owned import worklog_owned
from kb_mcp.sources.worklog.prepare.domain.layout import WORKLOG_OWNED, worklog_path
from kb_mcp.sources.worklog.prepare.domain.worklog import (
    SOURCE,
    TODO,
    TODO_ARCHIVE,
    WorklogDocument,
    WorklogFrontMatter,
    held_back,
    journal,
    linked_back,
    revision,
    transcript_ids,
    transcripts,
    writable,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping
    from pathlib import Path

    from kb_mcp.kernel.output import Detail
    from kb_mcp.mirror.adapters.pandoc import Pandoc
    from kb_mcp.mirror.domain.mirror import FrontMatter
    from kb_mcp.sources.worklog.prepare.domain.worklog import OrgText

TRACER = trace.get_tracer(__name__)


class WorklogProblem(Problem):
    """A file of the work log not read, or a document not converted, and what it held back.

    ``where`` is the path from the work log's folder, or a document's file and id, never
    its content; ``held_back``, what keeps its last copy for it: for a file not read, as
    the domain's function ``held_back`` says; for a conversion, the document's id.
    """

    held_back: str


class Read(Record):
    """The work log's documents to write, in order, and the HTML transcripts left out.

    The documents are those read that draw on no file not read. Problems stop removals
    but of a written document's old files; warnings, such as two transcripts of one id,
    do not.
    """

    documents: tuple[WorklogDocument, ...]
    html: int
    problems: tuple[WorklogProblem, ...]
    warnings: tuple[str, ...]


class WorklogPrepareOutcome(Record):
    """What a run did: documents prepared, files changed, HTML transcripts left out.

    Problems stop removals but of a written document's old files; warnings, such as two
    transcripts of one id, do not.
    """

    documents: int
    changes: Changes
    html: int
    problems: tuple[WorklogProblem, ...]
    warnings: tuple[str, ...]

    def text(self, summary: Detail) -> str:
        """Write the counts of documents, of files, of HTML transcripts left out, of problems.

        In detail, each warning comes before the problems.
        """
        warnings = self.warnings if summary == "detailed" else ()
        return (
            f"documents: {self.documents}\n"
            f"files written: {self.changes.written}\n"
            f"files unchanged: {self.changes.unchanged}\n"
            f"files removed: {self.changes.removed}\n"
            f"HTML left out: {self.html}\n"
            + "".join(f"warning: {warning}\n" for warning in warnings)
            + f"problems: {len(self.problems)}\n"
        )


class WorklogDryRun(Record):
    """What a run would do: documents, those to convert, files to remove, HTML left out."""

    documents: int
    to_convert: int
    to_remove: int
    html: int
    problems: tuple[WorklogProblem, ...]
    warnings: tuple[str, ...]

    def text(self, summary: Detail) -> str:
        """Write the counts of documents, of those to convert, of files to remove, of problems.

        HTML transcripts left out come before the problems, and in detail each warning.
        """
        warnings = self.warnings if summary == "detailed" else ()
        return (
            f"documents: {self.documents}\n"
            f"to convert: {self.to_convert}\n"
            f"files to remove: {self.to_remove}\n"
            f"HTML left out: {self.html}\n"
            + "".join(f"warning: {warning}\n" for warning in warnings)
            + f"problems: {len(self.problems)}\n"
        )


def read_worklog(folder: Path, *, archives: bool) -> Read:
    """Read the work log under ``folder``: its entries, days and meetings, then its transcripts.

    A meeting links to the id of its transcript, found in this run, read or not, and a
    transcript read links back to it. Without ``archives``, the archive file,
    ``transcripts/archive/``, ``meetings/archive/`` and the subtrees tagged ARCHIVE are
    left out. A file not read is a problem, named by its path, with what it holds back,
    as ``held_back`` says; the documents that draw on it are left out, as ``writable``
    says, so that a run writes none of their files. The span
    ``worklog.read`` holds the reading; ``worklog.read`` says at INFO what was read.
    ``worklog.unlinked``, a warning, says how many meetings' ``:MEETING:`` link no
    transcript found, and the first by its file, else its id: never a problem, so that it
    holds no removal back.
    """
    with TRACER.start_as_current_span("worklog.read"):
        org_files = files.listed(folder, archives=archives)
        unread = [(each.path, each.reason) for each in org_files.problems]
        org_texts: list[OrgText] = []
        for relative in org_files.paths:
            try:
                org_texts.append(files.org_text(org_files.root, relative))
            except files.UnreadableError as error:
                unread.append((str(relative), str(error)))
        found = {each.path: each for each in org_texts}
        # A file linking out is a problem, never listed: its path names it all the same.
        # A folder not listed, though its name may end in .org, names none.
        out = [
            PurePosixPath(each.path)
            for each in org_files.problems
            if each.reason == files.LINKS_OUT
        ]
        ids, warnings = transcript_ids([*org_files.paths, *out], archives=archives)
        problems = [
            WorklogProblem(where=where, reason=reason, held_back=held_back(where, ids))
            for where, reason in unread
        ]
        named = transcripts(org_texts, ids, archives=archives)
        todo, archive = found.get(PurePosixPath(TODO)), found.get(PurePosixPath(TODO_ARCHIVE))
        journaled, unlinked = journal(todo, archive, archives=archives, transcripts=ids)
        documents_read = writable(
            [*journaled, *linked_back(named, journaled)], [where for where, _ in unread]
        )
    log = structlog.get_logger()
    types = Counter(each.type for each in journaled)
    log.info(
        "worklog.read",
        entries=types[ENTRY_TYPE],
        days=types[DAY_TYPE],
        meetings=types[MEETING_TYPE],
        transcripts=len(named),
        html=org_files.html,
        problems=len(problems),
    )
    if unlinked:
        log.warning("worklog.unlinked", meetings=len(unlinked), first=unlinked[0])
    return Read(
        documents=tuple(documents_read),
        html=org_files.html,
        problems=tuple(problems),
        warnings=tuple(warnings),
    )


def existing(
    docs: Path,
) -> tuple[dict[str, tuple[FrontMatter, str]], dict[str, set[PurePosixPath]]]:
    """Return the work log's files under ``docs``, by their document's id: front matter, body.

    Then where they are, from ``docs``, by id: every file of one id, though only the last
    read of two is returned first, as a run under a problem may leave two. A damaged one
    is left out: it is the prepare's own, written again or removed.
    """
    kept: dict[str, tuple[FrontMatter, str]] = {}
    placed: dict[str, set[PurePosixPath]] = {}
    for file in documents(docs, WORKLOG_OWNED):
        try:
            matter, body = load(file.read_text(encoding="utf-8"), str(file))
        except OSError, ValueError:
            continue
        kept[matter.id] = (matter, body)
        placed.setdefault(matter.id, set()).add(PurePosixPath(file.relative_to(docs).as_posix()))
    return kept, placed


def moved(
    identifiers: Iterable[str], placed: Mapping[str, Collection[PurePosixPath]]
) -> set[PurePosixPath]:
    """Return the files of the documents of these ids, which are written, as ``placed`` has them.

    Once its document is written again, under another title's path when its title
    changed, an old file of its id is a copy of none, retired even by a run that removes
    nothing else; ``write_changed`` leaves the one wanted.
    """
    return {path for each in identifiers for path in placed.get(each, ())}


def prepare_worklog(
    folder: Path, docs: Path, pandoc: Pandoc, *, archives: bool = True
) -> WorklogPrepareOutcome:
    """Mirror the work log under ``folder`` into ``docs/worklog/``, with ``pandoc``.

    Without ``archives``, the archive file, ``transcripts/archive/``,
    ``meetings/archive/`` and the subtrees tagged ARCHIVE are left out, and so their
    files removed. Raises ``PandocFailedError`` when pandoc gives no version, before any
    file is written: no revision can be named without it.

    The task ``work-log documents`` reports each document, by its title; the spans
    ``worklog.convert`` and ``worklog.write`` hold building the files and writing them.
    ``worklog.document`` says at DEBUG each document, by its path, id and title, and how
    it went; ``worklog.end`` at INFO the files written. Each document is counted by its
    outcome and document type, and each conversion timed. A link is written only when its other
    end is written in this run or kept from an earlier one, so that each link names a
    file: a transcript not read, or whose conversion failed, without a file yet is no
    link's other end.
    """
    log = structlog.get_logger()
    kept, placed = existing(docs)
    read = read_worklog(folder, archives=archives)
    problems = list(read.problems)
    converter = pandoc.org_converter()
    ready: dict[PurePosixPath, tuple[FrontMatter, str]] = {}
    with (
        TRACER.start_as_current_span("worklog.convert"),
        task("work-log documents", len(read.documents)) as built,
    ):
        for document in built.each(read.documents, lambda one: one.title):
            typed = {"kb_mcp.kind": document.type}
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
                        WorklogProblem(
                            where=f"{document.file.path}, {document.id}",
                            reason=str(error),
                            held_back=document.id,
                        )
                    )
                    DOCUMENTS.add(1, {"kb_mcp.outcome": "failed", **typed})
                    continue
                outcome = "mirrored"
                created, updated = document.dates(None if old is None else old.created)
                fetched_at = document.file.fetched_at
                CONVERSION_DURATION.record(time.perf_counter() - began, typed)
            DOCUMENTS.add(1, {"kb_mcp.outcome": outcome, **typed})
            matter = WorklogFrontMatter(
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
                    Mention(role=PARTICIPANT, name=name)
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
    ends = {matter.id for matter, _ in ready.values()} | kept.keys()
    wanted: dict[PurePosixPath, bytes | Path] = {
        path: dump(
            copy.replace(matter, links=tuple(link for link in matter.links if link.ref in ends)),
            body,
        ).encode()
        for path, (matter, body) in ready.items()
    }
    retired = moved((matter.id for matter, _ in ready.values()), placed)
    with TRACER.start_as_current_span("worklog.write"):
        changes = write_changed(docs, wanted, worklog_owned, remove=not problems, retired=retired)
    log.info(
        "worklog.end",
        documents=len(wanted),
        written=changes.written,
        unchanged=changes.unchanged,
        removed=changes.removed,
        problems=len(problems),
    )
    return WorklogPrepareOutcome(
        documents=len(wanted),
        changes=changes,
        html=read.html,
        problems=tuple(problems),
        warnings=read.warnings,
    )


def plan_worklog(
    folder: Path, docs: Path, pandoc: Pandoc, *, archives: bool = True
) -> WorklogDryRun:
    """Say what preparing the work log would do, converting and writing nothing.

    A document is to convert when no file holds its revision; a file is to remove when no
    document read has its path, unless a problem was found, as a run would then keep it,
    but for the old file of a document read under another path, as ``moved`` says.
    Pandoc runs for its version alone, which names revisions; raises
    ``PandocFailedError`` when it gives none. ``worklog.end`` says at INFO what a run
    would do.
    """
    kept, placed = existing(docs)
    read = read_worklog(folder, archives=archives)
    converter = pandoc.org_converter()
    held = {identifier: matter.revision for identifier, (matter, _) in kept.items()}
    to_convert = sum(
        1
        for document in read.documents
        if held.get(document.id) != revision(converter, document.text)
    )
    wanted = {worklog_path(each.type, each.id, each.title) for each in read.documents}
    stale = worklog_owned(docs) - wanted
    retired = moved((each.id for each in read.documents), placed)
    to_remove = len(stale & retired if read.problems else stale)
    structlog.get_logger().info(
        "worklog.end",
        documents=len(read.documents),
        to_convert=to_convert,
        to_remove=to_remove,
        problems=len(read.problems),
    )
    return WorklogDryRun(
        documents=len(read.documents),
        to_convert=to_convert,
        to_remove=to_remove,
        html=read.html,
        problems=read.problems,
        warnings=read.warnings,
    )
