"""Downloading the documents of spaces and projects updated in a period."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from functools import partial
from itertools import batched
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from atlassian_offline_mcp.adapters import confluence_v2, http, jira_v3
from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.adapters.http import (
    SignInNeededError,
    Site,
    SiteError,
    TooManyFailuresError,
)
from atlassian_offline_mcp.adapters.raw_store import REPRESENTATIONS, RawStore
from atlassian_offline_mcp.adapters.session_file import (
    COOKIES,
    for_site,
    read_cookies,
    write_cookies,
)
from atlassian_offline_mcp.domain.content import IDENTIFIER, BlogPost, Issue, Page
from atlassian_offline_mcp.domain.files import skip_reason

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime

    from atlassian_offline_mcp.adapters.http import ReadPage, Request
    from atlassian_offline_mcp.domain.content import Attachment, Document, Listed
    from atlassian_offline_mcp.domain.period import Period
    from atlassian_offline_mcp.domain.settings import Settings

    type SnapshotRequests = Callable[[Listed], dict[str, tuple[Request, ReadPage | None]]]

# A listing longer than this many pages is refused rather than followed.
MAX_PAGES = 400
# Folders followed up from the pages of one space, at most.
MAX_FOLDERS = 1000
# Jira reads JQL dates in the user's time zone, up to 14 hours off UTC, and a date
# stands for its midnight: two days on each side always cover the period.
JQL_MARGIN = timedelta(days=2)
# Exit statuses, beyond 0 for a run without failure.
SOME_FAILED = 1
SIGN_IN_NEEDED = 3

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
    """One run over a site, into a store: a period, and a cap on attached files.

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

    def run(self, spaces: Sequence[str], projects: Sequence[str]) -> None:
        """Download every space and project named, after checking that the session holds.

        Raises SignInNeededError, before anything is written, when the session no longer
        holds. A source that does not answer at all (a site without Jira) is counted as a
        failure, and its targets skipped.
        """
        confluence = bool(spaces) and self.reachable(
            "confluence", confluence_v2.current_user_request(), confluence_v2.signed_in
        )
        jira = bool(projects) and self.reachable(
            "jira", jira_v3.myself_request(), jira_v3.signed_in
        )
        for key in spaces if confluence else ():
            self.space(key)
        for key in projects if jira else ():
            self.project(key)
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

    def collect(self, request: Request, read_page: ReadPage) -> list[object]:
        """Follow a paged listing to its end, and return every result as received."""
        results: list[object] = []
        for _ in range(MAX_PAGES):
            page, following = read_page(Fields(self.site.json(request), "response"), request)
            results += [item.value for item in page]
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

    def space(self, key: str) -> None:
        """List a space whole, store its listings, and fetch what changed in the period."""
        try:
            found = self.collect(confluence_v2.space_request(key), confluence_v2.listing_page)
            space = confluence_v2.space(Fields(found[0], "space")) if found else None
            if space is None:
                self.failed_targets.append(f"space {key}: not found")
                self.report.add("confluence spaces failed: not found")
                return
            page_listing = confluence_v2.listing_request(space.id, Page)
            post_listing = confluence_v2.listing_request(space.id, BlogPost)
            pages = self.collect(page_listing, confluence_v2.listing_page)
            posts = self.collect(post_listing, confluence_v2.listing_page)
        except (RepresentationError, SiteError) as error:
            self.failed_targets.append(f"space {key}: {error}")
            self.report.failed("confluence spaces", error)
            return
        documents = [*self.documents(Page, pages), *self.documents(BlogPost, posts)]
        self.store.put_space(found[0], pages, posts, self.folders(pages))
        for document in documents:
            self.consider(document)

    def folders(self, pages: Iterable[object]) -> list[object]:
        """GET every folder above the listed pages, following folders' own parents.

        A page entry that the adapter refuses is passed over here: it only loses its
        place under a folder in the tree.
        """
        wanted: list[str | None] = []
        for entry in pages:
            try:
                page = confluence_v2.document(Fields(entry, "pages"), Page)
            except RepresentationError:
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

    def project(self, key: str) -> None:
        """Search a project's issues updated in the period, and fetch what changed."""
        start = (self.period.start - JQL_MARGIN).date()
        end = (self.period.end + JQL_MARGIN).date()
        try:
            entries = self.collect(jira_v3.search_request(key, start, end), jira_v3.search_page)
        except (RepresentationError, SiteError) as error:
            self.failed_targets.append(f"project {key}: {error}")
            self.report.failed("jira projects", error)
            return
        for issue in self.documents(Issue, entries):
            self.consider(issue)

    def consider(self, document: Listed) -> None:
        """Fetch a listed document when it is in the period and its revision not stored."""
        if document.updated not in self.period:
            return
        what = label(document.type)
        self.report.add(f"{what}: in the period")
        if self.store.has(document):
            self.report.add(f"{what}: already stored")
            self.complete(document)
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
    """What a run downloads: spaces and projects, the period, and the largest file kept."""

    spaces: Sequence[str]
    projects: Sequence[str]
    period: Period
    max_file_bytes: int


@dataclass(frozen=True)
class Outcome:
    """What a run did, the user's keys that failed, and the run's exit status."""

    report: Report
    failed_targets: list[str]
    status: int


def download(
    settings: Settings,
    targets: Targets,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Outcome:
    """Run a download with the saved session, and save its report, even when stopped.

    The status is 0 when nothing failed, ``SOME_FAILED`` when something did, and
    ``SIGN_IN_NEEDED`` when the session no longer holds or none was saved. Raises
    StoreBusyError, before anything is written, when another run writes.
    """
    report, failed_targets, status = Report(), [], None
    try:
        cookies = read_cookies(settings.session / COOKIES)
    except OSError, ValueError:
        cookies, status = None, SIGN_IN_NEEDED
    store = RawStore(settings.raw)
    site = str(settings.site)
    with store.writing():
        try:
            if cookies is not None:
                with http.client(site, cookies) as client:
                    reader = Site(client, sleep=sleep)
                    span, cap = targets.period, targets.max_file_bytes
                    run = Download(reader, store, span, cap, now, report)
                    failed_targets = run.failed_targets
                    try:
                        run.run(targets.spaces, targets.projects)
                        status = SOME_FAILED if report.failures else 0
                    except SignInNeededError:
                        status = SIGN_IN_NEEDED
                    except TooManyFailuresError:
                        status = SOME_FAILED
                        report.add("runs: stopped, too many failures in a row")
                    finally:
                        host = urlsplit(site).hostname or ""
                        write_cookies(settings.session / COOKIES, for_site(http.jar(client), host))
        finally:
            if status is None:
                report.add("runs: interrupted")
            elif status == SIGN_IN_NEEDED:
                report.add("runs: stopped, sign-in needed")
            settings.runs.mkdir(parents=True, exist_ok=True)
            started = now().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            saved = {"status": status, "counts": dict(sorted(report.counts.items()))}
            (settings.runs / f"{started}.json").write_text(json.dumps(saved, indent=1), "utf-8")
    return Outcome(report, failed_targets, status)
