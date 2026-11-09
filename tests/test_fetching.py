"""A download end to end, over a scripted site that answers as the REST documentation says."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

import httpx
import pytest
from structlog.testing import capture_logs

from kb_mcp.kernel.outcome import Problem
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.http import (
    MAX_FAILED_IN_A_ROW,
    SiteClient,
    TooManyFailuresError,
)
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import (
    RawStore,
    StoreBusyError,
    StoredSnapshot,
)
from kb_mcp.sources.atlassian.fetch.adapters.session_file import (
    COOKIES,
    for_site,
    read_cookies,
    write_cookies,
)
from kb_mcp.sources.atlassian.fetch.app import fetching as fetching_module
from kb_mcp.sources.atlassian.fetch.app.fetching import Fetching, Targets, run_fetch
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.atlassian.fetch.domain.coverage import FetchWindow, Target
from kb_mcp.sources.atlassian.fetch.domain.period import Period, period
from tests.composed import MODEL
from tests.samples import (
    v1_user,
    v2_attachment,
    v2_folder,
    v2_page,
    v2_space,
    v3_comment,
    v3_issue,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings
    from tests.conftest import InMemory

SITE = "https://sandbox.example.invalid"
MEDIA = "https://api.media.atlassian.com/file/abc/binary?token=t"
NOW = datetime(2026, 10, 22, 9, tzinfo=UTC)
CAP = 1000
PICTURE = b"\x89PNG picture"
SPACE = "196613"
OWNER_ONLY = 0o600
HTTP_OK = 200
# The exit statuses of a run, as the shell reads them.
SOME_FAILED = 1
SIGN_IN_NEEDED = 3


def stamp(day: int, number: int = 3) -> dict[str, object]:
    """Return a v2 version, created on a day of October 2026."""
    return {"number": number, "createdAt": f"2026-10-{day:02d}T10:00:00.000Z"}


# Two pages and a blog post changed in the last week; one page did not.
PAGES = {
    "1001": v2_page(id="1001", title="Fresh page", version=stamp(20)),
    "1002": v2_page(
        id="1002", title="Page in a folder", version=stamp(21), parentId="2001", parentType="folder"
    ),
    "1003": v2_page(id="1003", title="Old page", version=stamp(1)),
}
POSTS = {"1101": v2_page(id="1101", title="Weekly news", version=stamp(19), parentId=None)}
FOLDERS = {
    "2001": v2_folder(id="2001", title="Inner", parentId="2002", parentType="folder"),
    "2002": v2_folder(id="2002", title="Outer", parentId="1001", parentType="page"),
}
ATTACHMENTS = {
    "1001": [
        v2_attachment(
            id="att1",
            fileSize=len(PICTURE),
            downloadLink="/rest/api/content/1001/child/attachment/att1/download",
        ),
        v2_attachment(id="att2", title="talk.mp4", mediaType="video/mp4"),
        v2_attachment(id="att3", title="huge.png", fileSize=CAP + 1),
    ],
    "1002": [],
    "1101": [],
}
ISSUE = v3_issue()
ISSUE["fields"]["attachment"][0]["size"] = len(PICTURE)  # type: ignore[index]
ISSUES = {
    "10000": ISSUE,
    "10001": v3_issue(
        id="10001",
        key="PRB-2",
        fields={**v3_issue()["fields"], "updated": "2026-09-01T10:00:00.000+0000"},  # type: ignore[dict-item]
    ),
}
COMMENTS = [v3_comment(id="10100"), v3_comment(id="10101")]
SERVED = ["Fresh page", "Page in a folder", "Old page", "Weekly news", "PRB-1", "MFS", "1001"]


@dataclass
class FakeSite:
    """Answer the GETs of a download as the sandbox would, and record them.

    The switches change the site: one page in a changed shape, an expired session, the
    spaces found by key, no Jira, every page failing, many pages in the period; the
    space's blog posts; the issues that the search finds, those whose GET answers a
    status, and those served without their summary, which the adapter refuses.
    """

    changed_labels: bool = False
    anonymous: bool = False
    spaces: list[dict[str, object]] = field(default_factory=lambda: [v2_space()])
    jira: bool = True
    pages_fail: bool = False
    many_pages: int = 0
    set_cookies: list[str] = field(default_factory=list)
    html_page: str | None = None
    listing_changed: bool = False
    media_fails: bool = False
    failing_files: int = 0
    search_status: int = 200
    search_changed: bool = False
    bulk_changed: bool = False
    posts: dict[str, dict[str, object]] = field(default_factory=lambda: dict(POSTS))
    issues: dict[str, dict[str, object]] = field(default_factory=lambda: dict(ISSUES))
    failing_issues: dict[str, int] = field(default_factory=dict)
    unread_issues: set[str] = field(default_factory=set)
    asked: list[httpx.URL] = field(default_factory=list)

    def routes(self) -> dict[str, Callable[[httpx.Request], httpx.Response]]:
        """Map each path to its answer."""
        routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {
            "/wiki/rest/api/user/current": lambda _: httpx.Response(
                200,
                json={"type": "anonymous"} if self.anonymous else {"accountId": "account-1"},
                headers=[("set-cookie", cookie) for cookie in self.set_cookies],
            ),
            "/rest/api/3/myself": lambda _: httpx.Response(
                200 if self.jira else 404, json={"accountId": "account-1"}
            ),
            "/wiki/api/v2/spaces": lambda _: httpx.Response(200, json={"results": self.spaces}),
            f"/wiki/api/v2/spaces/{SPACE}/pages": self.pages,
            f"/wiki/api/v2/spaces/{SPACE}/blogposts": lambda _: httpx.Response(
                200, json={"results": list(self.posts.values()), "_links": {}}
            ),
            "/wiki/rest/api/user/bulk": lambda _: httpx.Response(
                200, json={"results": [v1_user()]}
            ),
            "/wiki/rest/api/content/1001/child/attachment/att1/download": lambda _: httpx.Response(
                302, headers={"location": MEDIA}
            ),
            "/file/abc/binary": lambda _: httpx.Response(200, content=PICTURE),
            "/rest/api/3/search/jql": lambda _: httpx.Response(
                200, json={"issues": list(self.issues.values()), "isLast": True}
            ),
            "/rest/api/3/attachment/content/10000": lambda _: httpx.Response(
                303, headers={"location": MEDIA}
            ),
        }
        for issue_id in self.issues:
            routes[f"/rest/api/3/issue/{issue_id}"] = lambda _, i=issue_id: self.issue(i)
            routes[f"/rest/api/3/issue/{issue_id}/comment"] = self.comments
        for folder_id, folder in FOLDERS.items():
            routes[f"/wiki/api/v2/folders/{folder_id}"] = lambda _, f=folder: httpx.Response(
                200, json=f
            )
        for resource_type, documents in (("pages", PAGES | self.many()), ("blogposts", self.posts)):
            for document_id, document in documents.items():
                address = f"/wiki/api/v2/{resource_type}/{document_id}"
                routes[address] = lambda request, d=document: self.document(request, d)
                files = ATTACHMENTS.get(document_id, [])
                if document_id == "1001" and self.failing_files:
                    files = files + [
                        v2_attachment(
                            id=f"gone{index}",
                            fileSize=1,
                            downloadLink=f"/rest/api/content/1001/child/attachment/gone{index}",
                        )
                        for index in range(self.failing_files)
                    ]
                listed = {"results": files, "_links": {}}
                routes[f"{address}/attachments"] = lambda _, j=listed: httpx.Response(200, json=j)
        return {**routes, **self.changes()}

    def changes(self) -> dict[str, Callable[[httpx.Request], httpx.Response]]:
        """Map the paths that the switches change to their changed answers."""
        changes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        if self.html_page:
            changes[f"/wiki/api/v2/pages/{self.html_page}"] = lambda _: httpx.Response(
                200, content=b"<html>Maintenance</html>"
            )
        if self.media_fails:
            changes["/file/abc/binary"] = lambda _: httpx.Response(500)
        for index in range(self.failing_files):
            path = f"/wiki/rest/api/content/1001/child/attachment/gone{index}"
            changes[path] = lambda _: httpx.Response(404)
        if self.search_status != HTTP_OK or self.search_changed:
            changes["/rest/api/3/search/jql"] = self.search
        if self.bulk_changed:
            changes["/wiki/rest/api/user/bulk"] = lambda _: httpx.Response(
                200, json={"results": [{"displayName": "No id"}]}
            )
        return changes

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one GET, or 404 for a path the site does not have."""
        self.asked.append(request.url)
        if self.pages_fail and request.url.path.startswith("/wiki/api/v2/pages/"):
            return httpx.Response(503)
        route = self.routes().get(request.url.path)
        return route(request) if route else httpx.Response(404)

    def search(self, _: httpx.Request) -> httpx.Response:
        """Answer a search with a status, or with entries that lack their summary."""
        if self.search_status != HTTP_OK:
            return httpx.Response(self.search_status, json={"errorMessages": ["no project"]})
        entries = []
        for issue in self.issues.values():
            values = issue["fields"]
            assert isinstance(values, dict)
            entries.append({**issue, "fields": {k: v for k, v in values.items() if k != "summary"}})
        return httpx.Response(200, json={"issues": entries, "isLast": True})

    def issue(self, issue_id: str) -> httpx.Response:
        """Serve an issue, with its status if it fails, or without its summary."""
        if issue_id in self.failing_issues:
            return httpx.Response(self.failing_issues[issue_id])
        issue = self.issues[issue_id]
        if issue_id in self.unread_issues:
            values = issue["fields"]
            assert isinstance(values, dict)
            issue = {**issue, "fields": {k: v for k, v in values.items() if k != "summary"}}
        return httpx.Response(200, json=issue)

    def many(self) -> dict[str, dict[str, object]]:
        """Give the many pages in the period, by id, as the switch has them: none by default."""
        ids = [str(5000 + i) for i in range(self.many_pages)]
        return {page_id: v2_page(id=page_id, version=stamp(20)) for page_id in ids}

    def pages(self, request: httpx.Request) -> httpx.Response:
        """Serve the pages listing in two pages, linked by _links.next; or the many in one."""
        if self.many_pages:
            many = list(self.many().values())
            return httpx.Response(200, json={"results": many, "_links": {}})
        if "cursor" in request.url.params:
            return httpx.Response(200, json={"results": [PAGES["1003"]], "_links": {}})
        following = f"/wiki/api/v2/spaces/{SPACE}/pages?limit=250&cursor=c2"
        first = [PAGES["1001"], PAGES["1002"]]
        if self.listing_changed:
            first = [
                {key: value for key, value in page.items() if key != "title"} for page in first
            ]
        return httpx.Response(200, json={"results": first, "_links": {"next": following}})

    def document(self, request: httpx.Request, document: dict[str, object]) -> httpx.Response:
        """Serve a page or a post with the body asked for, at the version asked for."""
        version = document["version"]
        assert isinstance(version, dict)
        assert request.url.params["version"] == str(version["number"])
        body = request.url.params["body-format"]
        served = {**document, "body": {body: {"value": f"<p>{body}</p>", "representation": body}}}
        if self.changed_labels and document["id"] == "1002":
            served["labels"] = {"results": [{"label": "renamed field"}]}
        return httpx.Response(200, json=served)

    def comments(self, request: httpx.Request) -> httpx.Response:
        """Serve two comments, one per page."""
        start = int(request.url.params["startAt"])
        return httpx.Response(
            200,
            json={"comments": [COMMENTS[start]], "startAt": start, "total": len(COMMENTS)},
        )

    def client(self) -> httpx.Client:
        """Return an httpx client whose GETs this site answers."""
        return httpx.Client(base_url=SITE, transport=httpx.MockTransport(self.handle))


def given(span: Period, spaces: list[str], projects: list[str]) -> dict[Target, FetchWindow | None]:
    """Give each space and project the window that --since gives: ``span``."""
    named = [Target(source="confluence", key=key) for key in spaces] + [
        Target(source="jira", key=k) for k in projects
    ]
    return {target: FetchWindow(period=span, reason="given") for target in named}


def week(spaces: list[str], projects: list[str]) -> dict[Target, FetchWindow | None]:
    """Give each space and project the week before ``NOW``, as --since 7d does."""
    return given(period("7d", None, NOW), spaces, projects)


def run(store: RawStore, fake: FakeSite) -> Fetching:
    """Run one download of the space and the project over the fake site, over the week."""
    with fake.client() as client, store.writing():
        windows = week(["MFS"], ["PRB"])
        done = Fetching(
            SiteClient(client, sleep=lambda _: None), store, CAP, lambda: NOW, windows=windows
        )
        done.run(["MFS"], ["PRB"])
    return done


def test_a_space_and_a_project_are_downloaded_with_their_files(tmp_path: Path) -> None:
    """What changed in the period is stored with its pictures; what did not, is not."""
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite())
    pages = [item for item in store.latest(Page) if isinstance(item, StoredSnapshot)]
    assert sorted(item.snapshot.document.id for item in pages) == ["1001", "1002"]
    fresh = next(item for item in pages if item.snapshot.document.id == "1001")
    assert fresh.snapshot.html == "<p>view</p>"
    assert store.blob(fresh.blobs["att1"]).read_bytes() == PICTURE
    assert set(fresh.blobs) == {"att1"}  # the video and the file over the cap are listed only
    [post] = store.latest(BlogPost)
    assert isinstance(post, StoredSnapshot)
    [issue] = store.latest(Issue)
    assert isinstance(issue, StoredSnapshot)
    assert [comment.id for comment in issue.snapshot.comments] == ["10100", "10101"]
    assert store.blob(issue.blobs["10000"]).read_bytes() == PICTURE
    assert done.counts.failures == 0


def test_a_space_is_listed_whole_with_its_folders_and_authors(tmp_path: Path) -> None:
    """The tree comes whole, folders followed to the top; the authors are named."""
    store = RawStore(tmp_path / "raw")
    run(store, FakeSite())
    assert sorted(item.id for item in store.listed(SPACE, Page) if isinstance(item, Page)) == [
        "1001",
        "1002",
        "1003",
    ]
    assert sorted(folder.id for folder in store.folders(SPACE)) == ["2001", "2002"]  # type: ignore[union-attr]
    assert [user.display_name for user in store.users()] == ["A Person"]  # type: ignore[union-attr]


def test_a_run_reports_its_targets_their_listings_documents_and_probes(tmp_path: Path) -> None:
    """Each task's last event progress, as it ends: the space's, its probes, the project's.

    The space's pages are listed in two pages, its blog posts in one; it lists three
    pages and a post, of which two pages and the post changed in the week, and are
    fetched. Nothing was stored before, so nothing is probed. The search reads one page
    of two issues, one of them changed in the week.
    """
    with capture_logs() as events:
        run(RawStore(tmp_path / "raw"), FakeSite())
    assert [
        (event["task"], event["done"], event["total"])
        for event in events
        if event["event"] == "progress"
    ] == [
        ("listing", 3, None),
        ("documents", 3, 3),
        ("probes", 0, 0),
        ("listing", 1, None),
        ("documents", 1, 1),
        ("targets", 2, 2),
    ]


def test_a_second_run_fetches_no_document_again(tmp_path: Path) -> None:
    """With nothing changed, only listings and searches are asked for."""
    store = RawStore(tmp_path / "raw")
    fake = FakeSite()
    run(store, fake)
    again = FakeSite()
    done = run(store, again)
    fetched = [url.path for url in again.asked if "/pages/" in url.path or "/issue/" in url.path]
    assert fetched == []
    assert done.counts.counts["confluence pages: already stored"] == len(["1001", "1002"])


@pytest.mark.parametrize(
    ("since", "until"),
    [
        # Late in the UTC day, where UTC+14 is already two dates ahead of the period's end.
        ("2026-10-15T23:30:00+00:00", "2026-10-22T23:30:00+00:00"),
        # Given at UTC-12, late in its day: the next day in UTC, two in UTC+14.
        ("2026-10-15T23:59:00-12:00", "2026-10-21T23:59:00-12:00"),
    ],
)
def test_the_search_covers_the_period_in_every_time_zone_of_jira(
    tmp_path: Path, since: str, until: str
) -> None:
    """Jira reads the JQL's dates at midnight in the user's zone, from UTC-12 to UTC+14.

    Whatever the zone, and whatever offset the period was given in, the dates searched
    must hold the whole period; the period itself then decides on each issue.
    """
    fake = FakeSite()
    store = RawStore(tmp_path / "raw")
    span = period(since, until, NOW)
    with fake.client() as client, store.writing():
        windows = given(span, [], ["PRB"])
        Fetching(SiteClient(client, sleep=no_sleep), store, CAP, lambda: NOW, windows=windows).run(
            [], ["PRB"]
        )
    [search] = [url for url in fake.asked if url.path == "/rest/api/3/search/jql"]
    jql = search.params["jql"]
    assert jql.startswith('project = "PRB" AND updated >= "')
    start, end = (date.fromisoformat(text) for text in re.findall(r'"(\d{4}-\d{2}-\d{2})"', jql))
    for hours in range(-12, 15):
        zone = timezone(timedelta(hours=hours))
        assert datetime.combine(start, time(), zone) <= span.start
        assert datetime.combine(end, time(), zone) >= span.end


def test_a_changed_response_is_kept_raw_and_reported_by_its_path(tmp_path: Path) -> None:
    """A page in a changed shape is stored as received, and the run names the field."""
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite(changed_labels=True))
    results = {
        item.where if isinstance(item, Problem) else item.snapshot.document.id: item
        for item in store.latest(Page)
    }
    assert set(results) == {"1001", "confluence/pages/1002/000003"}
    reason = "document.json.labels.results[0].name: missing"
    assert done.counts.counts[f"confluence pages read failed: {reason}"] == 1


def test_the_report_names_nothing_the_site_served(tmp_path: Path) -> None:
    """Counts and paths only: no title, key, id or name."""
    done = run(RawStore(tmp_path / "raw"), FakeSite(changed_labels=True))
    text = json.dumps(done.counts.counts)
    assert not [word for word in SERVED if word in text]


def test_a_run_sends_the_site_nothing_but_gets(tmp_path: Path) -> None:
    """Listings, documents, files and authors alike: the site changes nothing."""
    fake = FakeSite()
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return fake.handle(request)

    store = RawStore(tmp_path / "raw")
    with (
        httpx.Client(base_url=SITE, transport=httpx.MockTransport(handle)) as client,
        store.writing(),
    ):
        site = SiteClient(client, sleep=lambda _: None)
        windows = week(["MFS"], ["PRB"])
        Fetching(site, store, CAP, lambda: NOW, windows=windows).run(["MFS"], ["PRB"])
    assert set(methods) == {"GET"}


def settings(tmp_path: Path) -> Settings:
    """Return settings with a data directory under the scratch folder."""
    return MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=tmp_path / "data")


def targets(spaces: list[str], projects: list[str]) -> Targets:
    """Return the targets of a run over the last week, with the test's cap."""
    return Targets(
        spaces=spaces, projects=projects, max_file_bytes=CAP, since=period("7d", None, NOW).start
    )


def saved_session(tmp_path: Path, monkeypatch: MonkeyPatch, fake: FakeSite) -> Settings:
    """Save a session, and let the run's client reach the fake site."""
    chosen = settings(tmp_path)
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    return chosen


def no_sleep(_: float) -> None:
    """Wait for nothing."""


def test_without_a_saved_session_the_run_asks_to_sign_in(tmp_path: Path) -> None:
    """No cookies saved: nothing is asked of the site, and the status says sign in.

    The report is named by the run's source, after its time.
    """
    outcome = run_fetch(settings(tmp_path), targets(["MFS"], []), lambda: NOW, no_sleep)
    assert outcome.ending == "sign in again"
    assert outcome.counts.counts["runs: stopped, sign-in needed"] == 1
    [report] = (tmp_path / "data" / "runs").iterdir()
    assert report.name == "20261022T090000Z-confluence.json"
    assert json.loads(report.read_text("utf-8"))["ending"] == "sign in again"


@pytest.mark.parametrize(("spaces", "projects"), [([], []), (["MFS"], ["PRB"])])
def test_a_run_of_no_source_or_of_both_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: MonkeyPatch, spaces: list[str], projects: list[str]
) -> None:
    """Plan 030: a fetch is of one source, whose report is its own; asked nothing, no report."""
    fake = FakeSite()
    chosen = saved_session(tmp_path, monkeypatch, fake)
    said = f"a fetch is of one source: spaces {spaces}, projects {projects}"
    with pytest.raises(ValueError, match=f"^{re.escape(said)}$"):
        run_fetch(chosen, targets(spaces, projects), lambda: NOW, no_sleep)
    assert fake.asked == []
    assert not chosen.runs.exists()
    assert not chosen.raw.exists()


def test_a_run_of_projects_alone_does_nothing_of_confluence_s(
    tmp_path: Path, monkeypatch: MonkeyPatch, telemetry: InMemory
) -> None:
    """Plan 030: Jira's fetch asks Confluence nothing, probes nothing, names no user.

    Neither its report nor its trace holds anything of Confluence's.
    """
    fake = FakeSite()
    chosen = saved_session(tmp_path, monkeypatch, fake)
    outcome = run_fetch(chosen, targets([], ["PRB"]), lambda: NOW, no_sleep)
    assert outcome.ending == "done"
    assert outcome.counts.counts["jira issues: fetched"] == 1
    assert [what for what in outcome.counts.counts if "confluence" in what] == []
    assert [url.path for url in fake.asked if url.path.startswith("/wiki/")] == []
    spans = {span.name for span in telemetry.spans.get_finished_spans()}
    assert "fetch.project" in spans
    assert spans & {"fetch.space", "fetch.probes", "fetch.users"} == set()


def test_an_expired_session_stops_the_run_before_anything_is_stored(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Confluence answering as to an anonymous user means the session has expired."""
    chosen = saved_session(tmp_path, monkeypatch, FakeSite(anonymous=True))
    outcome = run_fetch(chosen, targets(["MFS"], []), lambda: NOW, no_sleep)
    assert outcome.ending == "sign in again"
    assert not (chosen.raw / "confluence" / "pages").exists()


def test_a_run_with_a_failure_says_so_in_its_status(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A document that failed makes the run's status 1, and its report says why."""
    chosen = saved_session(tmp_path, monkeypatch, FakeSite(changed_labels=True))
    outcome = run_fetch(chosen, targets(["MFS"], []), lambda: NOW, no_sleep)
    assert outcome.ending == "failed"
    assert outcome.counts.failures == 1
    [report] = chosen.runs.iterdir()
    assert json.loads(report.read_text("utf-8"))["ending"] == "failed"


def test_only_the_site_cookies_with_a_value_are_saved_back(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A cookie that the media host set, or one without a value, never joins the session."""
    fake = FakeSite(set_cookies=["rolled=2; Domain=.example.invalid; Path=/wiki", "empty"])
    chosen = saved_session(tmp_path, monkeypatch, fake)
    run_fetch(chosen, targets(["MFS"], []), lambda: NOW, no_sleep)
    saved = read_cookies(chosen.session / COOKIES)
    assert {cookie["name"] for cookie in saved} == {"rolled"}
    assert (chosen.session / COOKIES).stat().st_mode & 0o777 == OWNER_ONLY
    assert for_site(
        [
            {"name": "kept", "value": "1", "domain": ".example.invalid"},
            {"name": "media", "value": "2", "domain": ".atlassian.com"},
            {"name": "none", "value": None, "domain": ".example.invalid"},
        ],
        "sandbox.example.invalid",
    ) == [{"name": "kept", "value": "1", "domain": ".example.invalid", "path": "/"}]


def test_a_space_key_that_finds_nothing_fails_the_run_and_is_named_locally(
    tmp_path: Path,
) -> None:
    """The key goes to not_found, for the command to print; the report counts a failure."""
    fake = FakeSite(spaces=[])
    store = RawStore(tmp_path / "raw")
    with fake.client() as client, store.writing():
        site = SiteClient(client, sleep=no_sleep)
        done = Fetching(site, store, CAP, lambda: NOW, windows=week(["ENG"], []))
        done.run(["ENG"], [])
    assert done.problems == [Problem(where="space ENG", reason="not found")]
    assert done.counts.counts["confluence spaces failed: not found"] == 1
    assert done.counts.failures == 1


def test_a_site_without_jira_still_downloads_its_spaces(tmp_path: Path) -> None:
    """Jira not answering is one failure; the spaces are downloaded all the same."""
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite(jira=False))
    assert done.counts.counts["jira failed: status 404"] == 1
    assert [item for item in store.latest(Page) if isinstance(item, StoredSnapshot)]
    assert list(store.latest(Issue)) == []


def test_a_run_stops_when_the_site_stops_answering(tmp_path: Path) -> None:
    """When every document's GET goes unanswered, the run stops instead of trying all."""
    store = RawStore(tmp_path / "raw")
    fake = FakeSite(pages_fail=True, many_pages=MAX_FAILED_IN_A_ROW + 5)
    with fake.client() as client, store.writing():
        windows = week(["MFS"], [])
        done = Fetching(
            SiteClient(client, sleep=no_sleep), store, CAP, lambda: NOW, windows=windows
        )
        with pytest.raises(TooManyFailuresError):
            done.run(["MFS"], [])
    assert done.counts.counts["confluence pages failed: status 503"] == MAX_FAILED_IN_A_ROW


def test_an_answer_that_is_not_json_fails_one_document_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    """A proxy page instead of one document's JSON costs that document alone."""
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite(html_page="1002"))
    assert done.counts.counts["confluence pages failed: not JSON"] == 1
    pages = [
        item.snapshot.document.id for item in store.latest(Page) if isinstance(item, StoredSnapshot)
    ]
    assert pages == ["1001"]
    assert [item for item in store.latest(Issue) if isinstance(item, StoredSnapshot)]


def test_a_listing_entry_with_a_changed_field_is_still_fetched(tmp_path: Path) -> None:
    """Only id, version and time decide a fetch: a listing without titles still works."""
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite(listing_changed=True))
    pages = [
        item.snapshot.document.id for item in store.latest(Page) if isinstance(item, StoredSnapshot)
    ]
    assert sorted(pages) == ["1001", "1002"]
    assert done.counts.counts["confluence pages: fetched"] == len(pages)


def test_a_file_that_failed_is_downloaded_by_a_later_run(tmp_path: Path) -> None:
    """The snapshot is kept without the file; the next run fetches the file alone."""
    store = RawStore(tmp_path / "raw")
    first = run(store, FakeSite(media_fails=True))
    assert first.counts.counts["files failed: status 500"] >= 1
    [fresh] = [
        item
        for item in store.latest(Page)
        if isinstance(item, StoredSnapshot) and item.snapshot.document.id == "1001"
    ]
    assert "att1" not in fresh.blobs
    again = FakeSite()
    second = run(store, again)
    assert second.counts.counts["confluence pages: already stored"] == len(["1001", "1002"])
    assert store.read(fresh.snapshot.document).blobs["att1"]
    assert not [url for url in again.asked if url.path.startswith("/wiki/api/v2/pages/")]


def test_a_second_run_downloads_no_file_again(tmp_path: Path) -> None:
    """Posts and issues already stored, with their files, cost no request but listings."""
    store = RawStore(tmp_path / "raw")
    run(store, FakeSite())
    again = FakeSite()
    done = run(store, again)
    assert "files: downloaded" not in done.counts.counts
    assert done.counts.counts["confluence blogposts: already stored"] == 1
    assert done.counts.counts["jira issues: already stored"] == 1
    assert not [
        url for url in again.asked if "/attachment" in url.path or url.path == "/file/abc/binary"
    ]


def test_an_expired_session_still_leaves_a_run_report(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The report says why the run stopped."""
    chosen = saved_session(tmp_path, monkeypatch, FakeSite(anonymous=True))
    run_fetch(chosen, targets(["MFS"], []), lambda: NOW, no_sleep)
    [report] = chosen.runs.iterdir()
    saved = json.loads(report.read_text("utf-8"))
    assert saved["ending"] == "sign in again"
    assert saved["counts"]["runs: stopped, sign-in needed"] == 1


def test_files_failing_one_after_another_never_stop_the_run(tmp_path: Path) -> None:
    """Raw first: the page is stored without its files, and the rest of the run goes on.

    A refused file is an answer from the site; only unanswered GETs stop a run.
    """
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite(failing_files=MAX_FAILED_IN_A_ROW + 2))
    assert done.counts.counts["files failed: status 404"] == MAX_FAILED_IN_A_ROW + 2
    stored = {
        item.snapshot.document.id for item in store.latest(Page) if isinstance(item, StoredSnapshot)
    }
    assert stored == {"1001", "1002"}
    assert [item for item in store.latest(BlogPost) if isinstance(item, StoredSnapshot)]
    assert [item for item in store.latest(Issue) if isinstance(item, StoredSnapshot)]


def test_a_project_that_jira_refuses_is_named_for_the_user(tmp_path: Path) -> None:
    """A JQL refused (an unknown project, say) names the key for stderr, not the report."""
    done = run(RawStore(tmp_path / "raw"), FakeSite(search_status=400))
    assert done.problems == [Problem(where="project PRB", reason="status 400")]
    assert done.counts.counts["jira projects failed: status 400"] == 1
    assert "PRB" not in json.dumps(done.counts.counts)


def test_a_search_entry_with_a_changed_field_is_still_fetched(tmp_path: Path) -> None:
    """An issue is fetched on its id and update time alone, whatever else the entry lost."""
    store = RawStore(tmp_path / "raw")
    run(store, FakeSite(search_changed=True))
    assert [item for item in store.latest(Issue) if isinstance(item, StoredSnapshot)]


def test_a_user_the_adapter_refuses_fails_alone(tmp_path: Path) -> None:
    """An author without an account id is counted; the run's documents are all kept."""
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite(bulk_changed=True))
    assert done.counts.counts["confluence users failed: users[0].accountId: missing"] == 1
    assert store.users() == []


def test_a_listing_entry_that_only_the_tree_needs_is_reported(tmp_path: Path) -> None:
    """A page entry without its title is fetched all the same, and its path is reported."""
    done = run(RawStore(tmp_path / "raw"), FakeSite(listing_changed=True))
    reason = "pages.title: missing"
    assert done.counts.counts[f"confluence pages in the tree failed: {reason}"] == len(
        ["1001", "1002"]
    )


def test_folders_over_the_cap_are_counted(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The walk up the folders is bounded, and what it leaves out is said."""
    monkeypatch.setattr(fetching_module, "MAX_FOLDERS", 1)
    done = run(RawStore(tmp_path / "raw"), FakeSite())
    assert done.counts.counts["confluence folders: over the cap, left out"] == 1


def test_a_busy_store_refuses_the_run_and_writes_no_report(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Another run writing: nothing is fetched, and no report is left."""
    chosen = saved_session(tmp_path, monkeypatch, FakeSite())
    with RawStore(chosen.raw).writing(), pytest.raises(StoreBusyError):
        run_fetch(chosen, targets(["MFS"], []), lambda: NOW, no_sleep)
    assert not chosen.runs.exists()


def test_a_file_not_of_its_listed_size_is_not_kept(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A proxy's page in a file's place is refused, so that a later run fetches it again."""
    wrong = v2_attachment(
        id="att9",
        fileSize=len(PICTURE) + 1,
        downloadLink="/rest/api/content/1001/child/attachment/att1/download",
    )
    monkeypatch.setitem(ATTACHMENTS, "1101", [wrong])
    store = RawStore(tmp_path / "raw")
    done = run(store, FakeSite())
    assert done.counts.counts["files failed: not the size listed"] == 1
    [post] = [item for item in store.latest(BlogPost) if isinstance(item, StoredSnapshot)]
    assert post.blobs == {}
