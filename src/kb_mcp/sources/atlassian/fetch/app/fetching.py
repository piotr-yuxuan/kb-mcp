"""Fetching the documents of spaces and projects updated in a period.

Each space, project, round of probes and merge of site users is a span of the run's trace;
each document fetched is a trace of its own, ``fetch.document``, linked to the run's,
since Tempo drops a trace past 5 MB, which one trace of all a run's requests could pass.
What is fetched, failed or skipped is counted and logged, as
``docs/reference/telemetry/fetch.md`` lists it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from copy import replace
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from itertools import batched
from typing import TYPE_CHECKING, Literal

import structlog
from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.trace import StatusCode
from pydantic import ConfigDict, Field, model_serializer

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.kernel.names import IDENTIFIER
from kb_mcp.kernel.records import Outcome, Problem, Record
from kb_mcp.observability.progress import task
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.http import (
    SignInNeededError,
    SiteClient,
    SiteError,
    TooManyFailuresError,
)
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import REPRESENTATIONS, RawStore
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import choose_sign_in, sites_of
from kb_mcp.sources.atlassian.fetch.domain.content import (
    CONFLUENCE_CLASSES,
    DOCUMENT_CLASSES,
    BlogPost,
    Issue,
    Page,
)
from kb_mcp.sources.atlassian.fetch.domain.coverage import (
    Coverage,
    CoverageChange,
    FetchWindow,
    Reason,
    Scope,
    fetch_window,
    whole_read_due,
)
from kb_mcp.sources.atlassian.fetch.domain.deletions import (
    DocumentKey,
    ProbeAnswer,
    Tombstone,
    after_probes,
    answer_of,
    probing_order,
    too_many_gone,
)
from kb_mcp.sources.atlassian.fetch.domain.files import skip_reason
from kb_mcp.sources.atlassian.fetch.domain.names import BLOGPOST, ISSUE, PAGE, PROJECT, SPACE

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

    from pydantic import SerializerFunctionWrapHandler

    from kb_mcp.config.settings import Settings
    from kb_mcp.kernel.names import Detail, Ending
    from kb_mcp.sources.atlassian.fetch.adapters.http import ReadPage, Request
    from kb_mcp.sources.atlassian.fetch.domain.content import Attachment, FetchedDocument, Listed
    from kb_mcp.sources.atlassian.fetch.domain.period import Period

    type SnapshotRequests = Callable[[Listed], dict[str, tuple[Request, ReadPage | None]]]
    type Whereabouts = Callable[[Fields], tuple[str, str | None]]

# A listing longer than this many pages is refused rather than followed.
MAX_PAGES = 400
# Folders followed up from the pages of one space, at most.
MAX_FOLDERS = 1000
# Documents absent from their listing that one fetch probes, at most; the rest wait.
MAX_PROBES = 200
HTTP_NOT_FOUND = 404
# Jira reads JQL dates in the signed-in site user's time zone, up to 14 hours off UTC, and
# a date stands for its midnight: two days on each side always cover the period.
JQL_MARGIN = timedelta(days=2)
# The counts that a short result shows: the documents fetched, or to fetch, of each type,
# and the files downloaded, or to download; then how the fetch stopped, if it did.
SHORT_COUNTS = (": fetched", ": to fetch", "files: downloaded", "files: to download")
STOPPED = "runs: "

# How each document type is read from its listing, and which GETs make its snapshot.
LISTED: dict[type[FetchedDocument], Callable[[Fields], Listed]] = {
    **{each: partial(confluence_v2.listed, document_class=each) for each in CONFLUENCE_CLASSES},
    Issue: jira_v3.listed,
}
SNAPSHOT_REQUESTS: dict[type[FetchedDocument], SnapshotRequests] = {
    **dict.fromkeys(CONFLUENCE_CLASSES, confluence_v2.snapshot_requests),
    Issue: jira_v3.snapshot_requests,
}
# How a document absent from its scope's whole read is asked for, and where its answer
# says it is: its scope as its listings are kept, and its own status if it has one.
PROBES: dict[type[FetchedDocument], tuple[Callable[[str], Request], Whereabouts]] = {
    Page: (partial(confluence_v2.probe_request, PAGE.plural), confluence_v2.whereabouts),
    BlogPost: (partial(confluence_v2.probe_request, BLOGPOST.plural), confluence_v2.whereabouts),
    Issue: (jira_v3.probe_request, jira_v3.whereabouts),
}
# Each document class by its document type's name, as a tombstone names it.
CLASSES = {each.document_type.name: each for each in DOCUMENT_CLASSES}
# What says, of each scope type by name, whether its source still signs in: the request of
# the signed-in site user, and how to read the answer.
SIGNED_IN: dict[str, tuple[Callable[[], Request], Callable[[Fields], bool]]] = {
    SPACE.name: (confluence_v2.current_user_request, confluence_v2.is_signed_in),
    PROJECT.name: (jira_v3.myself_request, jira_v3.is_signed_in),
}
TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# What a fetch did, by outcome: documents fetched or failed; files downloaded, failed or
# skipped; the bytes of the files downloaded.
DOCUMENTS = METER.create_counter(
    "kb_mcp.fetch.documents", unit="{document}", description="Documents fetched, by outcome"
)
FILES = METER.create_counter(
    "kb_mcp.fetch.files", unit="{file}", description="Attached files, by outcome"
)
BYTES = METER.create_counter(
    "kb_mcp.fetch.bytes", unit="By", description="Bytes of the attached files downloaded"
)


class FetchCounts(Record):
    """What a fetch did, by count, and each scope's window; it names nothing that the site served.

    ``windows`` holds each scope's window, and what became of its coverage, once the
    fetch ends; ``dry_run`` says whether the fetch only planned. Written, each count is a
    key beside them, its name holding a colon, which theirs do not.
    """

    model_config = ConfigDict(frozen=False)

    counts: Counter[str] = Field(default_factory=Counter)
    windows: tuple[ScopeFetchWindow, ...] = ()
    dry_run: bool = False

    @model_serializer(mode="wrap")
    def flat(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Write each count by its name, then the windows and whether a dry run."""
        written = handler(self)
        return {**written.pop("counts"), **written}

    def add(self, what: str, number: int = 1) -> None:
        """Count something that happened, by a name that holds a colon.

        Raises ValueError for a name without one, which could meet ``windows`` or
        ``dry_run`` once the counts are written beside them.
        """
        if ":" not in what:
            message = f"a count's name holds a colon: {what!r}"
            raise ValueError(message)
        self.counts[what] += number

    def text(self, detail: Detail) -> str:
        """Write the documents fetched by type and the files, or a dry run's.

        Detailed, and a dry run, begin with each scope's window, why it starts there, and
        what became of its coverage. Short also says how the fetch stopped, if it did;
        detailed gives every count of what the fetch did, or would do, failures by kind
        included.
        """
        windows = self.windows if detail == "detailed" or self.dry_run else ()
        said = [
            f"{each.scope}: "
            + (
                f"skipped, {each.reason}"
                if each.start is None or each.end is None
                else f"from {each.start.isoformat()} to {each.end.isoformat()}, {each.reason}"
            )
            + ("" if each.coverage is None else f"; coverage {each.coverage}")
            for each in windows
        ]
        shown = [
            (what, number)
            for what, number in sorted(self.counts.items())
            if detail == "detailed" or what.endswith(SHORT_COUNTS) or what.startswith(STOPPED)
        ]
        return "".join(f"{line}\n" for line in said) + "".join(
            f"{what}: {number}\n" for what, number in shown
        )


@dataclass
class Fetching:
    """One fetch of a source over its site, into its view of the store: each scope's window.

    And a cap on attached files. Its counts name each thing by the source, as
    ``confluence pages``. Each scope named has a window, or none when it is skipped, after
    --until. With
    ``plan``, the fetch lists and decides, and fetches and writes nothing. ``covered``
    names the scopes whose listing was read whole, with the period fetched, so that
    their coverage can grow, and ``first_failed`` the update time of each one's earliest
    document found and not stored whole; ``held``, the scopes skipped and those read
    whole whose coverage stays as it was, and why. ``problems`` holds each failure by its
    place, a scope, a document or a file, and its reason, as ``failed`` keeps it.
    ``due`` names the scopes searched by update time that this fetch also reads whole,
    and ``read_whole`` gathers every scope read whole. ``peers`` are the views of the
    other sources of the site, whose whole reads say, as the source's own do, which scopes
    are kept. ``snapshot_ids`` holds the ids of each document type that have a snapshot,
    read once a fetch, as the store held them when the fetch first tracked a scope of that
    type.
    """

    site: SiteClient
    store: RawStore
    max_file_bytes: int
    now: Callable[[], datetime]
    counts: FetchCounts = field(default_factory=FetchCounts)
    problems: list[Problem] = field(default_factory=list)
    authors: set[str] = field(default_factory=set)
    windows: Mapping[Scope, FetchWindow | None] = field(default_factory=dict)
    plan: bool = False
    covered: dict[Scope, Period] = field(default_factory=dict)
    first_failed: dict[Scope, datetime] = field(default_factory=dict)
    held: dict[Scope, str] = field(default_factory=dict)
    tombstones: dict[DocumentKey, Tombstone] = field(default_factory=dict)
    absent: dict[Scope, tuple[dict[DocumentKey, Scope], int, dict[DocumentKey, Tombstone]]] = field(
        default_factory=dict
    )
    due: frozenset[Scope] = frozenset()
    read_whole: set[Scope] = field(default_factory=set)
    peers: tuple[RawStore, ...] = ()
    snapshot_ids: dict[type[FetchedDocument], set[str]] = field(default_factory=dict)

    def label(self, what: str | type[FetchedDocument]) -> str:
        """Name something of the source in the counts, a document type by its plural.

        As ``confluence pages`` or ``confluence spaces``.
        """
        named = what if isinstance(what, str) else what.document_type.plural
        return f"{self.store.source} {named}"

    def run(self, scopes: Sequence[Scope]) -> None:
        """Fetch every space and project named, after checking that the session holds.

        Raises SignInNeededError, before anything is written, when the session no longer
        holds. A source that does not answer at all (a site without Jira) is counted as a
        failure, by its name, and its scopes skipped. A scope without a window is skipped
        too, and asked nothing. The task ``scopes`` reports those of the sources that
        answer, each by its key. What the scopes' whole reads no longer name is probed
        once every scope is read; Confluence's site users follow its spaces alone, so
        that a fetch of projects alone does and counts nothing of Confluence's.
        """
        self.held |= {scope: "after --until" for scope, w in self.windows.items() if w is None}
        by_type: dict[str, list[Scope]] = {}
        for scope in scopes:
            by_type.setdefault(scope.type.name, []).append(scope)
        answered = [
            scope
            for name, group in by_type.items()
            if self.reachable(group[0].source, *SIGNED_IN[name])
            for scope in group
        ]
        with task("scopes", len(answered)) as each:
            for scope in each.each(answered, lambda scope: scope.key):
                window = self.windows[scope]
                read = self.space if scope.type == SPACE else self.project
                if window is not None and read(scope, window):
                    self.covered[scope] = window.period
            if self.absent and not self.plan:
                self.probe_absent()
        if SPACE.name in by_type and not self.plan:
            self.users()

    def failed(self, what: str, where: str, error: Exception | str) -> Problem:
        """Count a failure by its kind and reason, and keep it as a problem by its place; give it.

        The reason is the one given, the refused field's path or the failed GET's status:
        the messages of these two errors hold paths and statuses only; any other error is
        named by its class, since its message could hold content.
        """
        known = isinstance(error, (str, RepresentationError, SiteError))
        reason = str(error) if known else type(error).__name__
        self.counts.add(f"{what} failed: {reason}")
        problem = Problem(where=where, reason=reason)
        self.problems.append(problem)
        return problem

    def scope_failed(self, what: str, scope: str, error: Exception | str) -> None:
        """Fail a space or a project named, as ``failed`` does; a warning says it.

        The warning, ``fetch.scope_failed``, names the scope and the reason.
        """
        failed = self.failed(what, scope, error)
        structlog.get_logger().warning(
            "fetch.scope_failed", scope=f"{failed.where}: {failed.reason}"
        )

    def reachable(
        self, source: str, request: Callable[[], Request], signed_in: Callable[[Fields], bool]
    ) -> bool:
        """GET the signed-in site user of a source; say whether the source answers.

        Raises SignInNeededError when it answers as to nobody.
        """
        try:
            user = Fields(self.site.json(request()), "user")
        except (RepresentationError, SiteError) as error:
            self.failed(source, source, error)
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

    def documents(
        self, document_class: type[FetchedDocument], entries: Iterable[object]
    ) -> list[Listed]:
        """Read what decides a fetch from a listing's entries, counting those refused."""
        found: list[Listed] = []
        for entry in entries:
            try:
                found.append(
                    LISTED[document_class](Fields(entry, document_class.document_type.plural))
                )
            except RepresentationError as error:
                what = f"{self.label(document_class)} listed"
                self.failed(what, f"{self.label(document_class)} listing", error)
        self.counts.add(f"{self.label(document_class)}: listed", len(found))
        return found

    def space(self, scope: Scope, window: FetchWindow) -> bool:
        """List a space whole, store its listings, and fetch what changed in its window.

        And what joined it since its stored listing, whatever its update time, as a page
        moved in keeps its own, with what joined before and is not stored whole yet; a
        space never listed before has none. Joined is by every listed entry's id, one that
        the adapter refuses among them. The listing is stored once its documents are
        fetched, with the joined that this fetch did not store whole, which the next takes. An
        entry that the adapter refuses has no update time: it leaves the space's coverage
        inexact, so that the next fetch asks for its whole period again. The task
        ``listing`` reports the pages of its listings read, and ``fetch_listed`` the
        documents. Return whether the space was listed whole. All is the span
        ``fetch.space``, an error when the space could not be listed.
        """
        key = scope.key
        with TRACER.start_as_current_span("fetch.space", attributes={"kb_mcp.scope": key}) as span:
            try:
                found = self.collect(confluence_v2.space_request(key), confluence_v2.listing_page)
                space = confluence_v2.space(Fields(found[0], "space")) if found else None
                if space is None:
                    self.scope_failed(self.label("spaces"), f"space {key}", "not found")
                    span.set_status(StatusCode.ERROR, "not found")
                    return False
                page_listing = confluence_v2.listing_request(space.id, Page)
                post_listing = confluence_v2.listing_request(space.id, BlogPost)
                with task("listing") as listing:
                    pages = self.collect(page_listing, confluence_v2.listing_page, listing.advance)
                    posts = self.collect(post_listing, confluence_v2.listing_page, listing.advance)
            except (RepresentationError, SiteError) as error:
                self.scope_failed(self.label("spaces"), f"space {key}", error)
                span.set_status(StatusCode.ERROR, str(error))
                return False
            documents = [*self.documents(Page, pages), *self.documents(BlogPost, posts)]
            # By id alone, as the last listing is read: an entry refused for its other
            # fields still names its document, which is then not absent, or joins.
            listed = {
                Page: confluence_v2.entry_ids(pages),
                BlogPost: confluence_v2.entry_ids(posts),
            }
            entries = listed[Page] | listed[BlogPost]
            held = {each: self.store.listed_ids(space.id, each) for each in CONFLUENCE_CLASSES}
            joined: set[str] = set()
            if self.store.was_listed(space.id):
                named = set().union(*held.values())
                joined = (entries - named | self.store.pending(space.id)) & entries
            if not self.plan:
                self.track(scope, space.id, held, listed)
                folders = self.folders(pages)
            whole = self.fetch_listed(scope, documents, window, joined)
            if len(documents) < len(pages) + len(posts):
                self.first_failed.setdefault(scope, window.period.start)
            if not self.plan:
                # Pending first: a fetch that stops between keeps the former listing.
                self.store.put_pending(space.id, joined - whole)
                self.store.put_space(found[0], pages, posts, folders, listed_at=self.now())
            self.read_whole.add(scope)
            return True

    def track(
        self,
        scope: Scope,
        holder: str,
        held: Mapping[type[FetchedDocument], set[str]],
        listed: Mapping[type[FetchedDocument], set[str]] | None,
    ) -> None:
        """Record, as pending, what the scope held and this fetch's whole read of it does not name.

        ``holder`` is the scope as its listings are kept, a space by its id, a project by
        its key; ``held`` the ids, by document class, that its last whole read names, read
        by id alone, and, for a project, those that its searches found since; ``listed``
        those that this fetch's whole read names, None when the fetch
        made none. The absent are the documents held that the store holds, and those
        already tombstoned in the scope; one that another scope of the source found absent
        keeps that tombstone and its state, so that a confirmed one stays confirmed. A
        document that this fetch's whole read names is present, and loses any tombstone, of
        whichever scope. A whole read of before
        neither starts nor ends an absence: without one, the scope's tombstones stay as
        they are, to be probed again. The record is written before the whole read is
        replaced, so that no absent document is lost to a fetch that stops; they are
        probed once every scope of the fetch is read.
        """
        # A former entry of an unresolved space keeps its id as its key: found now.
        known = {
            key: replace(stone, scope=scope)
            for key, stone in self.tombstones.items()
            if stone.scope in {scope, replace(scope, key=holder)}
        }
        absent: dict[DocumentKey, Scope] = {}
        stored = 0
        for document_class, ids in held.items():
            if document_class not in self.snapshot_ids:
                self.snapshot_ids[document_class] = self.store.stored_ids(document_class)
            before = ids & self.snapshot_ids[document_class]
            stored += len(before)
            named = document_class.document_type.name
            again = {key[2] for key in known if key[1] == named}
            missing = again if listed is None else (before | again) - listed[document_class]
            absent |= {(scope.source, named, each): scope for each in missing}
        # Another scope's tombstone of a document absent from here too goes on as it is.
        known |= {
            key: self.tombstones[key]
            for key in (absent.keys() - known.keys()) & self.tombstones.keys()
        }
        present = {
            (scope.source, each.document_type.name, i)
            for each, ids in (listed or {}).items()
            for i in ids
        }
        self.absent[scope] = (absent, stored, known)
        others = {
            key: stone
            for key, stone in self.tombstones.items()
            if key not in known and key not in present
        }
        self.tombstones = {**others, **after_probes(known, absent, {}, self.now())}
        self.store.put_tombstones(self.tombstones.values())

    def probe_absent(self) -> None:
        """Probe what each scope's whole read no longer names, and record what is gone.

        Those not confirmed are probed, at most ``MAX_PROBES`` a scope and a fetch, those
        on their way first; the rest stay pending. A tombstone of another scope, of a
        document absent from this one too, goes on from its own state; a document that a
        later scope's whole read of this fetch named has none left, and stays present. A
        document answering from another scope is followed there once that scope's last
        whole read names it, and stays pending until then. Raises SignInNeededError when
        too many answer gone and the session no longer holds; when the site does not
        answer, nothing is believed. The task ``probes`` reports a scope's probes, each by
        its document's id; all is the span ``fetch.probes``. The scopes kept, those whose
        whole reads the site's sources keep, this one's and its peers', are read once, and
        each one's whole read once, when a probe first finds a document there.
        """
        stores = (self.store, *self.peers)
        types = {CLASSES[key[1]] for absent, _, _ in self.absent.values() for key in absent}
        kept = {each: {h for store in stores for h in store.holders(each)} for each in types}
        listings: dict[tuple[str, type[FetchedDocument]], set[str]] = {}
        with TRACER.start_as_current_span("fetch.probes"):
            for scope, (tracked, stored, before) in self.absent.items():
                # Not what a later scope's whole read of this fetch named, which is present.
                absent = {k: s for k, s in tracked.items() if k in self.tombstones}
                known = {
                    k: s for k, s in self.tombstones.items() if s.scope == scope or k in absent
                }
                # By the tombstones as they stood before this fetch: those on their way first.
                order = probing_order(absent, before)[:MAX_PROBES]
                with task("probes", len(order)) as probes:
                    answers = {
                        k: a
                        for k in probes.each(order, lambda key: key[2])
                        if (a := self.probe(k, kept, listings))
                    }
                canary = SIGNED_IN[scope.type.name]
                if too_many_gone(answers, stored) and not self.reachable(scope.source, *canary):
                    answers = {}  # the site stopped answering: believe none of these answers
                now = after_probes(known, absent, answers, self.now())
                # Those not acted on: one of another scope probed here goes as answered.
                others = {k: s for k, s in self.tombstones.items() if k not in known}
                self.tombstones = {**others, **now}
                self.store.put_tombstones(self.tombstones.values())
                probed = f"{self.label('documents')}: probed, absent from their listing"
                self.counts.add(probed, len(answers))
                waiting = sum(1 for stone in now.values() if stone.first_gone is None)
                self.counts.add(f"{self.label('documents')}: absent, waiting for a probe", waiting)

    def probe(
        self,
        key: DocumentKey,
        kept: Mapping[type[FetchedDocument], set[str]],
        listings: dict[tuple[str, type[FetchedDocument]], set[str]],
    ) -> ProbeAnswer | None:
        """GET a document absent from its scope's whole read, and say what became of it.

        ``kept`` are the scopes, by document type, whose whole reads the site's sources
        keep, this one's and its peers', so that a scope of another site, whose keys may
        be the same, is never one; ``listings`` the ids that each kept scope's whole reads
        name, by scope and type, which a probe that first finds a document there reads.
        A probe that fails is a problem by its document, as ``fetch_document`` names one.
        """
        document_class = CLASSES[key[1]]
        request, whereabouts = PROBES[document_class]
        where = f"{self.label(document_class)} {key[2]}"
        try:
            found, status = whereabouts(Fields(self.site.json(request(key[2])), "probe"))
        except SiteError as error:
            if error.status == HTTP_NOT_FOUND:
                return ProbeAnswer.GONE
            self.failed(self.label("probes"), where, error)
            return None
        except RepresentationError as error:
            self.failed(self.label("probes"), where, error)
            return None
        holders = kept[document_class]
        if found in holders and (found, document_class) not in listings:
            stores = (self.store, *self.peers)
            listings[found, document_class] = {
                i for each in stores for i in each.listed_ids(found, document_class)
            }
        named = key[2] in listings.get((found, document_class), set())
        return answer_of(found, status, holders, named=named)

    def folders(self, pages: Iterable[object]) -> list[object]:
        """GET every folder above the listed pages, following folders' own parents.

        A page entry that the adapter refuses is counted, and passed over here: it only
        loses its place under a folder in the tree.
        """
        wanted: list[str | None] = []
        for entry in pages:
            try:
                page = confluence_v2.document(Fields(entry, PAGE.plural), Page)
            except RepresentationError as error:
                self.failed(
                    f"{self.label('pages')} in the tree",
                    f"{self.label('pages')} listing",
                    error,
                )
                continue
            if isinstance(page, Page) and page.parent_type == "folder":
                wanted.append(page.parent_id)
        found: dict[str, object] = {}
        while wanted:
            folder_id = wanted.pop()
            if folder_id is None or folder_id in found or not IDENTIFIER.fullmatch(folder_id):
                continue
            if len(found) >= MAX_FOLDERS:
                left = len(wanted) + 1
                self.counts.add(f"{self.label('folders')}: over the cap, left out", left)
                break
            try:
                response = self.site.json(confluence_v2.folder_request(folder_id))
                folder = confluence_v2.folder(Fields(response, "folder"))
            except (RepresentationError, SiteError) as error:
                self.failed(self.label("folders"), f"folder {folder_id}", error)
                found[folder_id] = None
                continue
            found[folder_id] = response
            if folder.parent_type == "folder":
                wanted.append(folder.parent_id)
        return [response for response in found.values() if response is not None]

    def project(self, scope: Scope, window: FetchWindow) -> bool:
        """Search a project's issues updated in its window, and fetch what changed.

        A fetch that writes first tracks what the project no longer holds
        (``track_project``), and keeps the ids that the search finds before fetching
        them, so that the next whole read misses none that it stored. The task
        ``listing`` reports the pages of the search read, and ``fetch_listed`` the
        issues found. Return whether the search was read whole,
        each of its entries read: an entry that the adapter refuses has no update time
        for the coverage to stop at, so it holds the project's. All is the span
        ``fetch.project``, an error when the search could not be read.
        """
        key = scope.key
        start = (window.period.start - JQL_MARGIN).date()
        end = (window.period.end + JQL_MARGIN).date()
        attributes = {"kb_mcp.scope": key}
        with TRACER.start_as_current_span("fetch.project", attributes=attributes) as span:
            if not self.plan:
                self.track_project(scope)
            try:
                with task("listing") as listing:
                    search = jira_v3.search_request(key, start, end)
                    entries = self.collect(search, jira_v3.search_page, listing.advance)
            except (RepresentationError, SiteError) as error:
                self.scope_failed(self.label("projects"), f"project {key}", error)
                span.set_status(StatusCode.ERROR, str(error))
                return False
            if self.plan:
                self.count_files(entries, window.period)
            else:
                found = self.store.searched(key) | jira_v3.entry_ids(entries)
                self.store.put_searched(key, found)
            issues = self.documents(Issue, entries)
            self.fetch_listed(scope, issues, window)
            if len(issues) < len(entries):
                self.held[scope] = "entries refused"
                return False
            return True

    def track_project(self, scope: Scope) -> None:
        """Track what a project no longer holds, by a whole read made when due.

        A project ``due`` is read whole, every issue by id whatever its update time, and
        that read replaces its last; one that fails is counted, ``fetch.scope_failed``,
        and the last stays, the search going on. What the project held, its last whole
        read's issues and those that its searches found since, and this one does not
        name is tracked as absent; a project that this fetch does not read whole
        keeps its tombstones as they are, so that what is absent already is still probed
        at each fetch. The task ``listing`` reports the pages of the whole read.
        """
        key, issues = scope.key, None
        if scope in self.due:
            try:
                with task("listing") as listing:
                    request = jira_v3.listing_request(key)
                    issues = self.collect(request, jira_v3.search_page, listing.advance)
            except (RepresentationError, SiteError) as error:
                self.scope_failed(f"{self.label('projects')} read whole", f"project {key}", error)
        held = {Issue: self.store.listed_ids(key, Issue) | self.store.searched(key)}
        listed = None if issues is None else {Issue: jira_v3.entry_ids(issues)}
        # Tombstones first: a fetch that stops between keeps the former whole read.
        self.track(scope, key, held, listed)
        if issues is not None:
            self.store.put_project(key, issues)
            self.store.put_searched(key, ())
            self.read_whole.add(scope)

    def fetch_listed(
        self,
        scope: Scope,
        documents: Sequence[Listed],
        window: FetchWindow,
        joined: Collection[str] = frozenset(),
    ) -> set[str]:
        """Fetch what a scope lists in its window and the raw store lacks; complete what it has.

        A document that ``joined`` names, by id, is taken as if in the window. Return the
        ids of those taken and stored whole, all in a plan.
        ``fetch.listed`` says at INFO how many documents the scope lists, how many are
        in its window, stored already and to fetch, with the window's start and reason.
        The counts hold, by type, those in the window and those stored when --since gave
        the window; else those new or changed since the last fetch. Those stored get the
        files they lack, without a task; the task ``documents`` reports those to fetch,
        each by its id. ``first_failed`` keeps, for the scope, the update time of the
        earliest not stored whole. A document listed twice, as an issue saved while its
        search pages through can shift another into the next page, is taken once.
        """
        in_window = list(
            dict.fromkeys(
                document
                for document in documents
                if document.updated in window.period or document.id in joined
            )
        )
        stored: list[Listed] = []
        to_fetch: list[Listed] = []
        for document in in_window:
            (stored if self.store.has(document) else to_fetch).append(document)
        structlog.get_logger().info(
            "fetch.listed",
            scope=str(scope),
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
        self.counts.counts.update(
            f"{self.label(document.document_class)}: {what}"
            for what, each in counted.items()
            for document in each
        )
        done = {each: self.plan or self.complete(each) for each in stored}
        with task("documents", len(to_fetch)) as fetching:
            done |= {
                document: self.fetch_document(document)
                for document in fetching.each(to_fetch, lambda listed: listed.id)
            }
        failed = [each.updated for each, whole in done.items() if not whole]
        if failed:
            self.first_failed[scope] = min(failed)
        return {each.id for each, whole in done.items() if whole}

    def count_files(self, entries: Iterable[object], period: Period) -> None:
        """Count the files, and their bytes, that a fetch would download for these issues.

        An issue named twice by its search is counted once, as it would be fetched once.
        """
        counted: set[Listed] = set()
        for entry in entries:
            try:
                listed = jira_v3.listed(Fields(entry, ISSUE.plural))
                files = jira_v3.listed_attachments(Fields(entry, ISSUE.plural))
            except RepresentationError:
                continue  # counted by documents() already
            if listed.updated not in period or self.store.has(listed) or listed in counted:
                continue
            counted.add(listed)
            kept = [each for each in files if skip_reason(each, self.max_file_bytes) is None]
            self.counts.add("files: to download", len(kept))
            self.counts.add("files: bytes to download", sum(each.size for each in kept))

    def fetch_document(self, document: Listed) -> bool:
        """Fetch a listed document whose revision is not stored; say if it is stored whole.

        It is not when its fetch failed, its snapshot was refused, or a file it keeps
        failed; a plan counts it to fetch, and fails none. The fetch is a trace of its
        own, ``fetch.document``, linked to the span of the run's trace current when it
        begins, saying the document's id and type; an error when the fetch fails, which
        is a warning, by the document's id.
        """
        what = self.label(document.document_class)
        if self.plan:
            self.counts.add(f"{what}: to fetch")
            return True
        with TRACER.start_as_current_span(
            "fetch.document",
            context=Context(),  # no parent: the root of a trace of its own
            links=[trace.Link(trace.get_current_span().get_span_context())],
            attributes={"kb_mcp.document.id": document.id, "kb_mcp.document.kind": what},
        ) as span:
            try:
                responses = {
                    name: self.site.json(request) if read is None else self.collect(request, read)
                    for name, (request, read) in SNAPSHOT_REQUESTS[document.document_class](
                        document
                    ).items()
                }
                whole = self.keep(document.document_class, responses)
            except (RepresentationError, SiteError) as error:
                self.failed(what, f"{what} {document.id}", error)
                DOCUMENTS.add(1, {"kb_mcp.outcome": "failed"})
                span.set_status(StatusCode.ERROR, str(error))
                structlog.get_logger().warning(
                    "fetch.document_failed", id=document.id, kind=what, reason=str(error)
                )
                return False
            self.counts.add(f"{what}: fetched")
            DOCUMENTS.add(1, {"kb_mcp.outcome": "fetched"})
            return whole

    def keep(self, document_class: type[FetchedDocument], responses: dict[str, object]) -> bool:
        """Download a snapshot's files, then store it with their digests; say if it is whole.

        A snapshot that its adapter refuses is stored all the same, without files: raw
        first, so that a fixed adapter reads it, and a later fetch downloads its files.
        Read, its document's title goes on the current span, and in ``fetch.document``
        at DEBUG; refused, it is a warning, without the id that it would have given. It is
        whole when read, with every file it keeps.
        """
        try:
            snapshot = REPRESENTATIONS[document_class].snapshot(responses)
            document = snapshot.document
            trace.get_current_span().set_attribute("kb_mcp.document.title", document.title)
            structlog.get_logger().debug(
                "fetch.document",
                id=document.id,
                kind=self.label(document_class),
                title=document.title,
            )
        except RepresentationError as error:
            self.failed(f"{self.label(document_class)} read", self.label(document_class), error)
            structlog.get_logger().warning(
                "fetch.document_unread",
                kind=self.label(document_class),
                reason=str(error),
            )
            snapshot = None
        blobs, whole = self.files(snapshot.attachments) if snapshot else ({}, False)
        self.store.put(document_class, responses, self.now(), blobs)
        if snapshot and snapshot.document.author and document_class is not Issue:
            self.authors.add(snapshot.document.author.account_id)
        return whole

    def complete(self, document: Listed) -> bool:
        """Download the files that a stored snapshot should have and lacks.

        Return whether it is now whole: read, with every file it keeps.
        """
        try:
            stored = self.store.read(document)
        except (RepresentationError, ValueError, OSError) as error:
            what = self.label(document.document_class)
            self.failed(f"{what} read", f"{what} {document.id}", error)
            return False
        missing = [
            attachment
            for attachment in stored.snapshot.attachments
            if attachment.id not in stored.blobs
            and skip_reason(attachment, self.max_file_bytes) is None
        ]
        blobs, whole = self.files(missing)
        self.store.add_blobs(document, blobs)
        if stored.snapshot.document.author and document.document_class is not Issue:
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
                self.counts.add(f"files: skipped, {reason}")
                FILES.add(1, {"kb_mcp.outcome": "skipped"})
                log.info("fetch.file_skipped", **named, reason=reason)
                continue
            try:
                data = self.site.file(attachment.download, self.max_file_bytes)
            except SiteError as error:
                self.failed("files", f"file {attachment.id}", error)
                FILES.add(1, {"kb_mcp.outcome": "failed"})
                log.warning("fetch.file_failed", **named, reason=str(error))
                whole = False
                continue
            if len(data) != attachment.size:  # a proxy's page, say, in the file's place
                self.failed("files", f"file {attachment.id}", "not the size listed")
                FILES.add(1, {"kb_mcp.outcome": "failed"})
                log.warning("fetch.file_failed", **named, reason="not the size listed")
                whole = False
                continue
            blobs[attachment.id] = self.store.put_blob(data)
            self.counts.add("files: downloaded")
            FILES.add(1, {"kb_mcp.outcome": "downloaded"})
            BYTES.add(len(data))
        return blobs, whole

    def users(self) -> None:
        """Merge the names of the Confluence authors seen into the site users kept.

        All is the span ``fetch.users``.
        """
        with TRACER.start_as_current_span("fetch.users"):
            users: list[object] = []
            authors = sorted(self.authors)
            for batch in batched(authors, confluence_v2.USERS_PER_REQUEST, strict=False):
                request = confluence_v2.users_request(batch)
                try:
                    users += self.collect(request, confluence_v2.users_page)
                except (RepresentationError, SiteError) as error:
                    self.failed(self.label("users"), self.label("users"), error)
            try:
                if users:
                    self.store.put_users(users)
            except RepresentationError as error:
                self.failed(self.label("users"), self.label("users"), error)
                return
            self.counts.add(f"{self.label('users')}: named", len(users))


class Purview(Record):
    """What a fetch takes: its purview, scopes of one source, from when, the largest file kept.

    ``since`` starts every scope's window there; without it, each scope catches up on
    what changed since its last fetch, as ``window`` rules. ``until`` ends the windows,
    by default when the fetch starts.
    """

    scopes: Sequence[Scope]
    max_file_bytes: int
    since: datetime | None = None
    until: datetime | None = None

    def windows(self, coverage: Coverage, now: datetime) -> dict[Scope, FetchWindow | None]:
        """Return each scope's window, None for one skipped; PeriodError for --until first.

        Raises PeriodError when --since does not come before the windows' end.
        """
        end = min(self.until, now) if self.until else now  # never past what a fetch can see
        return {scope: fetch_window(coverage, scope, self.since, end) for scope in self.scopes}

    @property
    def source(self) -> str:
        """Name the one source of these scopes, which names its fetch's record and events.

        Raises ValueError for scopes of no source, or of several: a fetch is of one source.
        """
        sources = {scope.source for scope in self.scopes}
        if len(sources) != 1:
            message = f"a fetch is of one source: scopes {[str(each) for each in self.scopes]}"
            raise ValueError(message)
        return sources.pop()


class ScopeFetchWindow(Record):
    """A scope of a fetch: its window, from ``start`` to ``end``, and why it starts there.

    A scope skipped, its catch-up after --until, has none, as ``reason`` says.
    ``coverage`` is what the fetch made of the scope's coverage, None when it wrote none:
    a dry run, or a scope that the fetch did not finish.
    """

    scope: Scope
    start: datetime | None
    end: datetime | None
    reason: Reason | Literal["after --until"]
    coverage: CoverageChange | None


def windows_of(
    windows: Mapping[Scope, FetchWindow | None], coverage: Mapping[Scope, CoverageChange]
) -> tuple[ScopeFetchWindow, ...]:
    """Give each scope's record: its window, and what became of its coverage."""
    return tuple(
        ScopeFetchWindow(
            scope=scope,
            start=None,
            end=None,
            reason="after --until",
            coverage=coverage.get(scope),
        )
        if window is None
        else ScopeFetchWindow(
            scope=scope,
            start=window.period.start,
            end=window.period.end,
            reason=window.reason,
            coverage=coverage.get(scope),
        )
        for scope, window in windows.items()
    )


def plan_fetch(
    settings: Settings,
    purview: Purview,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Outcome[FetchCounts]:
    """List and decide as a fetch would, and say what it would fetch; write nothing.

    It ends not run, a dry run's, unless it failed or the sign-in no longer holds.
    Raises PeriodError when --since does not come before the windows' end.
    """
    store = RawStore(settings.raw, purview.source)
    windows = purview.windows(store.coverage(), now())
    counts = FetchCounts(windows=windows_of(windows, {}), dry_run=True)
    try:
        client = choose_sign_in(settings, purview.source).client()
    except SignInNeededError:
        return Outcome(ending="sign in again", counts=counts)
    with client:
        fetching = Fetching(
            SiteClient(client, sleep=sleep),
            store,
            purview.max_file_bytes,
            now,
            counts,
            windows=windows,
            plan=True,
        )
        try:
            fetching.run(purview.scopes)
        except SignInNeededError:
            return Outcome(ending="sign in again", counts=counts, problems=tuple(fetching.problems))
        except TooManyFailuresError:
            counts.add("runs: stopped, too many failures in a row")
            return Outcome(ending="failed", counts=counts, problems=tuple(fetching.problems))
    return Outcome.of(counts, fetching.problems, otherwise="not run")


def run_fetch(
    settings: Settings,
    purview: Purview,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Outcome[FetchCounts]:
    """Run a fetch of one source signed in as the settings say, and give how it ended.

    The scopes are one source's; another source's are another fetch. Each scope is
    fetched over its window, and one searched by update time
    also read whole when ``whole_read_due`` says so. The coverage of every scope listed
    or searched whole grows as ``Coverage.extended`` rules, and each read whole was read
    whole when the fetch started. Every fetch reads the tombstones and keeps each as it
    finds it, even when it stops; the other sources of its site, by their whole
    reads, say with its own which scopes are kept.
    ``fetch.coverage`` says at INFO what became of each finished scope's coverage,
    and why it was held, if it was. It ends done when nothing failed, failed when
    something did, and sign in again when the sign-in no longer holds or no session was
    saved; Ctrl-C, and any other error that stops it, pass. Raises PeriodError when --since
    does not come before the windows' end, StoreBusyError when another run writes, and
    ValueError for scopes of no source or of several, all before anything is written.
    """
    counts, problems = FetchCounts(), []
    ending: Ending | None = None
    extensions: dict[Scope, CoverageChange] = {}
    store, started = RawStore(settings.raw, purview.source), now()
    coverage = store.coverage()
    windows = purview.windows(coverage, started)
    signing = choose_sign_in(settings, purview.source)
    with store.writing():
        try:
            with signing.client() as client:
                fetching = Fetching(
                    SiteClient(client, sleep=sleep),
                    store,
                    purview.max_file_bytes,
                    now,
                    counts,
                    windows=windows,
                    tombstones=store.tombstones(),
                    due=frozenset(
                        s for s in purview.scopes if whole_read_due(coverage, s, started)
                    ),
                    peers=tuple(
                        RawStore(settings.raw, name)
                        for name, site in sites_of(settings).items()
                        if site == signing.site and name != store.source
                    ),
                )
                problems = fetching.problems
                try:
                    fetching.run(purview.scopes)
                    found: Ending = "failed" if problems else "done"
                except SignInNeededError:
                    found = "sign in again"
                except TooManyFailuresError:
                    found = "failed"
                    counts.add("runs: stopped, too many failures in a row")
                finally:
                    signing.keep(client)
                    log = structlog.get_logger()
                    for scope, fetched in fetching.covered.items():
                        failed = fetching.first_failed.get(scope)
                        coverage, outcome = coverage.extended(scope, fetched, failed)
                        extensions[scope] = outcome
                        reason = (
                            {"reason": "apart from what is covered"} if outcome == "held" else {}
                        )
                        log.info("fetch.coverage", scope=str(scope), outcome=outcome, **reason)
                    for scope, why in fetching.held.items():
                        extensions[scope] = "held"
                        log.info("fetch.coverage", scope=str(scope), outcome="held", reason=why)
                    # Each scope read whole was read whole as the fetch started.
                    store.put_coverage(
                        replace(
                            coverage,
                            whole_read_at=coverage.whole_read_at
                            | dict.fromkeys(fetching.read_whole, started),
                        )
                    )
                ending = found  # once the coverage is stored, else an error stopped it
        except SignInNeededError:  # from the client: no session was saved
            ending = "sign in again"
        finally:
            if ending == "sign in again":
                counts.add("runs: stopped, sign-in needed")
    return Outcome(
        ending=ending,
        counts=replace(counts, windows=windows_of(windows, extensions)),
        problems=tuple(problems),
    )
