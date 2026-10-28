"""The work log's step: its org files, read in place, as Markdown files of the mirror.

It reads the work log's folder, converts each document whose revision is not the one its
file holds, and hands every file to ``mirror_files``, which writes those that changed and
removes, under ``worklog/`` alone, those of documents gone. A document whose file holds
its revision keeps that file's body, dates and time of fetch, so that an edit elsewhere
in its org file moves neither. A run that reports a problem removes nothing, so that the
last good copy of each file stays. Reading, building and writing are each a span; each
document is counted, and each conversion timed, by its kind, as
``docs/reference/telemetry/sync.md`` lists them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from atlassian_offline_mcp.mirror.adapters.markdown import WORKLOG, documents, dump, load
from atlassian_offline_mcp.mirror.adapters.mirror_files import Changes, sync, worklog_owned
from atlassian_offline_mcp.mirror.adapters.pandoc import PandocFailedError
from atlassian_offline_mcp.mirror.app.mirror import CONVERSION_DURATION, DOCUMENTS, Problem
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter, Link, PersonRole
from atlassian_offline_mcp.mirror.domain.mirror_layout import one_line, worklog_path
from atlassian_offline_mcp.observability.adapters.progress import task
from atlassian_offline_mcp.sources.worklog.adapters import files
from atlassian_offline_mcp.sources.worklog.domain.worklog import (
    TODO,
    TODO_ARCHIVE,
    TRANSCRIPTS,
    entries,
    revision,
    transcripts,
)

if TYPE_CHECKING:
    from pathlib import Path

    from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc
    from atlassian_offline_mcp.sources.worklog.domain.worklog import Document, Source

SOURCE = "worklog"
# The role of the people that a work-log document names.
PARTICIPANT = "participant"
TRACER = trace.get_tracer(__name__)


@dataclass(frozen=True)
class Read:
    """The work log's documents as read, in order, and the HTML transcripts left out.

    Problems stop removals; warnings, such as two transcripts of one id, do not.
    """

    documents: tuple[Document, ...]
    html: int
    problems: tuple[Problem, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Outcome:
    """What a run did: documents mirrored, files changed, HTML transcripts left out.

    Problems stop removals; warnings, such as two transcripts of one id, do not.
    """

    documents: int
    changes: Changes
    html: int
    problems: tuple[Problem, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Planned:
    """What a run would do: documents, those to convert, files to remove, HTML left out."""

    documents: int
    to_convert: int
    to_remove: int
    html: int
    problems: tuple[Problem, ...]
    warnings: tuple[str, ...]


def read_worklog(folder: Path, *, archives: bool) -> Read:
    """Read the work log under ``folder``: its entries, then its transcripts.

    Without ``archives``, the archive file, ``transcripts/archive/`` and the subtrees
    tagged ARCHIVE are left out. A file not read is a problem, named by its path. The span
    ``worklog.read`` holds the reading; ``worklog.read`` says at INFO what was read.
    """
    with TRACER.start_as_current_span("worklog.read"):
        listing = files.listed(folder, archives=archives)
        problems = [Problem(each.path, each.reason) for each in listing.problems]
        sources: list[Source] = []
        for relative in listing.paths:
            try:
                sources.append(files.source(listing.root, relative))
            except files.UnreadableError as error:
                problems.append(Problem(str(relative), str(error)))
        found = {each.path: each for each in sources}
        named, warnings = transcripts(
            [each for each in sources if each.path.parts[0] == TRANSCRIPTS], archives=archives
        )
        todo, archive = found.get(PurePosixPath(TODO)), found.get(PurePosixPath(TODO_ARCHIVE))
        documents_read = (*entries(todo, archive, archives=archives), *named)
    structlog.get_logger().info(
        "worklog.read",
        entries=len(documents_read) - len(named),
        transcripts=len(named),
        html=listing.html,
        problems=len(problems),
    )
    return Read(documents_read, listing.html, tuple(problems), tuple(warnings))


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

    Without ``archives``, the archive file, ``transcripts/archive/`` and the subtrees
    tagged ARCHIVE are left out, and so their files removed. Raises
    ``PandocFailedError`` when pandoc gives no version, before any file is written: no
    revision can be named without it.

    The task ``work-log documents`` reports each document, by its title; the spans
    ``worklog.convert`` and ``worklog.write`` hold building the files and writing them.
    ``worklog.document`` says at DEBUG each document, by its path, id and title, and how
    it went; ``worklog.end`` at INFO the files written. Each document is counted by its
    outcome and kind, and each conversion timed.
    """
    log = structlog.get_logger()
    read = read_worklog(folder, archives=archives)
    problems = list(read.problems)
    converter = pandoc.org_converter()
    kept = existing(docs)
    wanted: dict[PurePosixPath, bytes | Path] = {}
    with (
        TRACER.start_as_current_span("worklog.convert"),
        task("work-log documents", len(read.documents)) as built,
    ):
        for document in built.each(read.documents, lambda one: one.title):
            kind = {"aom.kind": document.type}
            name = revision(converter, document.text)
            old, body = kept.get(document.id, (None, ""))
            began = time.perf_counter()
            if old is not None and old.revision == name:
                outcome, created, updated = "kept", old.created, old.updated
                fetched_at = old.fetched_at
            else:
                try:
                    body = pandoc.org_markdown(document.text)
                except PandocFailedError as error:
                    problems.append(Problem(f"{document.source.path}, {document.id}", str(error)))
                    DOCUMENTS.add(1, {"aom.outcome": "failed", **kind})
                    continue
                outcome = "mirrored"
                created, updated = document.dates(None if old is None else old.created)
                fetched_at = document.source.fetched_at
                CONVERSION_DURATION.record(time.perf_counter() - began, kind)
            DOCUMENTS.add(1, {"aom.outcome": outcome, **kind})
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
            wanted[path] = dump(matter, body).encode()
            log.debug(
                "worklog.document",
                path=str(path),
                id=document.id,
                title=document.title,
                kind=document.type,
                outcome=outcome,
            )
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
    return Outcome(len(wanted), changes, read.html, tuple(problems), read.warnings)


def plan_worklog(folder: Path, docs: Path, pandoc: Pandoc, *, archives: bool = True) -> Planned:
    """Say what mirroring the work log would do, converting and writing nothing.

    A document is to convert when no file holds its revision; a file is to remove when no
    document read has its path, unless a problem was found, as a run would then keep it.
    Pandoc runs for its version alone, which names revisions; raises
    ``PandocFailedError`` when it gives none. ``worklog.end`` says at INFO what a run
    would do.
    """
    read = read_worklog(folder, archives=archives)
    converter = pandoc.org_converter()
    held = {identifier: matter.revision for identifier, (matter, _) in existing(docs).items()}
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
        len(read.documents), to_convert, to_remove, read.html, read.problems, read.warnings
    )
