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
from atlassian_offline_mcp.adapters.http import SignInNeededError, Site, SiteError
from atlassian_offline_mcp.adapters.raw_store import REPRESENTATIONS, RawStore
from atlassian_offline_mcp.adapters.session_file import COOKIES, read_cookies, write_cookies
from atlassian_offline_mcp.domain.content import IDENTIFIER, BlogPost, Issue, Page
from atlassian_offline_mcp.domain.files import skip_reason

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime
    from http.cookiejar import Cookie

    from atlassian_offline_mcp.adapters.http import Request
    from atlassian_offline_mcp.domain.content import Attachment, Document
    from atlassian_offline_mcp.domain.period import Period
    from atlassian_offline_mcp.domain.settings import Settings

    ReadPage = Callable[[Fields, Request], tuple[list[Fields], Request | None]]

# A listing longer than this many pages is refused rather than followed.
MAX_PAGES = 400
# Folders followed up from the pages of one space, at most.
MAX_FOLDERS = 1000
# Jira reads JQL dates in the user's time zone: the search is widened by this much.
JQL_MARGIN = timedelta(days=1)
# Documents failing one after another, after which the run stops: the site, the
# network or the session is wrong, and each further failure would only cost time.
MAX_FAILED_IN_A_ROW = 10
# Exit statuses, beyond 0 for a run without failure.
SOME_FAILED = 1
SIGN_IN_NEEDED = 3


class RunStoppedError(Exception):
    """Too many documents failed in a row for the run to go on."""


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
    """One run over a site, into a store: a period, and a cap on attached files."""

    site: Site
    store: RawStore
    period: Period
    max_file_bytes: int
    now: Callable[[], datetime]
    report: Report = field(default_factory=Report)
    not_found: list[str] = field(default_factory=list)
    authors: set[str] = field(default_factory=set)
    failed_in_a_row: int = 0

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

    def documents(self, kind: type[Document], entries: Iterable[object]) -> list[Document]:
        """Read the entries of a listing, counting those that the adapter refuses."""
        read = jira_v3.issue if kind is Issue else partial(confluence_v2.document, kind=kind)
        found: list[Document] = []
        for entry in entries:
            try:
                found.append(read(Fields(entry, kind.kind)))
            except RepresentationError as error:
                self.report.failed(f"{label(kind)} listed", error)
        self.report.add(f"{label(kind)}: listed", len(found))
        return found

    def space(self, key: str) -> None:
        """List a space whole, store its listings, and fetch what changed in the period."""
        try:
            found = Fields(self.site.json(confluence_v2.space_request(key)), "spaces")
            results = found.objects("results")
            space = confluence_v2.space(results[0]) if results else None
            if space is None:
                self.not_found.append(key)
                self.report.add("confluence spaces failed: not found")
                return
            page_listing = confluence_v2.listing_request(space.id, Page)
            post_listing = confluence_v2.listing_request(space.id, BlogPost)
            pages = self.collect(page_listing, confluence_v2.listing_page)
            posts = self.collect(post_listing, confluence_v2.listing_page)
        except (RepresentationError, SiteError) as error:
            self.report.failed("confluence spaces", error)
            return
        documents = [*self.documents(Page, pages), *self.documents(BlogPost, posts)]
        folders = self.folders([page for page in documents if isinstance(page, Page)])
        self.store.put_space(results[0].value, pages, posts, folders)
        for document in documents:
            self.consider(document)

    def folders(self, pages: Iterable[Page]) -> list[object]:
        """GET every folder above the pages, following folders' own parents, as received."""
        wanted = [page.parent_id for page in pages if page.parent_type == "folder"]
        found: dict[str, object] = {}
        while wanted and len(found) < MAX_FOLDERS:
            folder_id = wanted.pop()
            if folder_id is None or folder_id in found or not IDENTIFIER.fullmatch(folder_id):
                continue
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
            self.report.failed("jira projects", error)
            return
        for issue in self.documents(Issue, entries):
            self.consider(issue)

    def consider(self, document: Document) -> None:
        """Fetch a listed document when it is in the period and its revision not stored."""
        if document.updated not in self.period:
            return
        what = label(type(document))
        self.report.add(f"{what}: in the period")
        if self.store.has(document):
            self.report.add(f"{what}: already stored")
            self.complete(document)
            return
        try:
            self.keep(type(document), self.responses(document))
        except (RepresentationError, SiteError) as error:
            self.report.failed(what, error)
            self.failed_in_a_row += 1
            if self.failed_in_a_row >= MAX_FAILED_IN_A_ROW:
                raise RunStoppedError from None
            return
        self.failed_in_a_row = 0
        self.report.add(f"{what}: fetched")

    def responses(self, document: Document) -> dict[str, object]:
        """GET the responses that a document's snapshot keeps."""
        if isinstance(document, Issue):
            comments = jira_v3.comments_request(document.id)
            return {
                jira_v3.ISSUE: self.site.json(jira_v3.issue_request(document.id)),
                jira_v3.COMMENTS: self.collect(comments, jira_v3.comments_page),
            }
        if not isinstance(document, Page | BlogPost):
            message = f"not a kind of document that is downloaded: {type(document).__name__}"
            raise TypeError(message)
        storage = confluence_v2.document_request(document, "storage")
        view = confluence_v2.document_request(document, "view")
        attachments = confluence_v2.attachments_request(document)
        return {
            confluence_v2.DOCUMENT: self.site.json(storage),
            confluence_v2.VIEW: self.site.json(view),
            confluence_v2.ATTACHMENTS: self.collect(attachments, confluence_v2.listing_page),
        }

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

    def complete(self, document: Document) -> None:
        """Download the files that a stored snapshot should have and lacks."""
        try:
            stored = self.store.read(document)
        except (RepresentationError, ValueError, OSError) as error:
            self.report.failed(f"{label(type(document))} read", error)
            return
        missing = [
            attachment
            for attachment in stored.snapshot.attachments
            if attachment.id not in stored.blobs
            and skip_reason(attachment, self.max_file_bytes) is None
        ]
        self.store.add_blobs(document, self.files(missing))
        if stored.snapshot.document.author and not isinstance(document, Issue):
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
        if users:
            self.store.put_users(users)
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
    """What a run did, the space keys that found nothing, and the run's exit status."""

    report: Report
    not_found: list[str]
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
    StoreBusyError when another run writes.
    """
    report, not_found, status = Report(), [], None
    try:
        cookies = read_cookies(settings.session / COOKIES)
    except OSError, ValueError:
        cookies, status = None, SIGN_IN_NEEDED
    store = RawStore(settings.raw)
    try:
        if cookies is not None:
            with http.client(str(settings.site), cookies) as client, store.writing():
                site = Site(client, sleep=sleep)
                run = Download(site, store, targets.period, targets.max_file_bytes, now, report)
                not_found = run.not_found
                try:
                    run.run(targets.spaces, targets.projects)
                    status = SOME_FAILED if report.failures else 0
                except SignInNeededError:
                    status = SIGN_IN_NEEDED
                except RunStoppedError:
                    status = SOME_FAILED
                    report.add("runs: stopped, too many failures in a row")
                finally:
                    host = urlsplit(str(settings.site)).hostname or ""
                    write_cookies(
                        settings.session / COOKIES, site_cookies(client.cookies.jar, host)
                    )
    finally:
        if status is None:
            report.add("runs: interrupted")
        elif status == SIGN_IN_NEEDED:
            report.add("runs: stopped, sign-in needed")
        settings.runs.mkdir(parents=True, exist_ok=True)
        started = now().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        saved = {"status": status, "counts": dict(sorted(report.counts.items()))}
        (settings.runs / f"{started}.json").write_text(json.dumps(saved, indent=1), "utf-8")
    return Outcome(report, not_found, status)


def site_cookies(jar: Iterable[Cookie], host: str) -> list[dict[str, str | None]]:
    """Keep the cookies that the site's host is within: never a media host's."""
    return [
        {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path}
        for cookie in jar
        if host == cookie.domain.lstrip(".") or host.endswith("." + cookie.domain.lstrip("."))
    ]
