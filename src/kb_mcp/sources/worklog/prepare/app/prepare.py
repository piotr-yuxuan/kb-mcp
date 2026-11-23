"""The work log's prepare: what its fetch kept in its copy store, as Markdown files of the mirror.

It converts each document's text through the source's rows of the cache of conversions,
and hands every file to ``mirror_files``, which writes those that changed and removes,
under the source's folder alone, those of documents gone. It reads nothing of the work
log's folder, and nothing of the mirror but what ``mirror_files`` compares: deleting the
source's folder of the mirror and preparing again gives it back, converting nothing. A
run that meets a problem, a conversion that failed, removes no file, nor does one while a
document carried over from the mirror waits for its first read, so that its file stays,
but the old file of a document written again under another path, which no other
document of the store could own; each problem says what it held back. Building and
writing are each a span; each document is counted, and each conversion timed, by its
document type, as ``docs/reference/telemetry/prepare.md`` lists them.
"""

from __future__ import annotations

import copy
import time
from datetime import UTC
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from kb_mcp.kernel.names import WORKLOG_SCOPE_TYPE
from kb_mcp.kernel.records import Outcome, Problem, Record
from kb_mcp.mirror.adapters.instruments import CONVERSION_DURATION, DOCUMENTS
from kb_mcp.mirror.adapters.markdown import dump
from kb_mcp.mirror.adapters.mirror_files import Changes, write_changed
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.mirror.adapters.source_files import SOURCE_FILE, dumped
from kb_mcp.mirror.domain.mirror import (
    PARTICIPANT,
    Link,
    Mention,
    SourceFile,
    document_id,
    scope_name,
)
from kb_mcp.mirror.domain.mirror_text import one_line
from kb_mcp.observability.progress import task
from kb_mcp.sources.worklog.fetch.domain.worklog import TYPE_ROLES, WorklogFrontMatter
from kb_mcp.sources.worklog.prepare.adapters.owned import worklog_owned
from kb_mcp.sources.worklog.prepare.domain.layout import places, retired, worklog_path

if TYPE_CHECKING:
    from pathlib import Path

    from kb_mcp.kernel.names import Detail
    from kb_mcp.mirror.adapters.conversions import Conversions
    from kb_mcp.mirror.domain.mirror import FrontMatter
    from kb_mcp.sources.worklog.fetch.domain.copies import Copies

TRACER = trace.get_tracer(__name__)


class WorklogCounts(Record):
    """What a prepare did: documents prepared, conversions run and reused, files changed.

    ``converted`` counts the conversions pandoc ran, ``reused`` those the cache gave;
    ``held_back`` gives, by each problem's place, what keeps its last copy for it.
    """

    documents: int
    converted: int
    reused: int
    changes: Changes
    held_back: dict[str, str]

    def text(self, _detail: Detail) -> str:
        """Write the counts of documents, of conversions run and reused, of files."""
        return (
            f"documents: {self.documents}\n"
            f"converted by pandoc: {self.converted}\n"
            f"reused from the cache: {self.reused}\n"
            f"files written: {self.changes.written}\n"
            f"files unchanged: {self.changes.unchanged}\n"
            f"files removed: {self.changes.removed}\n"
        )


class WorklogPlanned(Record):
    """What a prepare would do: the documents that it would write, the files it would remove.

    What pandoc would convert is not counted, as a dry run opens no cache.
    """

    documents: int
    to_remove: int

    def text(self, _detail: Detail) -> str:
        """Write the counts of documents, and of files to remove."""
        return f"documents: {self.documents}\nfiles to remove: {self.to_remove}\n"


def prepare_worklog(
    copies: Copies, docs: Path, conversions: Conversions, *, source: str
) -> Outcome[WorklogCounts]:
    """Mirror what a work log's copy store holds into the folder of ``docs`` of its ``source``.

    Each document's text is converted through ``conversions``, the source's rows of the
    cache; a conversion that fails is a problem by the document's org file and id, never
    its content, which holds back that id. A link is written only when its other end has
    a file at its place once the run is done, as ``places`` gives it: one written in it,
    or one that stays, of a document whose conversion failed, or carried over from the
    mirror until a read takes it; never a file by its name alone. The source's file beside
    its documents says the roles that each of its types takes and the store's as-of time,
    written whenever the store holds a document. A run that found a problem, or whose
    store holds a carried date, removes no file but the old ones of documents written, as
    ``retired`` tells them; one that found none deletes the source's conversions that it
    did not use.

    The task ``work-log documents`` reports each document, by its title; the spans
    ``worklog.convert`` and ``worklog.write`` hold building the files and writing them.
    ``worklog.document`` says at DEBUG each document, by its path, id, title and type;
    ``worklog.end`` at INFO the files written and the conversions. Each document is
    counted by its outcome and document type, and each conversion timed.
    """
    log = structlog.get_logger()
    scope = scope_name(WORKLOG_SCOPE_TYPE, source)
    problems: list[Problem] = []
    held: dict[str, str] = {}
    ready: dict[PurePosixPath, tuple[FrontMatter, str]] = {}
    with (
        TRACER.start_as_current_span("worklog.convert"),
        task("work-log documents", len(copies.documents)) as built,
    ):
        for each in built.each(copies.documents.values(), lambda one: one.title):
            typed = {"kb_mcp.type": each.type}
            began = time.perf_counter()
            try:
                body = conversions.markdown(each.text)
            except PandocFailedError as error:
                where = f"{each.file}, {each.id}"
                problems.append(Problem(where=where, reason=str(error)))
                held[where] = each.id
                DOCUMENTS.add(1, {"kb_mcp.outcome": "failed", **typed})
                continue
            CONVERSION_DURATION.record(time.perf_counter() - began, typed)
            DOCUMENTS.add(1, {"kb_mcp.outcome": "mirrored", **typed})
            matter = WorklogFrontMatter(
                source=source,
                type=each.type,
                id=each.id,
                key=None,
                title=one_line(each.title),
                scope=scope,
                status=one_line(each.status),
                subtype=None,
                labels=tuple(one_line(label) for label in each.labels),
                people=tuple(
                    Mention(role=PARTICIPANT, name=name)
                    for name in dict.fromkeys(one_line(person) for person in each.people)
                    if name
                ),
                parent=None,
                links=tuple(
                    Link(relation=relation, document=document_id(source, other))
                    for relation, other in each.links
                ),
                created=each.created,
                updated=each.updated,
                version=None,
                revision=each.revision,
                url=None,
                breadcrumb=tuple(one_line(part) for part in each.breadcrumb),
            )
            path = worklog_path(source, each.type, each.id, each.title)
            ready[path] = (matter, body)
            log.debug(
                "worklog.document", path=str(path), id=each.id, title=each.title, type=each.type
            )
    written = {matter.id for matter, _ in ready.values()}
    known = copies.documents.keys() | copies.migrated.keys()
    found = worklog_owned(docs, source)
    placed = places(copies, source)
    remove = not problems and not copies.migrated
    # Unless the run removes what it does not write, the files that go are the old ones of
    # documents written; any other stays. A link's other end is a document whose place
    # holds a file once the run is done.
    old = retired(found - placed.keys(), known, written)
    left = ready.keys() | (set() if remove else found - old)
    ends = {document_id(source, each) for path, each in placed.items() if path in left}
    wanted: dict[PurePosixPath, bytes | Path] = {
        path: dump(
            copy.replace(
                matter, links=tuple(link for link in matter.links if link.document in ends)
            ),
            body,
        ).encode()
        for path, (matter, body) in ready.items()
    }
    if copies.documents:
        # The source's file beside its documents: the roles that each of its types takes,
        # and its one scope's as-of time, the moment of the last read without a problem.
        as_of = {} if copies.as_of is None else {scope: copies.as_of.astimezone(UTC)}
        wanted[PurePosixPath(source, SOURCE_FILE)] = dumped(
            SourceFile(roles=TYPE_ROLES, as_of=as_of)
        )
    with TRACER.start_as_current_span("worklog.write"):
        changes = write_changed(docs, wanted, lambda _: found, remove=remove, retired=old)
        pruned = 0 if problems else conversions.drop_unused()
    log.info(
        "worklog.end",
        documents=len(ready),
        written=changes.written,
        unchanged=changes.unchanged,
        removed=changes.removed,
        converted=conversions.converted,
        reused=conversions.reused,
        pruned=pruned,
        problems=len(problems),
    )
    return Outcome.of(
        WorklogCounts(
            documents=len(ready),
            converted=conversions.converted,
            reused=conversions.reused,
            changes=changes,
            held_back=held,
        ),
        problems,
    )


def plan_worklog(copies: Copies, docs: Path, *, source: str) -> Outcome[WorklogPlanned]:
    """Say what preparing what a work log's copy store holds would do, writing nothing.

    It ends not run. A file is to remove when no document of the store has its path,
    unless the store holds a carried date, as a run would then keep it, but the old file
    of a document of the store, as ``retired`` tells it; what pandoc would convert is not
    counted, nor so what a conversion that fails would keep. ``worklog.end`` says at INFO
    what a run would do.
    """
    wanted = {
        worklog_path(source, each.type, each.id, each.title) for each in copies.documents.values()
    }
    known = copies.documents.keys() | copies.migrated.keys()
    stray = worklog_owned(docs, source) - places(copies, source).keys()
    to_remove = len(retired(stray, known, copies.documents.keys()) if copies.migrated else stray)
    structlog.get_logger().info("worklog.end", documents=len(wanted), to_remove=to_remove)
    return Outcome.of(
        WorklogPlanned(documents=len(wanted), to_remove=to_remove), otherwise="not run"
    )
