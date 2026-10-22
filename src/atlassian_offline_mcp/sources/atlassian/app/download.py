"""Downloading the documents of spaces and projects updated in a period."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from functools import partial
from itertools import batched
from typing import TYPE_CHECKING, Literal

from atlassian_offline_mcp.kernel.content import IDENTIFIER, BlogPost, Issue, Page
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.kernel.fields import Fields, RepresentationError
from atlassian_offline_mcp.observability.adapters.progress import task
from atlassian_offline_mcp.sources.atlassian.adapters import confluence_v2, jira_v3
from atlassian_offline_mcp.sources.atlassian.adapters.http import (
    SignInNeededError,
    Site,
    SiteError,
    TooManyFailuresError,
)
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import (
    REPRESENTATIONS,
    RawStore,
    Unreadable,
)
from atlassian_offline_mcp.sources.atlassian.adapters.sign_in import sign_in
from atlassian_offline_mcp.sources.atlassian.domain.coverage import Coverage, Target, window
from atlassian_offline_mcp.sources.atlassian.domain.deletions import (
    Answer,
    Tombstone,
    after_probes,
    answer_of,
    probing_order,
    too_many_gone,
)
from atlassian_offline_mcp.sources.atlassian.domain.files import skip_reason
from atlassian_offline_mcp.sources.atlassian.domain.period import EPOCH, Period

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from datetime import datetime

    from atlassian_offline_mcp.config.domain.settings import Settings
    from atlassian_offline_mcp.kernel.content import Attachment, Document, Listed
    from atlassian_offline_mcp.sources.atlassian.adapters.http import ReadPage, Request

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


@dataclass
class Report:
    """What a run did, by count; it names nothing that the site served."""

    counts: Counter[str] = field(default_factory=Counter)

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
    """One run over a site, into a store: the periods, and a cap on attached files.

    Each target is fetched over its own window, or over ``period`` when it has none.
    With ``plan``, the run lists and decides, and fetches and writes nothing. ``covered``
    names the targets whose listing was read whole, so that their coverage can grow.
    ``failed_targets`` names the user's own keys that failed, for the command to show;
    they never enter the report.
    """

    site: Site
    store: RawStore
    period: Period
    max_file_bytes: int
    now: Callable[[], datetime]
    report: Report = field(default_factory=Report)
    failed_targets: list[str] = field(default_factory=list)
    authors: set[str] = field(default_factory=set)
    windows: Mapping[Target, Period] = field(default_factory=dict)
    plan: bool = False
    covered: list[Target] = field(default_factory=list)
    tombstones: dict[tuple[str, str], Tombstone] = field(default_factory=dict)
    absent: dict[str, tuple[dict[tuple[str, str], str], int, dict[tuple[str, str], Tombstone]]] = (
        field(default_factory=dict)
    )

    def run(self, spaces: Sequence[str], projects: Sequence[str]) -> None:
        """Download every space and project named, after checking that the session holds.

        Raises SignInNeededError, before anything is written, when the session no longer
        holds. A source that does not answer at all (a site without Jira) is counted as a
        failure, and its targets skipped. The task ``targets`` reports those of the
        sources that answer, each by its key.
        """
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
                target = Target("confluence", key)
                if self.space(key, self.windows.get(target, self.period)):
                    self.covered.append(target)
            if not self.plan:
                self.probe_absent()
            for key in targets.each(answered_projects, str):
                target = Target("jira", key)
                if self.project(key, self.windows.get(target, self.period)):
                    self.covered.append(target)
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

    def space(self, key: str, period: Period) -> bool:
        """List a space whole, store its listings, and fetch what changed in the period.

        The task ``listing`` reports the pages of its listings read, and the task
        ``documents`` the documents it lists, each by its id. Return whether the space
        was listed whole.
        """
        try:
            found = self.collect(confluence_v2.space_request(key), confluence_v2.listing_page)
            space = confluence_v2.space(Fields(found[0], "space")) if found else None
            if space is None:
                self.failed_targets.append(f"space {key}: not found")
                self.report.add("confluence spaces failed: not found")
                return False
            page_listing = confluence_v2.listing_request(space.id, Page)
            post_listing = confluence_v2.listing_request(space.id, BlogPost)
            with task("listing") as listing:
                pages = self.collect(page_listing, confluence_v2.listing_page, listing.advance)
                posts = self.collect(post_listing, confluence_v2.listing_page, listing.advance)
        except (RepresentationError, SiteError) as error:
            self.failed_targets.append(f"space {key}: {error}")
            self.report.failed("confluence spaces", error)
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
        with task("documents", len(documents)) as considered:
            for document in considered.each(documents, lambda listed: listed.id):
                self.consider(document, period)
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
        task ``probes`` reports a space's probes, each by its document's id.
        """
        canary = (confluence_v2.current_user_request(), confluence_v2.signed_in)
        kept = {each.id for each in self.store.spaces() if not isinstance(each, Unreadable)}
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
            self.report.add("confluence documents: probed, absent from their listing", len(answers))
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

    def project(self, key: str, period: Period) -> bool:
        """Search a project's issues updated in the period, and fetch what changed.

        The task ``listing`` reports the pages of the search read, and the task
        ``documents`` the issues found, each by its id. Return whether the search was
        read whole.
        """
        start = (period.start - JQL_MARGIN).date()
        end = (period.end + JQL_MARGIN).date()
        try:
            with task("listing") as listing:
                search = jira_v3.search_request(key, start, end)
                entries = self.collect(search, jira_v3.search_page, listing.advance)
        except (RepresentationError, SiteError) as error:
            self.failed_targets.append(f"project {key}: {error}")
            self.report.failed("jira projects", error)
            return False
        if self.plan:
            self.count_files(entries, period)
        issues = self.documents(Issue, entries)
        with task("documents", len(issues)) as considered:
            for issue in considered.each(issues, lambda listed: listed.id):
                self.consider(issue, period)
        return True

    def count_files(self, entries: Iterable[object], period: Period) -> None:
        """Count the files, and their bytes, that a run would download for these issues."""
        for entry in entries:
            try:
                listed = jira_v3.listed(Fields(entry, "issues"))
                files = jira_v3.listed_attachments(Fields(entry, "issues"))
            except RepresentationError:
                continue  # counted by documents() already
            if listed.updated not in period or self.store.has(listed):
                continue
            kept = [each for each in files if skip_reason(each, self.max_file_bytes) is None]
            self.report.add("files: to download", len(kept))
            self.report.add("files: bytes to download", sum(each.size for each in kept))

    def consider(self, document: Listed, period: Period) -> None:
        """Fetch a listed document when it is in the period and its revision not stored."""
        if document.updated not in period:
            return
        what = label(document.type)
        self.report.add(f"{what}: in the period")
        if self.store.has(document):
            self.report.add(f"{what}: already stored")
            if not self.plan:
                self.complete(document)
            return
        if self.plan:
            self.report.add(f"{what}: to fetch")
            return
        try:
            responses = {
                name: self.site.json(request) if read is None else self.collect(request, read)
                for name, (request, read) in SNAPSHOT_REQUESTS[document.type](document).items()
            }
            self.keep(document.type, responses)
        except (RepresentationError, SiteError) as error:
            self.report.failed(what, error)
            return
        self.report.add(f"{what}: fetched")

    def keep(self, kind: type[Document], responses: dict[str, object]) -> None:
        """Download a snapshot's files, then store it with their digests.

        A snapshot that its adapter refuses is stored all the same, without files: raw
        first, so that a fixed adapter reads it, and a later run downloads its files.
        """
        try:
            snapshot = REPRESENTATIONS[kind].snapshot(responses)
        except RepresentationError as error:
            self.report.failed(f"{label(kind)} read", error)
            snapshot = None
        blobs = self.files(snapshot.attachments) if snapshot else {}
        self.store.put(kind, responses, self.now(), blobs)
        if snapshot and snapshot.document.author and kind is not Issue:
            self.authors.add(snapshot.document.author.account_id)

    def complete(self, document: Listed) -> None:
        """Download the files that a stored snapshot should have and lacks."""
        try:
            stored = self.store.read(document)
        except (RepresentationError, ValueError, OSError) as error:
            self.report.failed(f"{label(document.type)} read", error)
            return
        missing = [
            attachment
            for attachment in stored.snapshot.attachments
            if attachment.id not in stored.blobs
            and skip_reason(attachment, self.max_file_bytes) is None
        ]
        self.store.add_blobs(document, self.files(missing))
        if stored.snapshot.document.author and document.type is not Issue:
            self.authors.add(stored.snapshot.document.author.account_id)

    def files(self, attachments: Iterable[Attachment]) -> dict[str, str]:
        """Download the attachments' files that are kept, and return their digests by id."""
        blobs: dict[str, str] = {}
        for attachment in attachments:
            reason = skip_reason(attachment, self.max_file_bytes)
            if reason is not None:
                self.report.add(f"files: skipped, {reason}")
                continue
            try:
                data = self.site.file(attachment.download, self.max_file_bytes)
            except SiteError as error:
                self.report.failed("files", error)
                continue
            if len(data) != attachment.size:  # a proxy's page, say, in the file's place
                self.report.add("files failed: not the size listed")
                continue
            blobs[attachment.id] = self.store.put_blob(data)
            self.report.add("files: downloaded")
        return blobs

    def users(self) -> None:
        """Merge the names of the Confluence authors seen into the users kept."""
        users: list[object] = []
        for chunk in batched(sorted(self.authors), confluence_v2.USERS_PER_REQUEST, strict=False):
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


@dataclass(frozen=True)
class Targets:
    """What a run downloads: spaces and projects, how far back, and the largest file kept.

    ``since`` starts every target's window there; without it, each target catches up
    from the start of its coverage. ``back`` reaches further back (or ``all`` the way);
    ``until`` ends the windows, by default when the run starts.
    """

    spaces: Sequence[str]
    projects: Sequence[str]
    max_file_bytes: int
    since: datetime | None = None
    back: timedelta | Literal["all"] | None = None
    until: datetime | None = None

    def windows(self, coverage: Coverage, now: datetime) -> dict[Target, Period]:
        """Return each target's window; raise PeriodError for one with nowhere to start."""
        named = [Target("confluence", key) for key in self.spaces]
        named += [Target("jira", key) for key in self.projects]
        end = min(self.until, now) if self.until else now  # never past what a run can see
        return {target: window(coverage, target, self.since, self.back, end) for target in named}


@dataclass(frozen=True)
class Outcome:
    """What a run did, the user's keys that failed, and the run's exit status."""

    report: Report
    failed_targets: list[str]
    status: ExitStatus | None


def plan(
    settings: Settings,
    targets: Targets,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Outcome:
    """List and decide as a run would, and say what it would fetch; write nothing.

    Raises PeriodError for a target with nowhere to start.
    """
    store, report = RawStore(settings.raw), Report()
    windows = targets.windows(store.coverage(), now())
    try:
        client = sign_in(settings).client()
    except SignInNeededError:
        return Outcome(report, [], ExitStatus.SIGN_IN_AGAIN)
    with client:
        run = Download(
            Site(client, sleep=sleep),
            store,
            Period(EPOCH, now()),
            targets.max_file_bytes,
            now,
            report,
            windows=windows,
            plan=True,
        )
        try:
            run.run(targets.spaces, targets.projects)
        except SignInNeededError:
            return Outcome(report, run.failed_targets, ExitStatus.SIGN_IN_AGAIN)
        except TooManyFailuresError:
            report.add("runs: stopped, too many failures in a row")
            return Outcome(report, run.failed_targets, ExitStatus.FAILED)
    return Outcome(
        report, run.failed_targets, ExitStatus.FAILED if report.failures else ExitStatus.OK
    )


def download(
    settings: Settings,
    targets: Targets,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Outcome:
    """Run a download signed in as the settings say, and save its report, even when stopped.

    Each target is fetched over its window; the coverage of every target listed whole
    grows, and the tombstones found are kept, even when the run stops. The status is
    ``OK`` when nothing failed, ``FAILED`` when something did, and ``SIGN_IN_AGAIN``
    when the sign-in no longer holds or no session was saved. Raises PeriodError for a
    target with nowhere to start, and StoreBusyError when another run writes, both
    before anything is written.
    """
    report, failed_targets, status = Report(), [], None
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
                    Period(EPOCH, started),
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
                    for target in run.covered:
                        coverage = coverage.extended(target, windows[target])
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
    return Outcome(report, failed_targets, status)
