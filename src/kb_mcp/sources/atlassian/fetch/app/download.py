"""Downloading the documents of spaces and projects updated in a period.

Each space, project, round of probes and merge of users is a span of the run's trace;
each document fetched is a trace of its own, ``download.document``, linked to the run's,
since Tempo drops a trace past 5 MB, which one trace of all a run's requests could pass.
What is fetched, failed or skipped is counted and logged, as
``docs/reference/telemetry/download.md`` lists it.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from itertools import batched
from typing import TYPE_CHECKING, Literal

import structlog
from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.trace import StatusCode
from pydantic import ConfigDict, Field

from kb_mcp.kernel.content import BlogPost, Issue, Page
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.kernel.names import IDENTIFIER
from kb_mcp.kernel.record import Record
from kb_mcp.observability.adapters.progress import task
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.http import (
    SignInNeededError,
    Site,
    SiteError,
    TooManyFailuresError,
)
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import (
    REPRESENTATIONS,
    RawStore,
    Unreadable,
)
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import sign_in
from kb_mcp.sources.atlassian.fetch.domain.coverage import (
    Coverage,
    Extension,
    Reason,
    Target,
    Window,
    window,
)
from kb_mcp.sources.atlassian.fetch.domain.deletions import (
    Answer,
    Tombstone,
    after_probes,
    answer_of,
    probing_order,
    too_many_gone,
)
from kb_mcp.sources.atlassian.fetch.domain.files import skip_reason

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.kernel.content import Attachment, Document, Listed
    from kb_mcp.sources.atlassian.fetch.adapters.http import ReadPage, Request
    from kb_mcp.sources.atlassian.fetch.domain.period import Period

    type SnapshotRequests = Callable[[Listed], dict[str, tuple[Request, ReadPage | None]]]

# A listing longer than this many pages is refused rather than followed.
MAX_PAGES = 400
# Folders followed up from the pages of one space, at most.
MAX_FOLDERS = 1000
# Documents absent from their listing that one run probes, at most; the rest wait.
MAX_PROBES = 200
HTTP_NOT_FOUND = 404
# The kinds of Confluence documents that a space lists.
KINDS: tuple[type[Page | BlogPost], ...] = (Page, BlogPost)
# Jira reads JQL dates in the user's time zone, up to 14 hours off UTC, and a date
# stands for its midnight: two days on each side always cover the period.
JQL_MARGIN = timedelta(days=2)

# How each kind of document is read from its listing, and which GETs make its snapshot.
LISTED: dict[type[Document], Callable[[Fields], Listed]] = {
    Page: partial(confluence_v2.listed, kind=Page),
    BlogPost: partial(confluence_v2.listed, kind=BlogPost),
    Issue: jira_v3.listed,
}
SNAPSHOT_REQUESTS: dict[type[Document], SnapshotRequests] = {
    Page: confluence_v2.snapshot_requests,
    BlogPost: confluence_v2.snapshot_requests,
    Issue: jira_v3.snapshot_requests,
}
TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# What a run did, by outcome: documents fetched or failed; files downloaded, failed or
# skipped; the bytes of the files downloaded.
DOCUMENTS = METER.create_counter(
    "kb_mcp.download.documents", unit="{document}", description="Documents fetched, by outcome"
)
FILES = METER.create_counter(
    "kb_mcp.download.files", unit="{file}", description="Attached files, by outcome"
)
BYTES = METER.create_counter(
    "kb_mcp.download.bytes", unit="By", description="Bytes of the attached files downloaded"
)


class Report(Record):
    """What a run did, by count; it names nothing that the site served."""

    model_config = ConfigDict(frozen=False)

    counts: Counter[str] = Field(default_factory=Counter)

    def add(self, what: str, number: int = 1) -> None:
        """Count something that happened."""
        self.counts[what] += number

    def failed(self, what: str, error: Exception) -> None:
        """Count a failure by the refused field's path, or by the failed GET's status.

        The messages of these two errors hold paths and statuses only; any other error is
        counted by its class, since its message could hold content.
        """
        known = isinstance(error, (RepresentationError, SiteError))
        self.add(f"{what} failed: {error if known else type(error).__name__}")

    @property
    def failures(self) -> int:
        """Count what failed."""
        return sum(number for what, number in self.counts.items() if " failed: " in what)


def label(kind: type[Document]) -> str:
    """Name a kind of document in the report, as ``confluence pages``."""
    return f"{kind.source} {kind.kind}"


@dataclass
class Download:
    """One run over a site, into a store: each target's window, and a cap on attached files.

    Each target named has a window, or none when it is skipped, after --until. With
    ``plan``, the run lists and decides, and fetches and writes nothing. ``covered``
    names the targets whose listing was read whole, with the period fetched, so that
    their coverage can grow, and ``first_failed`` the update time of each one's earliest
    document found and not stored whole; ``held``, the targets skipped and those read
    whole whose coverage stays as it was, and why. ``failed_targets`` names the user's
    own keys that failed, for the command to show; they never enter the report.
    """

    site: Site
    store: RawStore
    max_file_bytes: int
    now: Callable[[], datetime]
    report: Report = field(default_factory=Report)
    failed_targets: list[str] = field(default_factory=list)
    authors: set[str] = field(default_factory=set)
    windows: Mapping[Target, Window | None] = field(default_factory=dict)
    plan: bool = False
    covered: dict[Target, Period] = field(default_factory=dict)
    first_failed: dict[Target, datetime] = field(default_factory=dict)
    held: dict[Target, str] = field(default_factory=dict)
    tombstones: dict[tuple[str, str], Tombstone] = field(default_factory=dict)
    absent: dict[str, tuple[dict[tuple[str, str], str], int, dict[tuple[str, str], Tombstone]]] = (
        field(default_factory=dict)
    )

    def run(self, spaces: Sequence[str], projects: Sequence[str]) -> None:
        """Download every space and project named, after checking that the session holds.

        Raises SignInNeededError, before anything is written, when the session no longer
        holds. A source that does not answer at all (a site without Jira) is counted as a
        failure, and its targets skipped. A target without a window is skipped too, and
        asked nothing. The task ``targets`` reports those of the sources that answer,
        each by its key.
        """
        self.held |= {target: "after --until" for target, w in self.windows.items() if w is None}
        confluence = bool(spaces) and self.reachable(
            "confluence", confluence_v2.current_user_request(), confluence_v2.signed_in
        )
        jira = bool(projects) and self.reachable(
            "jira", jira_v3.myself_request(), jira_v3.signed_in
        )
        answered_spaces = spaces if confluence else ()
        answered_projects = projects if jira else ()
        with task("targets", len(answered_spaces) + len(answered_projects)) as targets:
            for key in targets.each(answered_spaces, str):
                target = Target(source="confluence", key=key)
                window = self.windows[target]
                if window is not None and self.space(target, window):
                    self.covered[target] = window.period
            if not self.plan:
                self.probe_absent()
            for key in targets.each(answered_projects, str):
                target = Target(source="jira", key=key)
                window = self.windows[target]
                if window is not None and self.project(target, window):
                    self.covered[target] = window.period
        if not self.plan:
            self.users()

    def reachable(self, source: str, request: Request, signed_in: Callable[[Fields], bool]) -> bool:
        """GET the signed-in user of a source; say whether the source answers.

        Raises SignInNeededError when it answers as to nobody.
        """
        try:
            user = Fields(self.site.json(request), "user")
        except (RepresentationError, SiteError) as error:
            self.report.failed(source, error)
            return False
        if not signed_in(user):
            raise SignInNeededError
        return True

    def collect(
        self, request: Request, read_page: ReadPage, paged: Callable[[], None] = lambda: None
    ) -> list[object]:
        """Follow a paged listing to its end, and return every result as received.

        ``paged`` hears of each page read.
        """
        results: list[object] = []
        for _ in range(MAX_PAGES):
            page, following = read_page(Fields(self.site.json(request), "response"), request)
            results += [item.value for item in page]
            paged()
            if following is None:
                return results
            request = following
        message = f"a listing of more than {MAX_PAGES} pages"
        raise SiteError(message)

    def documents(self, kind: type[Document], entries: Iterable[object]) -> list[Listed]:
        """Read what decides a fetch from a listing's entries, counting those refused."""
        found: list[Listed] = []
        for entry in entries:
            try:
                found.append(LISTED[kind](Fields(entry, kind.kind)))
            except RepresentationError as error:
                self.report.failed(f"{label(kind)} listed", error)
        self.report.add(f"{label(kind)}: listed", len(found))
        return found

    def space(self, target: Target, window: Window) -> bool:
        """List a space whole, store its listings, and fetch what changed in its window.

        The task ``listing`` reports the pages of its listings read, and ``fetch_listed``
        the documents. Return whether the space was listed whole. All is the span
        ``download.space``, an error when the space could not be listed.
        """
        key = target.key
        with TRACER.start_as_current_span(
            "download.space", attributes={"kb_mcp.target": key}
        ) as span:
            try:
                found = self.collect(confluence_v2.space_request(key), confluence_v2.listing_page)
                space = confluence_v2.space(Fields(found[0], "space")) if found else None
                if space is None:
                    self.failed_targets.append(f"space {key}: not found")
                    self.report.add("confluence spaces failed: not found")
                    span.set_status(StatusCode.ERROR, "not found")
                    return False
                page_listing = confluence_v2.listing_request(space.id, Page)
                post_listing = confluence_v2.listing_request(space.id, BlogPost)
                with task("listing") as listing:
                    pages = self.collect(page_listing, confluence_v2.listing_page, listing.advance)
                    posts = self.collect(post_listing, confluence_v2.listing_page, listing.advance)
            except (RepresentationError, SiteError) as error:
                self.failed_targets.append(f"space {key}: {error}")
                self.report.failed("confluence spaces", error)
                span.set_status(StatusCode.ERROR, str(error))
                return False
            documents = [*self.documents(Page, pages), *self.documents(BlogPost, posts)]
            if not self.plan:
                # By id alone, as the last listing is read: an entry refused for its other
                # fields still names its document, which is then not absent.
                listed = {
                    Page: confluence_v2.entry_ids(pages),
                    BlogPost: confluence_v2.entry_ids(posts),
                }
                self.track(space.id, listed)
                folders = self.folders(pages)
                self.store.put_space(found[0], pages, posts, folders, listed_at=self.now())
            self.fetch_listed(target, documents, window)
            return True

    def track(self, space_id: str, listed: Mapping[type[Document], set[str]]) -> None:
        """Record, as pending, what the space's last listing named and the new one does not.

        The absent are the documents the last listing named, read by id alone, and the
        store holds, and those already tombstoned in the space. The record is written
        before the listing is replaced, so that no absent document is lost to a run that
        stops; they are probed once every space of the run is listed.
        """
        known = {key: stone for key, stone in self.tombstones.items() if stone.space_id == space_id}
        absent: dict[tuple[str, str], str] = {}
        stored = 0
        for kind in KINDS:
            before = self.store.listed_ids(space_id, kind) & self.store.stored_ids(kind)
            stored += len(before)
            again = {key[1] for key in known if key[0] == kind.kind}
            absent |= {(kind.kind, each): space_id for each in (before | again) - listed[kind]}
        self.absent[space_id] = (absent, stored, known)
        others = {
            key: stone for key, stone in self.tombstones.items() if stone.space_id != space_id
        }
        self.tombstones = {**others, **after_probes(known, absent, {}, self.now())}
        self.store.put_tombstones(self.tombstones.values())

    def probe_absent(self) -> None:
        """Probe what each space no longer lists, and record what is gone.

        Those not confirmed are probed, at most ``MAX_PROBES`` a space and a run, those
        on their way first; the rest stay pending. A document answering from another
        space is followed there once that space's stored listing names it, and stays
        pending until then. Raises SignInNeededError when too many answer gone and the
        session no longer holds; when the site does not answer, nothing is believed. The
        task ``probes`` reports a space's probes, each by its document's id; all is the
        span ``download.probes``.
        """
        canary = (confluence_v2.current_user_request(), confluence_v2.signed_in)
        kept = {each.id for each in self.store.spaces() if not isinstance(each, Unreadable)}
        with TRACER.start_as_current_span("download.probes"):
            for space_id, (absent, stored, before) in self.absent.items():
                known = {k: s for k, s in self.tombstones.items() if s.space_id == space_id}
                # By the tombstones as they stood before this run: those on their way first.
                order = probing_order(absent, before)[:MAX_PROBES]
                with task("probes", len(order)) as probes:
                    answers = {
                        k: a
                        for k in probes.each(order, lambda key: key[1])
                        if (a := self.probe(k, kept))
                    }
                if too_many_gone(answers, stored) and not self.reachable("confluence", *canary):
                    answers = {}  # the site stopped answering: believe none of these answers
                now = after_probes(known, absent, answers, self.now())
                others = {k: s for k, s in self.tombstones.items() if s.space_id != space_id}
                self.tombstones = {**others, **now}
                self.store.put_tombstones(self.tombstones.values())
                probed = "confluence documents: probed, absent from their listing"
                self.report.add(probed, len(answers))
                waiting = sum(1 for stone in now.values() if stone.first_gone is None)
                self.report.add("confluence documents: absent, waiting for a probe", waiting)

    def probe(self, key: tuple[str, str], kept: set[str]) -> Answer | None:
        """GET a document absent from its listing, and say what became of it."""
        try:
            response = Fields(self.site.json(confluence_v2.probe_request(*key)), "probe")
            found_space, status = confluence_v2.whereabouts(response)
        except SiteError as error:
            if error.status == HTTP_NOT_FOUND:
                return Answer.GONE
            self.report.failed("confluence probes", error)
            return None
        except RepresentationError as error:
            self.report.failed("confluence probes", error)
            return None
        kind = Page if key[0] == Page.kind else BlogPost
        named = found_space in kept and key[1] in self.store.listed_ids(found_space, kind)
        return answer_of(found_space, status, kept, named=named)

    def folders(self, pages: Iterable[object]) -> list[object]:
        """GET every folder above the listed pages, following folders' own parents.

        A page entry that the adapter refuses is counted, and passed over here: it only
        loses its place under a folder in the tree.
        """
        wanted: list[str | None] = []
        for entry in pages:
            try:
                page = confluence_v2.document(Fields(entry, "pages"), Page)
            except RepresentationError as error:
                self.report.failed("confluence pages in the tree", error)
                continue
            if isinstance(page, Page) and page.parent_type == "folder":
                wanted.append(page.parent_id)
        found: dict[str, object] = {}
        while wanted:
            folder_id = wanted.pop()
            if folder_id is None or folder_id in found or not IDENTIFIER.fullmatch(folder_id):
                continue
            if len(found) >= MAX_FOLDERS:
                self.report.add("confluence folders: over the cap, left out", len(wanted) + 1)
                break
            try:
                response = self.site.json(confluence_v2.folder_request(folder_id))
                folder = confluence_v2.folder(Fields(response, "folder"))
            except (RepresentationError, SiteError) as error:
                self.report.failed("confluence folders", error)
                found[folder_id] = None
                continue
            found[folder_id] = response
            if folder.parent_type == "folder":
                wanted.append(folder.parent_id)
        return [response for response in found.values() if response is not None]

    def project(self, target: Target, window: Window) -> bool:
        """Search a project's issues updated in its window, and fetch what changed.

        The task ``listing`` reports the pages of the search read, and ``fetch_listed``
        the issues found. Return whether the search was read whole, each of its entries
        read: an entry that the adapter refuses has no update time for the coverage to
        stop at, so it holds the project's. All is the span ``download.project``, an error
        when the search could not be read.
        """
        key = target.key
        start = (window.period.start - JQL_MARGIN).date()
        end = (window.period.end + JQL_MARGIN).date()
        attributes = {"kb_mcp.target": key}
        with TRACER.start_as_current_span("download.project", attributes=attributes) as span:
            try:
                with task("listing") as listing:
                    search = jira_v3.search_request(key, start, end)
                    entries = self.collect(search, jira_v3.search_page, listing.advance)
            except (RepresentationError, SiteError) as error:
                self.failed_targets.append(f"project {key}: {error}")
                self.report.failed("jira projects", error)
                span.set_status(StatusCode.ERROR, str(error))
                return False
            if self.plan:
                self.count_files(entries, window.period)
            issues = self.documents(Issue, entries)
            self.fetch_listed(target, issues, window)
            if len(issues) < len(entries):
                self.held[target] = "entries refused"
                return False
            return True

    def fetch_listed(self, target: Target, documents: Sequence[Listed], window: Window) -> None:
        """Fetch what a target lists in its window and the store lacks; complete what it has.

        ``download.listed`` says at INFO how many documents the target lists, how many are
        in its window, stored already and to fetch, with the window's start and reason.
        The report counts, by kind, those in the window and those stored when --since gave
        the window; else those new or changed since the last fetch. Those stored get the
        files they lack, without a task; the task ``documents`` reports those to fetch,
        each by its id. ``first_failed`` keeps, for the target, the update time of the
        earliest not stored whole. A document listed twice, as an issue saved while its
        search pages through can shift another into the next page, is taken once.
        """
        in_window = list(
            dict.fromkeys(document for document in documents if document.updated in window.period)
        )
        stored: list[Listed] = []
        to_fetch: list[Listed] = []
        for document in in_window:
            (stored if self.store.has(document) else to_fetch).append(document)
        structlog.get_logger().info(
            "download.listed",
            target=str(target),
            listed=len(documents),
            in_window=len(in_window),
            stored=len(stored),
            to_fetch=len(to_fetch),
            start=window.period.start.isoformat(),
            reason=window.reason,
        )
        counted = (
            {"in the period": in_window, "already stored": stored}
            if window.reason == "given"
            else {"new or changed since the last fetch": to_fetch}
        )
        self.report.counts.update(
            f"{label(document.type)}: {what}" for what, each in counted.items() for document in each
        )
        failed = [each.updated for each in stored if not (self.plan or self.complete(each))]
        with task("documents", len(to_fetch)) as fetching:
            failed += [
                document.updated
                for document in fetching.each(to_fetch, lambda listed: listed.id)
                if not self.fetch(document)
            ]
        if failed:
            self.first_failed[target] = min(failed)

    def count_files(self, entries: Iterable[object], period: Period) -> None:
        """Count the files, and their bytes, that a run would download for these issues.

        An issue named twice by its search is counted once, as it would be fetched once.
        """
        counted: set[Listed] = set()
        for entry in entries:
            try:
                listed = jira_v3.listed(Fields(entry, "issues"))
                files = jira_v3.listed_attachments(Fields(entry, "issues"))
            except RepresentationError:
                continue  # counted by documents() already
            if listed.updated not in period or self.store.has(listed) or listed in counted:
                continue
            counted.add(listed)
            kept = [each for each in files if skip_reason(each, self.max_file_bytes) is None]
            self.report.add("files: to download", len(kept))
            self.report.add("files: bytes to download", sum(each.size for each in kept))

    def fetch(self, document: Listed) -> bool:
        """Fetch a listed document whose revision is not stored; say if it is stored whole.

        It is not when its fetch failed, its snapshot was refused, or a file it keeps
        failed; a plan counts it to fetch, and fails none. The fetch is a trace of its
        own, ``download.document``, linked to the span of the run's trace current when it
        begins, saying the document's id and kind; an error when the fetch fails, which
        is a warning, by the document's id.
        """
        what = label(document.type)
        if self.plan:
            self.report.add(f"{what}: to fetch")
            return True
        with TRACER.start_as_current_span(
            "download.document",
            context=Context(),  # no parent: the root of a trace of its own
            links=[trace.Link(trace.get_current_span().get_span_context())],
            attributes={"kb_mcp.document.id": document.id, "kb_mcp.document.kind": what},
        ) as span:
            try:
                responses = {
                    name: self.site.json(request) if read is None else self.collect(request, read)
                    for name, (request, read) in SNAPSHOT_REQUESTS[document.type](document).items()
                }
                whole = self.keep(document.type, responses)
            except (RepresentationError, SiteError) as error:
                self.report.failed(what, error)
                DOCUMENTS.add(1, {"kb_mcp.outcome": "failed"})
                span.set_status(StatusCode.ERROR, str(error))
                structlog.get_logger().warning(
                    "download.document_failed", id=document.id, kind=what, reason=str(error)
                )
                return False
            self.report.add(f"{what}: fetched")
            DOCUMENTS.add(1, {"kb_mcp.outcome": "fetched"})
            return whole

    def keep(self, kind: type[Document], responses: dict[str, object]) -> bool:
        """Download a snapshot's files, then store it with their digests; say if it is whole.

        A snapshot that its adapter refuses is stored all the same, without files: raw
        first, so that a fixed adapter reads it, and a later run downloads its files.
        Read, its document's title goes on the current span, and in ``download.document``
        at DEBUG; refused, it is a warning, without the id that it would have given. It is
        whole when read, with every file it keeps.
        """
        try:
            snapshot = REPRESENTATIONS[kind].snapshot(responses)
            document = snapshot.document
            trace.get_current_span().set_attribute("kb_mcp.document.title", document.title)
            structlog.get_logger().debug(
                "download.document", id=document.id, kind=label(kind), title=document.title
            )
        except RepresentationError as error:
            self.report.failed(f"{label(kind)} read", error)
            structlog.get_logger().warning(
                "download.document_unread", kind=label(kind), reason=str(error)
            )
            snapshot = None
        blobs, whole = self.files(snapshot.attachments) if snapshot else ({}, False)
        self.store.put(kind, responses, self.now(), blobs)
        if snapshot and snapshot.document.author and kind is not Issue:
            self.authors.add(snapshot.document.author.account_id)
        return whole

    def complete(self, document: Listed) -> bool:
        """Download the files that a stored snapshot should have and lacks.

        Return whether it is now whole: read, with every file it keeps.
        """
        try:
            stored = self.store.read(document)
        except (RepresentationError, ValueError, OSError) as error:
            self.report.failed(f"{label(document.type)} read", error)
            return False
        missing = [
            attachment
            for attachment in stored.snapshot.attachments
            if attachment.id not in stored.blobs
            and skip_reason(attachment, self.max_file_bytes) is None
        ]
        blobs, whole = self.files(missing)
        self.store.add_blobs(document, blobs)
        if stored.snapshot.document.author and document.type is not Issue:
            self.authors.add(stored.snapshot.document.author.account_id)
        return whole

    def files(self, attachments: Iterable[Attachment]) -> tuple[dict[str, str], bool]:
        """Download the attachments' files that are kept; return their digests by id.

        Return too whether every file kept was downloaded: a skip is no failure. A file
        skipped is said at INFO, one that failed is a warning, each by its id and its name.
        """
        log = structlog.get_logger()
        blobs: dict[str, str] = {}
        whole = True
        for attachment in attachments:
            named = {"id": attachment.id, "file_name": attachment.filename}
            reason = skip_reason(attachment, self.max_file_bytes)
            if reason is not None:
                self.report.add(f"files: skipped, {reason}")
                FILES.add(1, {"kb_mcp.outcome": "skipped"})
                log.info("download.file_skipped", **named, reason=reason)
                continue
            try:
                data = self.site.file(attachment.download, self.max_file_bytes)
            except SiteError as error:
                self.report.failed("files", error)
                FILES.add(1, {"kb_mcp.outcome": "failed"})
                log.warning("download.file_failed", **named, reason=str(error))
                whole = False
                continue
            if len(data) != attachment.size:  # a proxy's page, say, in the file's place
                self.report.add("files failed: not the size listed")
                FILES.add(1, {"kb_mcp.outcome": "failed"})
                log.warning("download.file_failed", **named, reason="not the size listed")
                whole = False
                continue
            blobs[attachment.id] = self.store.put_blob(data)
            self.report.add("files: downloaded")
            FILES.add(1, {"kb_mcp.outcome": "downloaded"})
            BYTES.add(len(data))
        return blobs, whole

    def users(self) -> None:
        """Merge the names of the Confluence authors seen into the users kept.

        All is the span ``download.users``.
        """
        with TRACER.start_as_current_span("download.users"):
            users: list[object] = []
            authors = sorted(self.authors)
            for chunk in batched(authors, confluence_v2.USERS_PER_REQUEST, strict=False):
                request = confluence_v2.users_request(chunk)
                try:
                    users += self.collect(request, confluence_v2.users_page)
                except (RepresentationError, SiteError) as error:
                    self.report.failed("confluence users", error)
            try:
                if users:
                    self.store.put_users(users)
            except RepresentationError as error:
                self.report.failed("confluence users", error)
                return
            self.report.add("confluence users: named", len(users))


class Targets(Record):
    """What a run downloads: spaces and projects, from when, and the largest file kept.

    ``since`` starts every target's window there; without it, each target catches up on
    what changed since its last fetch, as ``window`` rules. ``until`` ends the windows,
    by default when the run starts.
    """

    spaces: Sequence[str]
    projects: Sequence[str]
    max_file_bytes: int
    since: datetime | None = None
    until: datetime | None = None

    def windows(self, coverage: Coverage, now: datetime) -> dict[Target, Window | None]:
        """Return each target's window, None for one skipped; PeriodError for --until first.

        Raises PeriodError when --since does not come before the windows' end.
        """
        named = [Target(source="confluence", key=key) for key in self.spaces]
        named += [Target(source="jira", key=key) for key in self.projects]
        end = min(self.until, now) if self.until else now  # never past what a run can see
        return {target: window(coverage, target, self.since, end) for target in named}


class TargetWindow(Record):
    """A target of a run: its window, from ``start`` to ``end``, and why it starts there.

    A target skipped, its catch-up after --until, has none, as ``reason`` says.
    ``coverage`` is what the run made of the target's coverage, None when it wrote none:
    a dry run, or a target that the run did not finish.
    """

    target: Target
    start: datetime | None
    end: datetime | None
    reason: Reason | Literal["after --until"]
    coverage: Extension | None


def windows_of(
    windows: Mapping[Target, Window | None], coverage: Mapping[Target, Extension]
) -> tuple[TargetWindow, ...]:
    """Give each target's record: its window, and what became of its coverage."""
    return tuple(
        TargetWindow(
            target=target,
            start=None,
            end=None,
            reason="after --until",
            coverage=coverage.get(target),
        )
        if window is None
        else TargetWindow(
            target=target,
            start=window.period.start,
            end=window.period.end,
            reason=window.reason,
            coverage=coverage.get(target),
        )
        for target, window in windows.items()
    )


class Outcome(Record):
    """What a run did, the user's keys that failed, and the run's exit status.

    ``windows`` holds each target's window, and what became of its coverage; ``dry_run``
    says whether the run only planned.
    """

    report: Report
    failed_targets: list[str]
    status: ExitStatus | None
    windows: tuple[TargetWindow, ...] = ()
    dry_run: bool = False


def plan(
    settings: Settings,
    targets: Targets,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Outcome:
    """List and decide as a run would, and say what it would fetch; write nothing.

    Raises PeriodError when --since does not come before the windows' end.
    """
    store, report = RawStore(settings.raw), Report()
    windows = targets.windows(store.coverage(), now())
    planned = partial(Outcome, windows=windows_of(windows, {}), dry_run=True)
    try:
        client = sign_in(settings).client()
    except SignInNeededError:
        return planned(report=report, failed_targets=[], status=ExitStatus.SIGN_IN_AGAIN)
    with client:
        run = Download(
            Site(client, sleep=sleep),
            store,
            targets.max_file_bytes,
            now,
            report,
            windows=windows,
            plan=True,
        )
        try:
            run.run(targets.spaces, targets.projects)
        except SignInNeededError:
            return planned(
                report=report, failed_targets=run.failed_targets, status=ExitStatus.SIGN_IN_AGAIN
            )
        except TooManyFailuresError:
            report.add("runs: stopped, too many failures in a row")
            return planned(
                report=report, failed_targets=run.failed_targets, status=ExitStatus.FAILED
            )
    return planned(
        report=report,
        failed_targets=run.failed_targets,
        status=ExitStatus.FAILED if report.failures else ExitStatus.OK,
    )


def download(
    settings: Settings,
    targets: Targets,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Outcome:
    """Run a download signed in as the settings say, and save its report, even when stopped.

    Each target is fetched over its window. The coverage of every target listed whole
    grows as ``Coverage.extended`` rules, and the tombstones found are kept, even when
    the run stops; ``download.coverage`` says at INFO what became of each finished
    target's coverage, and why it was held, if it was. The status is ``OK`` when nothing
    failed, ``FAILED`` when something did, and ``SIGN_IN_AGAIN`` when the sign-in no
    longer holds or no session was saved. Raises PeriodError when --since does not come
    before the windows' end, and StoreBusyError when another run writes, both before
    anything is written.
    """
    report, failed_targets, status = Report(), [], None
    extensions: dict[Target, Extension] = {}
    store, started = RawStore(settings.raw), now()
    coverage = store.coverage()
    windows = targets.windows(coverage, started)
    signing = sign_in(settings)
    with store.writing():
        try:
            with signing.client() as client:
                run = Download(
                    Site(client, sleep=sleep),
                    store,
                    targets.max_file_bytes,
                    now,
                    report,
                    windows=windows,
                    tombstones=store.tombstones(),
                )
                failed_targets = run.failed_targets
                try:
                    run.run(targets.spaces, targets.projects)
                    status = ExitStatus.FAILED if report.failures else ExitStatus.OK
                except SignInNeededError:
                    status = ExitStatus.SIGN_IN_AGAIN
                except TooManyFailuresError:
                    status = ExitStatus.FAILED
                    report.add("runs: stopped, too many failures in a row")
                finally:
                    signing.keep(client)
                    log = structlog.get_logger()
                    for target, fetched in run.covered.items():
                        failed = run.first_failed.get(target)
                        coverage, outcome = coverage.extended(target, fetched, failed)
                        extensions[target] = outcome
                        reason = (
                            {"reason": "apart from what is covered"} if outcome == "held" else {}
                        )
                        log.info("download.coverage", target=str(target), outcome=outcome, **reason)
                    for target, why in run.held.items():
                        extensions[target] = "held"
                        log.info(
                            "download.coverage", target=str(target), outcome="held", reason=why
                        )
                    store.put_coverage(coverage)
                    store.put_tombstones(run.tombstones.values())
        except SignInNeededError:  # from the client: no session was saved
            status = ExitStatus.SIGN_IN_AGAIN
        finally:
            if status is None:
                report.add("runs: interrupted")
            elif status == ExitStatus.SIGN_IN_AGAIN:
                report.add("runs: stopped, sign-in needed")
            settings.runs.mkdir(parents=True, exist_ok=True)
            stamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            saved = {"status": status, "counts": dict(sorted(report.counts.items()))}
            (settings.runs / f"{stamp}.json").write_text(json.dumps(saved, indent=1), "utf-8")
    return Outcome(
        report=report,
        failed_targets=failed_targets,
        status=status,
        windows=windows_of(windows, extensions),
    )
