"""The work log's fetch: its folder, read in place, into its source's copy store.

``read_worklog`` reads the folder and splits it into documents, as ``worklog`` says;
``fetch_worklog`` keeps what it read in the copy store, as ``copies.fetched`` decides, a
store's first fetch first carrying over the dates and the as-of time that the mirror
holds (``carried_over``). Reading is a span, and the events are those of
``docs/reference/telemetry/fetch.md``.
"""

from __future__ import annotations

import contextlib
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.names import WORKLOG_SCOPE_TYPE, RefusedError
from kb_mcp.kernel.records import Outcome, OutcomeWarning, Problem, Record
from kb_mcp.mirror.adapters.markdown import documents, load
from kb_mcp.mirror.adapters.source_files import SOURCE_FILE, source_file
from kb_mcp.mirror.domain.mirror import scope_name
from kb_mcp.sources.worklog import DAY_TYPE, ENTRY_TYPE, MEETING_TYPE
from kb_mcp.sources.worklog.fetch.adapters import files
from kb_mcp.sources.worklog.fetch.adapters.copy_store import CopyStore
from kb_mcp.sources.worklog.fetch.domain.copies import Carried, Copies, fetched
from kb_mcp.sources.worklog.fetch.domain.worklog import (
    TODO,
    TODO_ARCHIVE,
    WorklogDocument,
    WorklogFrontMatter,
    held_back,
    journal,
    linked_back,
    transcript_ids,
    transcripts,
    worklog_globs,
    writable,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from kb_mcp.config.settings import Settings
    from kb_mcp.kernel.names import Detail
    from kb_mcp.sources.worklog.fetch.domain.worklog import OrgText
    from kb_mcp.sources.worklog.settings import WorklogTable

TRACER = trace.get_tracer(__name__)
# Why a meeting is a warning: its link reaches no transcript found.
UNLINKED = "its :MEETING: link reaches no transcript found"
# Why a file of the mirror that does not read is a problem when a store begins, a
# document's or its source's, and what it holds back: no document's copy.
NOT_CARRIED = "its dates are not carried over"
NO_AS_OF = "its as-of time is not carried over"
NOTHING = "nothing"


class Read(Record):
    """The work log's documents to keep, in order, and the HTML transcripts left out.

    The documents are those read that draw on no file not read. Problems keep every
    document's last copy; warnings, such as two transcripts of one id, do not. A
    problem's ``where`` is the path from the work log's folder, never its content;
    ``held_back`` gives, by that place, what keeps its last copy for it, as the domain's
    function ``held_back`` says.
    """

    documents: tuple[WorklogDocument, ...]
    html: int
    problems: tuple[Problem, ...]
    held_back: dict[str, str]
    warnings: tuple[OutcomeWarning, ...]


class WorklogFetched(Record):
    """What a fetch of the work log did, or in a dry run would do, to its copy store.

    ``documents`` read, of which ``new`` and ``changed``, their revision another; ``gone``,
    those that a read without a problem no longer found, which left the store; ``html``,
    the HTML transcripts left out; ``held_back``, by each problem's place, what keeps its
    last copy for it.
    """

    documents: int
    new: int
    changed: int
    gone: int
    html: int
    held_back: dict[str, str]

    def text(self, _detail: Detail) -> str:
        """Write the counts of documents read, new, changed, gone, of HTML transcripts left out."""
        return (
            f"documents read: {self.documents}\n"
            f"new: {self.new}\n"
            f"changed: {self.changed}\n"
            f"gone: {self.gone}\n"
            f"HTML left out: {self.html}\n"
        )


def read_worklog(folder: Path, *, archives: bool) -> Read:
    """Read the work log under ``folder``: its entries, days and meetings, then its transcripts.

    A meeting links to the id of its transcript, found in this run, read or not, and a
    transcript read links back to it. Without ``archives``, the archive file,
    ``transcripts/archive/``, ``meetings/archive/`` and the subtrees tagged ARCHIVE are
    left out. A file not read is a problem, named by its path, with what it holds back,
    as ``held_back`` says; the documents that draw on it are left out, as ``writable``
    says, so that a fetch takes none of them. The span
    ``worklog.read`` holds the reading; ``worklog.read`` says at INFO what was read.
    ``worklog.unlinked``, a warning, says how many meetings' ``:MEETING:`` link no
    transcript found, and the first by its file, else its id: never a problem, so that it
    holds no removal back, but a warning of the outcome, each meeting by its file or id.
    Two transcripts of one id are a warning too, and each one an event,
    ``worklog.same_id``.
    """
    with TRACER.start_as_current_span("worklog.read"):
        org_files = files.listed(folder, archives=archives)
        unread = [(each.where, each.reason) for each in org_files.problems]
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
            PurePosixPath(each.where)
            for each in org_files.problems
            if each.reason == files.LINKS_OUT
        ]
        ids, warnings = transcript_ids([*org_files.paths, *out], archives=archives)
        problems = [Problem(where=where, reason=reason) for where, reason in unread]
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
    for each in warnings:
        log.warning("worklog.same_id", reason=f"{each.where}: {each.reason}")
    return Read(
        documents=tuple(documents_read),
        html=org_files.html,
        problems=tuple(problems),
        held_back={where: held_back(where, ids) for where, _ in unread},
        warnings=(
            *warnings,
            *(OutcomeWarning(where=each, reason=UNLINKED) for each in unlinked),
        ),
    )


def carried_over(docs: Path, source: str) -> tuple[Copies, list[Problem]]:
    """Give what a work log's copy store begins with: what its files of the mirror hold.

    By its id, the path, created and updated dates of each document of the files of
    ``source``'s folders of ``docs`` that ``worklog_globs`` finds, those that its prepare
    writes, in today's front matter or the former one, so that each document keeps its dates,
    and its file until a read takes it; and the as-of time of its one scope that its
    source's file holds, the moment of the former version's last read without a problem,
    so that a fetch with a problem leaves it. A file that does not read, or holds no
    document of the work log's rules, is a problem by its path, never its content: what it
    holds is not carried over, and so lost.
    """
    carried: dict[str, Carried] = {}
    problems: list[Problem] = []
    for file in documents(docs, worklog_globs(source)):
        path = file.relative_to(docs).as_posix()
        try:
            matter, _ = load(file.read_text(encoding="utf-8"), path)
            WorklogFrontMatter(**matter.model_dump())
        except (OSError, ValueError) as error:
            # A refusal names the file or the key; any other message could quote content.
            named = isinstance(error, RepresentationError | RefusedError)
            reason = str(error) if named else type(error).__name__
            problems.append(Problem(where=path, reason=f"{reason}; {NOT_CARRIED}"))
            continue
        carried[matter.id] = Carried(path=path, created=matter.created, updated=matter.updated)
    try:
        held = source_file(docs, source)
    except (OSError, RepresentationError) as error:
        held, path = None, f"{source}/{SOURCE_FILE}"
        # A refusal names the file and the key; any other message could quote content.
        named = isinstance(error, RepresentationError)
        reason = str(error) if named else f"{path}: {type(error).__name__}"
        problems.append(Problem(where=path, reason=f"{reason}; {NO_AS_OF}"))
    as_of = None if held is None else held.as_of.get(scope_name(WORKLOG_SCOPE_TYPE, source))
    return Copies(documents={}, migrated=carried, as_of=as_of), problems


def fetch_worklog(
    settings: Settings,
    table: WorklogTable,
    source: str,
    now: Callable[[], datetime],
    *,
    dry_run: bool,
) -> Outcome[WorklogFetched]:
    """Read ``source``'s work log, as its table says, into its copy store; or say what changes.

    A store never written first takes the dates and the as-of time of the source's files
    of the mirror, as ``carried_over`` reads them, and is written so before the read,
    whatever the read then meets; each file of the mirror that does not read is a problem
    of the fetch, which holds back ``NOTHING``. The read, begun at ``now()``, is then kept
    as ``fetched`` says, complete when the fetch met no problem. Without the table's
    ``archives``, the archive file, ``transcripts/archive/``, ``meetings/archive/`` and the
    subtrees tagged ARCHIVE are left out. A dry run takes no lock and writes nothing, and
    ends not run, or failed for a problem found.

    Raises ``StoreBusyError`` while another run writes the store, and
    ``RepresentationError`` for a store that does not read. ``worklog.carried`` says at
    INFO how many dates a store began with, and how many files of the mirror did not
    read; ``worklog.fetched`` at INFO what the read found.
    """
    store = CopyStore(settings.copies, source)
    log = structlog.get_logger()
    with contextlib.nullcontext() if dry_run else store.writing():
        stored = store.read()
        carried: list[Problem] = []
        if stored is None:
            stored, carried = carried_over(settings.docs, source)
            log.info("worklog.carried", documents=len(stored.migrated), not_read=len(carried))
            if not dry_run:
                store.put(stored)
        at = now()
        read = read_worklog(table.path, archives=table.archives)
        problems = (*carried, *read.problems)
        copies = fetched(stored, read.documents, at, complete=not problems)
        if not dry_run:
            store.put(copies)
    revisions = {key: each.revision for key, each in stored.documents.items()}
    found = {each.id: copies.documents[each.id].revision for each in read.documents}
    counts = WorklogFetched(
        documents=len(found),
        new=len(found.keys() - revisions.keys()),
        changed=sum(
            1 for key, revision in found.items() if revisions.get(key, revision) != revision
        ),
        gone=len(revisions.keys() - copies.documents.keys()),
        html=read.html,
        held_back={**dict.fromkeys((each.where for each in carried), NOTHING), **read.held_back},
    )
    log.info(
        "worklog.fetched",
        documents=counts.documents,
        new=counts.new,
        changed=counts.changed,
        gone=counts.gone,
        problems=len(problems),
    )
    return Outcome.of(
        counts,
        problems,
        read.warnings,
        otherwise="not run" if dry_run else "done",
    )
