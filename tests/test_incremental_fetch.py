"""Runs after the first: catch-up, backfill, plans, deletions and moves, over a scripted site."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic_core import to_jsonable_python
from structlog.testing import capture_logs

from kb_mcp.cli.main import main
from kb_mcp.kernel.records import Problem
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.search.adapters.sqlite_index import reading
from kb_mcp.search.app.indexing import build_index, updated
from kb_mcp.sources.atlassian.declared import JIRA
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore, StoredSnapshot
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, folder_of, write_cookies
from kb_mcp.sources.atlassian.fetch.app import fetching
from kb_mcp.sources.atlassian.fetch.app.fetching import Purview, plan_fetch, run_fetch
from kb_mcp.sources.atlassian.fetch.domain import names
from kb_mcp.sources.atlassian.fetch.domain.content import Issue, Page
from kb_mcp.sources.atlassian.fetch.domain.coverage import Coverage, FetchWindow, Scope
from kb_mcp.sources.atlassian.fetch.domain.deletions import CONFIRM_AFTER
from kb_mcp.sources.atlassian.fetch.domain.period import EPOCH, Period, PeriodError
from kb_mcp.sources.declaration import Source
from kb_mcp.sources.registry import SOURCES
from tests.composed import MODEL, model_of
from tests.mirrors import prepared_sources
from tests.samples import v2_page, v2_space
from tests.test_fetching import (
    CAP,
    ISSUE,
    PAGES,
    SITE,
    SPACE,
    FakeSite,
    scopes,
    stamp,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.kernel.names import Ending

FIRST = datetime(2026, 10, 22, 9, tzinfo=UTC)
SECOND = datetime(2026, 10, 23, 9, tzinfo=UTC)
WEEK = timedelta(days=7)
YEAR = timedelta(days=365)
# The space and the project that the scripted site serves, as scopes.
MFS = Scope(source="confluence", type=names.SPACE, key="MFS")
PRB = Scope(source="jira", type=names.PROJECT, key="PRB")
MANY = 30
OTHER_SPACE = "300000"
FAILED = 1


@dataclass
class RefreshSite(FakeSite):
    """The scripted site of plan 004, whose listing and pages can change between runs.

    ``listing`` replaces the space's pages; ``gone`` answer 404 when probed, ``moved``
    answer from another space, and ``moved_issues`` from another project; Confluence reads
    as anonymous after ``anonymous_after`` asks for the current user.
    """

    listing: dict[str, dict[str, object]] = field(default_factory=lambda: dict(PAGES))
    gone: set[str] = field(default_factory=set)
    moved: dict[str, str] = field(default_factory=dict)
    moved_issues: dict[str, str] = field(default_factory=dict)
    others: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    anonymous_after: int | None = None
    user_asks: int = 0

    def routes(self) -> dict[str, Callable[[httpx.Request], httpx.Response]]:
        """Serve the base site, with this run's listing, pages and probes."""
        routes = super().routes()
        routes[f"/wiki/api/v2/spaces/{SPACE}/pages"] = lambda _: httpx.Response(
            200, json={"results": list(self.listing.values()), "_links": {}}
        )
        routes["/wiki/rest/api/user/current"] = self.user
        # Other spaces, each with its key and its listing of pages; MFS answers as before.
        spaces = {"MFS": v2_space()} | {
            key: v2_space(id=OTHER_SPACE, key=key, name=key) for key in self.others
        }
        routes["/wiki/api/v2/spaces"] = lambda request: httpx.Response(
            200, json={"results": [spaces[request.url.params["keys"]]]}
        )
        for pages in self.others.values():
            routes[f"/wiki/api/v2/spaces/{OTHER_SPACE}/pages"] = lambda _, p=pages: httpx.Response(
                200, json={"results": p, "_links": {}}
            )
            routes[f"/wiki/api/v2/spaces/{OTHER_SPACE}/blogposts"] = lambda _: httpx.Response(
                200, json={"results": [], "_links": {}}
            )
        for page_id in {*self.listing, *self.gone, *self.moved}:
            page = self.listing.get(page_id) or PAGES.get(page_id) or v2_page(id=page_id)
            routes[f"/wiki/api/v2/pages/{page_id}"] = lambda request, p=page: self.page(request, p)
            routes[f"/wiki/api/v2/pages/{page_id}/attachments"] = lambda _: httpx.Response(
                200, json={"results": [], "_links": {}}
            )
        for issue_id, project in self.moved_issues.items():
            moved = {"id": issue_id, "fields": {"project": {"key": project}}}
            routes[f"/rest/api/3/issue/{issue_id}"] = lambda _, m=moved: httpx.Response(200, json=m)
        return routes

    def user(self, _: httpx.Request) -> httpx.Response:
        """Answer the current user, until the session is made to expire."""
        self.user_asks += 1
        expired = self.anonymous_after is not None and self.user_asks > self.anonymous_after
        return httpx.Response(200, json={"type": "anonymous"} if expired else {"accountId": "a"})

    def page(self, request: httpx.Request, page: dict[str, object]) -> httpx.Response:
        """Serve a page's body, or, asked with no body, where the page is."""
        page_id = str(page["id"])
        if "body-format" in request.url.params:
            return self.document(request, page)
        if page_id in self.gone:
            return httpx.Response(404)
        space = self.moved.get(page_id, SPACE)
        return httpx.Response(200, json={"id": page_id, "spaceId": space, "status": "current"})


def settings(tmp_path: Path) -> Settings:
    """Return settings with a data directory, and a saved session, under the scratch folder."""
    chosen = MODEL(
        sources={"confluence": {"site": SITE}, "jira": {"site": SITE}}, data_dir=tmp_path / "data"
    )
    write_cookies(
        folder_of(chosen.session, SITE) / COOKIES, [{"name": "s", "value": "v", "domain": "x"}]
    )
    return chosen


def run(
    chosen: Settings,
    monkeypatch: MonkeyPatch,
    fake: FakeSite,
    purview: Purview,
    now: datetime,
) -> Ending:
    """Run one download at ``now`` over the fake site, and return how it ended."""
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    return run_fetch(chosen, purview, lambda: now, lambda _: None).ending


def first_week(spaces: list[str], projects: list[str]) -> Purview:
    """Return the purview of a first run over the week before ``FIRST``."""
    return Purview(scopes=scopes(spaces, projects), max_file_bytes=CAP, since=FIRST - WEEK)


def catch_up(spaces: list[str], projects: list[str]) -> Purview:
    """Return the purview of a later run, from what is covered."""
    return Purview(scopes=scopes(spaces, projects), max_file_bytes=CAP)


def stored_pages(chosen: Settings) -> dict[str, str]:
    """Map each stored page to its stored revision."""
    return {
        item.snapshot.document.id: item.snapshot.document.revision
        for item in RawStore(chosen.raw, "confluence").latest(Page)
        if isinstance(item, StoredSnapshot)
    }


def test_a_first_run_starts_the_coverage_of_each_target(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A run of each source with --since 7d covers the week, for every target listed whole."""
    chosen = settings(tmp_path)
    assert run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST) == "done"
    assert run(chosen, monkeypatch, RefreshSite(), first_week([], ["PRB"]), FIRST) == "done"
    assert RawStore(chosen.raw, "confluence").coverage().periods == {
        MFS: Period(FIRST - WEEK, FIRST),
        PRB: Period(FIRST - WEEK, FIRST),
    }


def test_a_later_run_catches_up_on_an_old_page_edited_since(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """With no --since, a page last edited before the first run, and edited today, comes."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    assert "1003" not in stored_pages(chosen)
    edited = {"number": 4, "createdAt": "2026-10-23T08:00:00.000Z"}
    listing = {**PAGES, "1003": {**PAGES["1003"], "version": edited}}
    later = RefreshSite(listing=listing)
    assert run(chosen, monkeypatch, later, catch_up(["MFS"], []), SECOND) == "done"
    assert stored_pages(chosen)["1003"] == "000004"
    assert RawStore(chosen.raw, "confluence").coverage().periods[MFS] == Period(
        FIRST - WEEK, SECOND
    )


def test_a_page_that_joined_a_space_since_its_listing_comes_whatever_its_update_time(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 056: moved in with an old update time, it is fetched, so the coverage stays exact.

    The first run met no failure and left the space exact: the next starts a day before
    its covered end, long after the page's update time.
    """
    chosen = settings(tmp_path)
    first = RefreshSite(listing=without("1003"))
    assert run(chosen, monkeypatch, first, first_week(["MFS"], []), FIRST) == "done"
    assert RawStore(chosen.raw, "confluence").coverage().exact == {MFS}
    with capture_logs() as events:
        assert run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), SECOND) == "done"
    [listed] = [each for each in events if each["event"] == "fetch.listed"]
    assert listed["reason"] == "since the last fetch"
    assert stored_pages(chosen)["1003"] == "000003"
    assert RawStore(chosen.raw, "confluence").coverage().exact == {MFS}


def test_a_page_that_joined_and_failed_is_asked_for_again_by_the_next_run(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The listing is replaced once what joined is stored: a failed run finds it joined again."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(listing=without("1003")), first_week(["MFS"], []), FIRST)
    failing = RefreshSite(pages_fail=True)
    assert run(chosen, monkeypatch, failing, catch_up(["MFS"], []), SECOND) == "failed"
    assert "1003" not in stored_pages(chosen)
    later = SECOND + timedelta(hours=1)
    assert run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), later) == "done"
    assert stored_pages(chosen)["1003"] == "000003"


def test_a_space_whose_joined_page_failed_still_follows_a_deletion_and_keeps_it_pending(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The listing is stored after every whole read; what joined and failed waits, pending.

    So a page deleted in the run that failed the joined one is tracked as absent, and the
    next run fetches the joined page whatever its update time.
    """
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(listing=without("1003")), first_week(["MFS"], []), FIRST)
    deleted = {key: value for key, value in PAGES.items() if key != "1001"}
    failing = RefreshSite(listing=deleted, gone={"1001"}, pages_fail=True)
    assert run(chosen, monkeypatch, failing, catch_up(["MFS"], []), SECOND) == "failed"
    store = RawStore(chosen.raw, "confluence")
    assert store.listed_ids(SPACE, Page) == {"1002", "1003"}
    assert store.pending(SPACE) == {"1003"}
    assert list(store.tombstones()) == [("confluence", "page", "1001")]
    later = SECOND + timedelta(hours=1)
    run(
        chosen,
        monkeypatch,
        RefreshSite(listing=deleted, gone={"1001"}),
        catch_up(["MFS"], []),
        later,
    )
    assert stored_pages(chosen)["1003"] == "000003"
    assert store.pending(SPACE) == set()


def test_a_former_tombstone_of_a_space_not_yet_listed_is_found_by_its_whole_read(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Kept under its space's id, it joins the space's scope once the space is listed."""
    chosen = settings(tmp_path)
    chosen.raw.mkdir(parents=True)
    (chosen.raw / "tombstones.json").write_text(
        f'[{{"kind": "pages", "id": "1009", "space": "{SPACE}", "first_gone": null,'
        ' "confirmed": false}]',
        "utf-8",
    )
    run(chosen, monkeypatch, RefreshSite(gone={"1009"}), first_week(["MFS"], []), FIRST)
    [stone] = RawStore(chosen.raw, "confluence").tombstones().values()
    assert (stone.scope, stone.id, stone.first_gone) == (MFS, "1009", FIRST)


def test_a_joined_entry_that_the_adapter_refuses_comes_once_it_reads_without_an_edit(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Joined by its entry's id, refused, it stays pending: read unedited, it comes.

    The space is exact only after the run that stores it.
    """
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(listing=without("1003")), first_week(["MFS"], []), FIRST)
    versionless = {key: value for key, value in PAGES["1003"].items() if key != "version"}
    refused = RefreshSite(listing={**PAGES, "1003": versionless})
    assert run(chosen, monkeypatch, refused, catch_up(["MFS"], []), SECOND) == "failed"
    store = RawStore(chosen.raw, "confluence")
    assert (store.pending(SPACE), store.coverage().exact) == ({"1003"}, frozenset())
    later = SECOND + timedelta(hours=1)
    assert run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), later) == "done"
    assert stored_pages(chosen)["1003"] == "000003"
    assert (store.pending(SPACE), store.coverage().exact) == (set(), {MFS})


def test_an_upgraded_space_fetches_what_its_tag_listing_named_inside_its_covered_period(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The tag's coverage and listing: a page moved in during the covered period is stored.

    The tag never fetched it; one updated before the covered start stays history. The
    space is exact only once that page is stored.
    """
    chosen = settings(tmp_path)
    chosen.raw.mkdir(parents=True)
    start = FIRST - WEEK
    period = {"start": start.isoformat(), "end": FIRST.isoformat()}
    (chosen.raw / "coverage.json").write_text(
        json.dumps([{"source": "confluence", "key": "MFS", **period}]), "utf-8"
    )
    store = RawStore(chosen.raw, "confluence")
    with store.writing():
        store.put_space(v2_space(), list(PAGES.values()), [], [])
    failing = RefreshSite(pages_fail=True)
    assert run(chosen, monkeypatch, failing, catch_up(["MFS"], []), SECOND) == "failed"
    assert store.coverage().exact == frozenset()
    later = SECOND + timedelta(hours=1)
    assert run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), later) == "done"
    assert sorted(stored_pages(chosen)) == ["1001", "1002"]
    assert store.coverage().exact == {MFS}


def test_a_pending_page_that_the_next_listing_omits_leaves_pending(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Pending is of what the space lists: a page gone from it is no longer to fetch."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(listing=without("1003")), first_week(["MFS"], []), FIRST)
    run(chosen, monkeypatch, RefreshSite(pages_fail=True), catch_up(["MFS"], []), SECOND)
    store = RawStore(chosen.raw, "confluence")
    assert store.pending(SPACE) == {"1003"}
    gone = RefreshSite(listing=without("1003"), gone={"1003"})
    run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(hours=1))
    assert store.pending(SPACE) == set()
    assert "1003" not in stored_pages(chosen)


def test_an_old_page_that_the_first_listing_named_waits_for_an_edit_or_since(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 056's limit: older history than the coverage is fetched by --since, not by a catch-up.

    Only what joined the space since its stored listing is taken whatever its update time.
    """
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    assert run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), SECOND) == "done"
    assert "1003" not in stored_pages(chosen)


def test_a_fetch_records_the_whole_read_of_a_space_and_of_a_project_at_its_first_fetch(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 061: each is read whole as the run starts; a project's search is not one."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    run(chosen, monkeypatch, RefreshSite(), first_week([], ["PRB"]), FIRST)
    run(chosen, monkeypatch, RefreshSite(), catch_up([], ["PRB"]), SECOND)
    assert RawStore(chosen.raw, "confluence").coverage().whole_read_at == {MFS: FIRST, PRB: FIRST}


def test_an_earlier_since_reaches_further_and_moves_the_covered_start(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--since 1y, where --back went: the old page comes, and the coverage starts a year back."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    targets = Purview(scopes=scopes(["MFS"], []), max_file_bytes=CAP, since=SECOND - YEAR)
    assert run(chosen, monkeypatch, RefreshSite(), targets, SECOND) == "done"
    assert stored_pages(chosen)["1003"] == "000003"
    covered = RawStore(chosen.raw, "confluence").coverage().periods[MFS]
    assert covered == Period(SECOND - YEAR, SECOND)


def test_an_until_before_since_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Refused by name, before any request, and nothing is written."""
    chosen = settings(tmp_path)
    fake = RefreshSite()
    backwards = Purview(
        scopes=scopes(["MFS"], []), max_file_bytes=CAP, since=FIRST, until=FIRST - WEEK
    )
    with pytest.raises(PeriodError, match=r"^--until: must come after --since"):
        run(chosen, monkeypatch, fake, backwards, FIRST)
    assert fake.asked == []
    assert not chosen.raw.exists()
    assert not chosen.runs.exists()


def test_a_target_whose_listing_failed_keeps_its_coverage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A refused search leaves the project uncovered; the space is covered all the same."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(search_status=400), first_week(["MFS"], []), FIRST)
    run(chosen, monkeypatch, RefreshSite(search_status=400), first_week([], ["PRB"]), FIRST)
    assert set(RawStore(chosen.raw, "confluence").coverage().periods) == {MFS}


def test_a_plan_lists_and_decides_and_writes_nothing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A dry run asks only for listings and searches, and leaves the data directory as it was."""
    chosen = settings(tmp_path)
    fake = RefreshSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    confluence, jira = (
        plan_fetch(chosen, first_week(spaces, projects), lambda: FIRST, lambda _: None)
        for spaces, projects in ((["MFS"], []), ([], ["PRB"]))
    )
    assert (confluence.ending, jira.ending) == ("not run", "not run")
    assert confluence.counts.counts["confluence pages: to fetch"] == len(["1001", "1002"])
    assert jira.counts.counts["jira issues: to fetch"] == 1
    assert jira.counts.counts["files: to download"] == 1
    assert jira.counts.counts["files: bytes to download"] > 0
    fetched = [url.path for url in fake.asked if "/pages/" in url.path or "/issue/" in url.path]
    assert fetched == []
    left = sorted(
        path.relative_to(chosen.data_dir).as_posix() for path in chosen.data_dir.rglob("*")
    )
    host = "session/sandbox.example.invalid"
    assert left == ["session", host, f"{host}/cookies.json"]


def without(page_id: str) -> dict[str, dict[str, object]]:
    """Return the space's listing without one page."""
    return {key: value for key, value in PAGES.items() if key != page_id}


def test_a_page_gone_on_two_runs_is_confirmed_and_one_back_loses_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Absent and 404 once: a tombstone; twice: confirmed; listed again: no tombstone."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    gone = RefreshSite(listing=without("1002"), gone={"1002"})
    run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND)
    [stone] = RawStore(chosen.raw, "confluence").tombstones().values()
    assert (stone.key, stone.confirmed) == (("confluence", "page", "1002"), False)
    gone_again = RefreshSite(listing=without("1002"), gone={"1002"})
    run(chosen, monkeypatch, gone_again, catch_up(["MFS"], []), SECOND + timedelta(days=1))
    [stone] = RawStore(chosen.raw, "confluence").tombstones().values()
    assert stone.confirmed
    run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), SECOND + timedelta(days=2))
    assert RawStore(chosen.raw, "confluence").tombstones() == {}


def test_the_probes_of_a_space_are_reported_as_a_task(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Two pages no longer listed: two probes, both done."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    both = RefreshSite(listing={"1003": PAGES["1003"]}, gone={"1001", "1002"})
    with capture_logs() as events:
        run(chosen, monkeypatch, both, catch_up(["MFS"], []), SECOND)
    probes = [event for event in events if event.get("task") == "probes"]
    assert [(event["done"], event["total"]) for event in probes] == [(2, 2)]


def test_a_page_moved_to_another_space_listed_in_the_run_is_not_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Absent from its space, but answering from another space that this run lists."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    moved_page = {**PAGES["1001"], "spaceId": OTHER_SPACE}
    moved = RefreshSite(
        listing=without("1001"), moved={"1001": OTHER_SPACE}, others={"OPS": [moved_page]}
    )
    run(chosen, monkeypatch, moved, first_week(["MFS", "OPS"], []), SECOND)
    assert RawStore(chosen.raw, "confluence").tombstones() == {}


def test_a_page_found_in_a_stored_space_that_does_not_list_it_waits(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Found in a space this run does not list, whose stored listing lacks it: kept, pending."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    store = RawStore(chosen.raw, "confluence")
    with store.writing():
        store.put_space(v2_space(id=OTHER_SPACE, key="OPS", name="Ops"), [], [], [])
    for day in (0, 1):
        moved = RefreshSite(listing=without("1001"), moved={"1001": OTHER_SPACE})
        run(chosen, monkeypatch, moved, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    [stone] = store.tombstones().values()
    assert (stone.key, stone.first_gone, stone.confirmed) == (
        ("confluence", "page", "1001"),
        None,
        False,
    )
    prepared_sources(store, chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1001-*.md"))


def test_a_page_found_in_a_stored_space_whose_listing_names_it_is_followed_there(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Named by a space's stored listing, though this run does not list it: moved, not hidden."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    store = RawStore(chosen.raw, "confluence")
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [{**PAGES["1001"], "spaceId": OTHER_SPACE}], [], [], listed_at=FIRST)
    for day in (0, 1):
        moved = RefreshSite(listing=without("1001"), moved={"1001": OTHER_SPACE})
        run(chosen, monkeypatch, moved, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    assert store.tombstones() == {}
    prepared_sources(store, chosen.docs, SITE, identity)
    assert [path.parent.name for path in chosen.docs.rglob("1001-*.md")] == ["OPS"]


def test_a_page_on_its_way_is_probed_before_one_newly_absent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """With room for one probe, the page answered gone once is confirmed, not starved."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    gone = RefreshSite(listing=without("1002"), gone={"1002"})
    run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND)
    monkeypatch.setattr("kb_mcp.sources.atlassian.fetch.app.fetching.MAX_PROBES", 1)
    both = RefreshSite(listing={"1003": PAGES["1003"]}, gone={"1001", "1002"})
    run(chosen, monkeypatch, both, catch_up(["MFS"], []), SECOND + timedelta(days=1))
    stones = RawStore(chosen.raw, "confluence").tombstones()
    assert stones[("confluence", "page", "1002")].confirmed
    assert stones[("confluence", "page", "1001")].first_gone is None


def test_a_listed_entry_that_the_reader_refuses_is_not_absent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The new listing is read by id too: an entry refused for its version is still listed."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    versionless = {key: value for key, value in PAGES["1002"].items() if key != "version"}
    refused = RefreshSite(listing={**PAGES, "1002": versionless}, gone={"1002"})
    run(chosen, monkeypatch, refused, catch_up(["MFS"], []), SECOND)
    assert RawStore(chosen.raw, "confluence").tombstones() == {}


def test_a_listed_entry_that_the_reader_refuses_leaves_the_space_inexact_until_it_reads(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """It has no update time to stop at: the next catch-up asks from the covered start.

    Edited on the 21st, the page is refused on the 23rd; on the 26th, read again, it
    comes, though a day before the covered end is after its edit.
    """
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    edited = {**PAGES["1002"], "version": stamp(21, number=4)}
    versionless = {key: value for key, value in edited.items() if key != "version"}
    refused = RefreshSite(listing={**PAGES, "1002": versionless})
    assert run(chosen, monkeypatch, refused, catch_up(["MFS"], []), SECOND) == "failed"
    assert RawStore(chosen.raw, "confluence").coverage().exact == frozenset()
    with capture_logs() as events:
        later = RefreshSite(listing={**PAGES, "1002": edited})
        run(chosen, monkeypatch, later, catch_up(["MFS"], []), SECOND + timedelta(days=3))
    [listed] = [each for each in events if each["event"] == "fetch.listed"]
    assert listed["reason"] == "covered start"
    assert stored_pages(chosen)["1002"] == "000004"


def test_a_page_moved_out_of_the_kept_spaces_is_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Moved where no run looks: it has left the mirror's scope, like a deleted page."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    moved = RefreshSite(listing=without("1001"), moved={"1001": OTHER_SPACE})
    run(chosen, monkeypatch, moved, catch_up(["MFS"], []), SECOND)
    assert list(RawStore(chosen.raw, "confluence").tombstones()) == [("confluence", "page", "1001")]


def test_many_gone_with_a_lost_session_write_no_tombstone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Thirty pages gone at once, and Confluence then reads as anonymous: believe none."""
    chosen = settings(tmp_path)
    many = {str(5000 + n): v2_page(id=str(5000 + n), version=stamp(20)) for n in range(MANY)}
    run(chosen, monkeypatch, RefreshSite(listing=many), first_week(["MFS"], []), FIRST)
    lost = RefreshSite(listing={}, gone=set(many), anonymous_after=1)
    assert run(chosen, monkeypatch, lost, catch_up(["MFS"], []), SECOND) == "sign in again"
    stones = RawStore(chosen.raw, "confluence").tombstones().values()
    assert len(stones) == MANY  # each absent page waits for a probe
    assert [stone for stone in stones if stone.first_gone is not None] == []


def identity(html: str) -> str:
    """Write HTML as it is, standing in for pandoc."""
    return html


def test_the_mirror_leaves_out_a_confirmed_tombstone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Once confirmed gone, a page's file leaves the mirror."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
    names = sorted(path.name for path in (chosen.docs / "confluence" / "MFS").glob("*.md"))
    assert [name for name in names if name.startswith("1002-")] == []
    assert [name for name in names if name.startswith("1001-")]


def test_the_mirror_places_a_page_in_the_space_that_lists_it(tmp_path: Path) -> None:
    """A page listed in another space than its snapshot names is prepared there."""
    store = RawStore(tmp_path / "raw", "confluence")
    responses = {
        "document.json": v2_page(),
        "view.json": v2_page(body={"view": {"value": "<p>v</p>", "representation": "view"}}),
        "attachments.json": [],
    }
    with store.writing():
        store.put(Page, responses, FIRST, {})
        store.put_space(v2_space(), [], [], [])
        store.put_space(
            v2_space(id=OTHER_SPACE, key="OPS", name="Ops"), [v2_page(spaceId=OTHER_SPACE)], [], []
        )
    prepared_sources(store, tmp_path / "docs", SITE, identity)
    placed = (tmp_path / "docs" / "confluence").rglob("196845-*.md")
    assert [path.parent.name for path in placed] == ["OPS"]


def test_many_gone_with_the_session_holding_are_believed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A real mass deletion: the canary still signs in, so the tombstones are written."""
    chosen = settings(tmp_path)
    many = {str(5000 + n): v2_page(id=str(5000 + n), version=stamp(20)) for n in range(MANY)}
    run(chosen, monkeypatch, RefreshSite(listing=many), first_week(["MFS"], []), FIRST)
    deleted = RefreshSite(listing={}, gone=set(many))
    assert run(chosen, monkeypatch, deleted, catch_up(["MFS"], []), SECOND) == "done"
    assert len(RawStore(chosen.raw, "confluence").tombstones()) == MANY


def test_a_page_that_comes_back_is_mirrored_again_from_its_kept_snapshot(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A tombstone hides a page; the raw snapshot stays, and the file returns with it."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    assert "1002" in stored_pages(chosen)
    run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), SECOND + timedelta(days=3))
    prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))


def test_a_gone_page_leaves_the_mirror_even_when_another_has_a_problem(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Problems elsewhere keep last good copies, but never a page known to be gone."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    broken = next((chosen.raw / "confluence" / "pages" / "1001").iterdir()) / "view.json"
    broken.write_text("{}", "utf-8")  # another document now unreadable
    outcome = prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)[
        "confluence"
    ]
    assert outcome.problems
    assert not list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))
    assert list((chosen.docs / "confluence" / "MFS").glob("1001-*.md"))


def test_a_corrupt_coverage_record_is_refused_by_the_command(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A record that cannot be read fails the fetch, naming it, rather than starting over."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("KB_MCP_SOURCES__CONFLUENCE__SITE", SITE)
    data = (home / "kb-mcp").resolve()
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "coverage.json").write_text("[{}]", "utf-8")
    options = [
        "fetch",
        "--yes",
        "--config",
        str(home / "none.toml"),
        "--space",
        "MFS",
    ]
    assert main(options) == FAILED
    assert "coverage.json[0]" in capsys.readouterr().err


def test_a_moved_page_takes_its_new_space_everywhere_and_leaves_the_old(tmp_path: Path) -> None:
    """The freshest listing wins: path, front matter, tree, and the old file goes."""
    store = RawStore(tmp_path / "raw", "confluence")
    docs = tmp_path / "docs"
    responses = {
        "document.json": v2_page(),
        "view.json": v2_page(body={"view": {"value": "<p>v</p>", "representation": "view"}}),
        "attachments.json": [],
    }
    with store.writing():
        store.put(Page, responses, FIRST, {})
        store.put_space(v2_space(), [v2_page()], [], [], listed_at=FIRST)
    prepared_sources(store, docs, SITE, identity)
    assert list((docs / "confluence" / "MFS").glob("196845-*.md"))
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [v2_page(spaceId=OTHER_SPACE)], [], [], listed_at=SECOND)
    prepared_sources(store, docs, SITE, identity)
    [moved] = (docs / "confluence").rglob("196845-*.md")
    assert moved.parent.name == "OPS"
    assert "scope: space:OPS" in moved.read_text("utf-8")
    assert moved.name in (docs / "confluence" / "OPS" / "_tree.md").read_text("utf-8")


def test_a_damaged_listing_time_is_one_problem_not_one_per_document(tmp_path: Path) -> None:
    """The time a space was listed is read once a run, and a damaged record named once."""
    store = RawStore(tmp_path / "raw", "confluence")
    with store.writing():
        for page_id in ("1001", "1002"):
            view = {"view": {"value": "<p>v</p>", "representation": "view"}}
            responses = {
                "document.json": v2_page(id=page_id),
                "view.json": v2_page(id=page_id, body=view),
                "attachments.json": [],
            }
            store.put(Page, responses, FIRST, {})
        listing = [v2_page(id="1001"), v2_page(id="1002")]
        store.put_space(v2_space(), listing, [], [], listed_at=FIRST)
    (store.root / "confluence" / "spaces" / SPACE / "listed_at.json").write_text("{}", "utf-8")
    outcome = prepared_sources(store, tmp_path / "docs", SITE, identity)["confluence"]
    named = [problem.where for problem in outcome.problems if "listed_at" in problem.where]
    assert named == [f"confluence/spaces/{SPACE}/listed_at.json"]


def test_a_page_whose_probe_failed_is_probed_again_on_a_later_run(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A probe answering 500 leaves the page pending; later runs probe it, and confirm."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    failing = RefreshSite(listing=without("1002"), html_page=None, gone=set())
    failing.pages_fail = True  # every page GET answers 503: no answer to the probe
    monkeypatch.setattr(http, "client", lambda *_: failing.client())
    outcome = run_fetch(chosen, catch_up(["MFS"], []), lambda: SECOND, lambda _: None)
    assert Problem(where="confluence pages 1002", reason="status 503") in outcome.problems
    [pending] = RawStore(chosen.raw, "confluence").tombstones().values()
    assert (pending.key, pending.first_gone, pending.confirmed) == (
        ("confluence", "page", "1002"),
        None,
        False,
    )
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    [stone] = RawStore(chosen.raw, "confluence").tombstones().values()
    assert stone.confirmed


def test_a_moved_page_whose_new_file_fails_keeps_its_old_file(tmp_path: Path) -> None:
    """The last good copy of a moved page stays until its new file is built."""
    store = RawStore(tmp_path / "raw", "confluence")
    docs = tmp_path / "docs"
    responses = {
        "document.json": v2_page(),
        "view.json": v2_page(body={"view": {"value": "<p>v</p>", "representation": "view"}}),
        "attachments.json": [],
    }
    with store.writing():
        store.put(Page, responses, FIRST, {})
        store.put_space(v2_space(), [v2_page()], [], [], listed_at=FIRST)
    prepared_sources(store, docs, SITE, identity)
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [v2_page(spaceId=OTHER_SPACE)], [], [], listed_at=SECOND)

    def failing(html: str) -> str:
        if "<p>v</p>" in html:
            message = "pandoc failed"
            raise PandocFailedError(message)
        return html

    outcome = prepared_sources(store, docs, SITE, failing)["confluence"]
    assert outcome.problems
    assert list((docs / "confluence" / "MFS").glob("196845-*.md"))


def test_a_window_never_ends_past_the_run() -> None:
    """An --until in the future stops at now: coverage never claims time not yet seen."""
    later = Purview(
        scopes=scopes(["MFS"], []), max_file_bytes=CAP, since=FIRST - WEEK, until=FIRST + WEEK
    )
    window = later.windows(Coverage(), FIRST)[MFS]
    assert window is not None
    assert window.period.end == FIRST


def test_a_deleted_page_whose_listing_entry_changed_is_still_tracked(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The last listing is read by id alone: an entry without its title still counts."""
    chosen = settings(tmp_path)
    titleless = {
        key: {k: v for k, v in page.items() if k != "title"} for key, page in PAGES.items()
    }
    run(chosen, monkeypatch, RefreshSite(listing=titleless), first_week(["MFS"], []), FIRST)
    assert "1002" in RawStore(chosen.raw, "confluence").stored_ids(Page)
    rest = {key: page for key, page in titleless.items() if key != "1002"}
    for day in (1, 2):
        gone = RefreshSite(listing=rest, gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    [stone] = RawStore(chosen.raw, "confluence").tombstones().values()
    assert (stone.key, stone.confirmed) == (("confluence", "page", "1002"), True)


def test_a_stale_listing_never_brings_back_a_page_confirmed_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A space listed long before the page answered gone cannot revive it."""
    chosen = settings(tmp_path)
    store = RawStore(chosen.raw, "confluence")
    with store.writing():
        stale = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        entry = {**PAGES["1002"], "spaceId": OTHER_SPACE}
        store.put_space(stale, [entry], [], [], listed_at=FIRST - timedelta(days=30))
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    prepared_sources(store, chosen.docs, SITE, identity)
    assert list(chosen.docs.rglob("1002-*.md")) == []


def test_a_since_before_the_epoch_starts_at_the_epoch() -> None:
    """Nothing on the site is older; the dates searched stay within the calendar."""
    early = Purview(
        scopes=scopes(["MFS"], []), max_file_bytes=CAP, since=datetime(1, 1, 2, tzinfo=UTC)
    )
    window = early.windows(Coverage(), FIRST)[MFS]
    assert window is not None
    assert window.period.start == EPOCH


# Plan 034: a project's coverage ends exactly, at its earliest document not stored whole.
START = datetime(2026, 10, 21, 12, tzinfo=UTC)
RUN = datetime(2026, 10, 28, 12, tzinfo=UTC)
NEXT = RUN + timedelta(hours=6)
FAILING = datetime(2026, 10, 26, 9, tzinfo=UTC)
FINE = datetime(2026, 10, 27, 9, tzinfo=UTC)
# The path of the file that each issue of the scripted site keeps.
ISSUE_FILE = "/rest/api/3/attachment/content/10000"


def issue_at(issue_id: str, updated: datetime, *, files: bool = True) -> dict[str, object]:
    """Return an issue of PRB updated at a moment, as its search entry and its GET give it."""
    values = ISSUE["fields"]
    assert isinstance(values, dict)
    changed = {"updated": updated.isoformat(), **({} if files else {"attachment": []})}
    return {**ISSUE, "id": issue_id, "key": f"PRB-{issue_id}", "fields": {**values, **changed}}


def two_issues() -> dict[str, dict[str, object]]:
    """Return the issue that tests make fail, and a later one, without files, that never fails."""
    return {"20001": issue_at("20001", FAILING), "20002": issue_at("20002", FINE, files=False)}


def exactly(start: datetime, end: datetime, read_whole: datetime = RUN) -> Coverage:
    """Return PRB covered exactly from ``start`` to ``end``, as of its end.

    And read whole at ``read_whole``: its first fetch, by default at ``RUN``.
    """
    return Coverage(
        periods={PRB: Period(start, end)},
        exact=frozenset({PRB}),
        as_of={PRB: end},
        whole_read_at={PRB: read_whole},
    )


def said_coverage(events: list[dict[str, object]]) -> list[tuple[object, ...]]:
    """Give what ``fetch.coverage`` said, scope by scope: the outcome, and why if held."""
    return [
        (event["scope"], event["outcome"], *([event["reason"]] if "reason" in event else []))
        for event in events
        if event["event"] == "fetch.coverage"
    ]


@pytest.mark.parametrize(
    "failing",
    [
        RefreshSite(issues=two_issues(), failing_issues={"20001": 500}),
        RefreshSite(issues=two_issues(), unread_issues={"20001"}),
        RefreshSite(issues=two_issues(), media_fails=True),
    ],
    ids=["fetch failed", "snapshot refused", "file failed"],
)
def test_a_failure_ends_a_project_s_coverage_at_its_update_time(
    failing: RefreshSite, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Not stored whole: the coverage ends at its update time, exact, and is said capped."""
    chosen = settings(tmp_path)
    with capture_logs() as events:
        run(
            chosen,
            monkeypatch,
            failing,
            Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
            RUN,
        )
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, FAILING)
    assert said_coverage(events) == [("project PRB", "capped")]


def stored_issue(chosen: Settings, issue_id: str) -> Path:
    """Return the response of an issue's one stored snapshot, as the store keeps it."""
    [revision] = (chosen.raw / "jira" / "issues" / issue_id).iterdir()
    return revision / "issue.json"


def test_a_stored_snapshot_that_cannot_be_read_ends_the_coverage_at_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Stored already, it is read for its files: unreadable, it is not stored whole."""
    chosen = settings(tmp_path)
    whole = RefreshSite(issues=two_issues())
    run(
        chosen,
        monkeypatch,
        whole,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    stored_issue(chosen, "20001").write_text("{}", "utf-8")
    again = Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START)
    with capture_logs() as events:
        run(chosen, monkeypatch, RefreshSite(issues=two_issues()), again, NEXT)
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, FAILING)
    assert said_coverage(events) == [("project PRB", "capped")]


@pytest.mark.parametrize(
    ("failing", "asked_again"),
    [
        (
            RefreshSite(issues=two_issues(), failing_issues={"20001": 500}),
            "/rest/api/3/issue/20001",
        ),
        (RefreshSite(issues=two_issues(), media_fails=True), ISSUE_FILE),
    ],
    ids=["fetch failed", "file failed"],
)
def test_what_failed_is_asked_for_again_and_the_coverage_then_reaches_the_run(
    failing: RefreshSite, asked_again: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The next run without --since asks for it again, and covers up to its own start."""
    chosen = settings(tmp_path)
    run(
        chosen,
        monkeypatch,
        failing,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    again = RefreshSite(issues=two_issues())
    with capture_logs() as events:
        run(chosen, monkeypatch, again, catch_up([], ["PRB"]), NEXT)
    assert asked_again in [url.path for url in again.asked]
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, NEXT)
    assert said_coverage(events) == [("project PRB", "extended")]


def test_a_snapshot_refused_holds_the_coverage_until_the_adapter_reads_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Stored raw, it is asked for again on each run, and stops the coverage until it reads.

    Its stored response, made whole, stands for an adapter fixed to read it; the next run
    then downloads the file that it lacked, and covers up to its own start.
    """
    chosen = settings(tmp_path)
    refused = RefreshSite(issues=two_issues(), unread_issues={"20001"})
    run(
        chosen,
        monkeypatch,
        refused,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), catch_up([], ["PRB"]), NEXT)
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, FAILING)
    stored_issue(chosen, "20001").write_text(json.dumps(issue_at("20001", FAILING)), "utf-8")
    again = RefreshSite(issues=two_issues())
    later = NEXT + timedelta(hours=6)
    run(chosen, monkeypatch, again, catch_up([], ["PRB"]), later)
    assert ISSUE_FILE in [url.path for url in again.asked]
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, later)


def test_among_several_failures_the_earliest_ends_the_coverage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Two issues fail, a day apart: the coverage ends at the earlier, so both are asked again."""
    chosen = settings(tmp_path)
    earlier = FAILING - timedelta(days=1)
    issues = {**two_issues(), "20003": issue_at("20003", earlier)}
    failing = RefreshSite(issues=issues, failing_issues={"20001": 500, "20003": 500})
    run(
        chosen,
        monkeypatch,
        failing,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, earlier)


def test_a_search_entry_that_the_adapter_refuses_holds_the_coverage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Without its update time, it has no moment to stop at: the coverage stays, said held."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), first_week([], ["PRB"]), FIRST)
    before = RawStore(chosen.raw, "confluence").coverage()
    timeless = issue_at("20004", FINE)
    values = timeless["fields"]
    assert isinstance(values, dict)
    timeless["fields"] = {key: value for key, value in values.items() if key != "updated"}
    refused = RefreshSite(issues={**two_issues(), "20004": timeless})
    with capture_logs() as events:
        run(chosen, monkeypatch, refused, catch_up([], ["PRB"]), RUN)
    assert RawStore(chosen.raw, "confluence").coverage() == before
    assert said_coverage(events) == [("project PRB", "held", "entries refused")]


@pytest.mark.parametrize(("status", "stopped"), [(503, "failed"), (401, "sign in again")])
def test_a_run_stopped_during_a_project_leaves_its_coverage_and_extends_those_before(
    status: int, stopped: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Failures in a row, or a sign-in lost, during PRB's fetch: MFS, fetched first, grows.

    PRB's coverage stays as it was.
    """
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), first_week(["MFS"], []), FIRST)
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), first_week([], ["PRB"]), FIRST)
    before = RawStore(chosen.raw, "confluence").coverage().periods[PRB]
    many = {str(30000 + n): issue_at(str(30000 + n), RUN - timedelta(hours=1)) for n in range(MANY)}
    failing = RefreshSite(issues=many, failing_issues=dict.fromkeys(many, status))
    assert run(chosen, monkeypatch, failing, catch_up(["MFS"], []), RUN) == "done"
    assert run(chosen, monkeypatch, failing, catch_up([], ["PRB"]), RUN) == stopped
    periods = RawStore(chosen.raw, "confluence").coverage().periods
    assert periods[PRB] == before
    assert periods[MFS] == Period(FIRST - WEEK, RUN)


def test_an_entry_from_before_034_is_replaced_by_a_catch_up_and_capped(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Written without exact: a run without --since sees it whole, and ends it at a failure.

    The next run asks for the failed issue again, and covers up to its own start.
    """
    chosen = settings(tmp_path)
    chosen.raw.mkdir(parents=True)
    old = [{"source": "jira", "key": "PRB", "start": START.isoformat(), "end": RUN.isoformat()}]
    (chosen.raw / "coverage.json").write_text(json.dumps(old), "utf-8")
    windows = catch_up([], ["PRB"]).windows(RawStore(chosen.raw, "confluence").coverage(), NEXT)
    assert windows == {PRB: FetchWindow(period=Period(START, NEXT), reason="covered start")}
    failing = RefreshSite(issues=two_issues(), failing_issues={"20001": 500})
    run(chosen, monkeypatch, failing, catch_up([], ["PRB"]), NEXT)
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, FAILING, NEXT)
    again = RefreshSite(issues=two_issues())
    later = NEXT + timedelta(hours=6)
    run(chosen, monkeypatch, again, catch_up([], ["PRB"]), later)
    assert "/rest/api/3/issue/20001" in [url.path for url in again.asked]
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, later, NEXT)


def test_an_entry_from_before_034_met_by_a_later_since_stays_inexact(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--since after its start joins it as before, whatever failed: no failure is blessed."""
    chosen = settings(tmp_path)
    chosen.raw.mkdir(parents=True)
    old = [{"source": "jira", "key": "PRB", "start": START.isoformat(), "end": RUN.isoformat()}]
    (chosen.raw / "coverage.json").write_text(json.dumps(old), "utf-8")
    failing = RefreshSite(issues=two_issues(), failing_issues={"20001": 500})
    inside = Purview(
        scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=FAILING - timedelta(hours=1)
    )
    run(chosen, monkeypatch, failing, inside, NEXT)
    after = RawStore(chosen.raw, "confluence").coverage()
    assert after == Coverage(periods={PRB: Period(START, NEXT)}, whole_read_at={PRB: NEXT})
    later = NEXT + timedelta(hours=6)
    assert catch_up([], ["PRB"]).windows(after, later) == {
        PRB: FetchWindow(period=Period(START, later), reason="covered start")
    }


# Plan 034: each target starts where its fetch should.
LAST_FETCH = datetime(2026, 10, 27, 9, tzinfo=UTC)
CATCH_UP = datetime(2026, 10, 28, 12, tzinfo=UTC)


def jira_asked(fake: FakeSite) -> list[str]:
    """Give the paths of the issues that a run asked for, in order."""
    return [url.path for url in fake.asked if url.path.startswith("/rest/api/3/issue/")]


def test_a_project_catches_up_from_a_day_before_its_last_fetch(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Covered exactly to 27 October 09:00, a run on the 28th at noon searches from the 24th.

    A day, then JQL's two. It asks for the issues updated from the 26th at 09:00 that are
    not stored: not one updated a minute before, nor one stored already. The coverage
    then reaches the run's start, exact.
    """
    chosen = settings(tmp_path)
    stored = issue_at("20010", LAST_FETCH - timedelta(hours=1), files=False)
    first = RefreshSite(issues={"20010": stored})
    run(
        chosen,
        monkeypatch,
        first,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        LAST_FETCH,
    )
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, LAST_FETCH, LAST_FETCH)
    issues = {
        "20010": stored,
        "20011": issue_at("20011", datetime(2026, 10, 26, 9, tzinfo=UTC), files=False),
        "20012": issue_at("20012", datetime(2026, 10, 26, 8, 59, tzinfo=UTC), files=False),
        "20013": issue_at("20013", CATCH_UP - timedelta(hours=2), files=False),
    }
    later = RefreshSite(issues=issues)
    run(chosen, monkeypatch, later, catch_up([], ["PRB"]), CATCH_UP)
    [search] = [url for url in later.asked if url.path == "/rest/api/3/search/jql"]
    assert 'updated >= "2026-10-24"' in search.params["jql"]
    fetched = {path for path in jira_asked(later) if not path.endswith("/comment")}
    assert fetched == {"/rest/api/3/issue/20011", "/rest/api/3/issue/20013"}
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, CATCH_UP, LAST_FETCH)


def test_a_catch_up_until_a_moment_reaches_that_moment(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--until 06:00 on the 28th: the coverage reaches 06:00, and an issue of 10:00 waits."""
    chosen = settings(tmp_path)
    first = RefreshSite(issues={})
    run(
        chosen,
        monkeypatch,
        first,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        LAST_FETCH,
    )
    until = datetime(2026, 10, 28, 6, tzinfo=UTC)
    issues = {"20013": issue_at("20013", CATCH_UP - timedelta(hours=2), files=False)}
    later = RefreshSite(issues=issues)
    run(
        chosen,
        monkeypatch,
        later,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, until=until),
        CATCH_UP,
    )
    assert jira_asked(later) == []
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, until, LAST_FETCH)


def test_a_failure_at_the_start_of_a_catch_up_ends_the_coverage_there(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """At a day before the covered end: the coverage ends there, and the next run asks again."""
    chosen = settings(tmp_path)
    run(
        chosen,
        monkeypatch,
        RefreshSite(issues={}),
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    start_of_catch_up = RUN - timedelta(days=1)
    issues = {"20020": issue_at("20020", start_of_catch_up)}
    failing = RefreshSite(issues=issues, failing_issues={"20020": 500})
    run(chosen, monkeypatch, failing, catch_up([], ["PRB"]), NEXT)
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, start_of_catch_up)
    again = RefreshSite(issues=issues)
    later = NEXT + timedelta(hours=6)
    run(chosen, monkeypatch, again, catch_up([], ["PRB"]), later)
    assert "/rest/api/3/issue/20020" in jira_asked(again)
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, later)


def test_a_space_catches_up_over_its_covered_period_by_version(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A page moved in with a version older than the last fetch comes; no stored one is asked.

    The listing is read whole anyway: a look at the store tells what it lacks.
    """
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    moved_in = v2_page(id="1004", title="Moved in", version=stamp(18))
    later = RefreshSite(listing={**PAGES, "1004": moved_in})
    run(chosen, monkeypatch, later, catch_up(["MFS"], []), SECOND)
    pages = {url.path for url in later.asked if url.path.startswith("/wiki/api/v2/pages/")}
    assert pages == {"/wiki/api/v2/pages/1004", "/wiki/api/v2/pages/1004/attachments"}
    assert "1004" in stored_pages(chosen)


def test_a_target_never_fetched_fetches_its_last_week_while_the_others_catch_up(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A space added to the settings no longer refuses the run: it covers the week before."""
    chosen = settings(tmp_path)
    run(
        chosen,
        monkeypatch,
        RefreshSite(issues={}),
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    targets = catch_up(["MFS"], ["PRB"])
    assert targets.windows(RawStore(chosen.raw, "confluence").coverage(), NEXT) == {
        MFS: FetchWindow(period=Period(NEXT - WEEK, NEXT), reason="first fetch"),
        PRB: FetchWindow(
            period=Period(RUN - timedelta(days=1), NEXT), reason="since the last fetch"
        ),
    }
    assert run(chosen, monkeypatch, RefreshSite(issues={}), catch_up(["MFS"], []), NEXT) == "done"
    assert run(chosen, monkeypatch, RefreshSite(issues={}), catch_up([], ["PRB"]), NEXT) == "done"
    assert RawStore(chosen.raw, "confluence").coverage().periods == {
        MFS: Period(NEXT - WEEK, NEXT),
        PRB: Period(START, NEXT),
    }


def test_a_target_whose_catch_up_starts_after_until_is_skipped_and_asked_nothing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """PRB covered to the run before, --until earlier still: held, no search; MFS runs."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    run(
        chosen,
        monkeypatch,
        RefreshSite(issues={}),
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    before = RawStore(chosen.raw, "confluence").coverage().periods[PRB]
    until = RUN - timedelta(days=1)
    fake = RefreshSite(issues=two_issues())
    with capture_logs() as events:
        space = Purview(scopes=scopes(["MFS"], []), max_file_bytes=CAP, until=until)
        run(chosen, monkeypatch, fake, space, NEXT)
        project = Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, until=until)
        run(chosen, monkeypatch, fake, project, NEXT)
    assert not [url for url in fake.asked if url.path.startswith("/rest/api/3/search")]
    periods = RawStore(chosen.raw, "confluence").coverage().periods
    assert periods[PRB] == before
    assert periods[MFS] == Period(FIRST - WEEK, until)
    assert said_coverage(events) == [
        ("space MFS", "extended"),
        ("project PRB", "held", "after --until"),
    ]


def test_a_kept_file_that_fails_again_keeps_the_coverage_at_its_issue(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Stored without its file, the issue is completed by the next run: failing again, capped."""
    chosen = settings(tmp_path)
    failing = RefreshSite(issues=two_issues(), media_fails=True)
    run(
        chosen,
        monkeypatch,
        failing,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    again = RefreshSite(issues=two_issues(), media_fails=True)
    with capture_logs() as events:
        run(chosen, monkeypatch, again, catch_up([], ["PRB"]), NEXT)
    assert ISSUE_FILE in [url.path for url in again.asked]
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, FAILING)
    assert said_coverage(events) == [("project PRB", "capped")]


def test_a_space_whose_catch_up_starts_after_until_is_skipped_and_said_so(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No listing, the coverage as it was; the summary and the JSON say why, without a window."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    before = RawStore(chosen.raw, "confluence").coverage()
    fake = RefreshSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    early = Purview(scopes=scopes(["MFS"], []), max_file_bytes=CAP, until=FIRST - WEEK)
    outcome = run_fetch(chosen, early, lambda: SECOND, lambda _: None)
    assert not [url for url in fake.asked if url.path.startswith("/wiki/api/v2/spaces")]
    assert RawStore(chosen.raw, "confluence").coverage() == before
    detailed = outcome.counts.text("detailed")
    assert "space MFS: skipped, after --until; coverage held\n" in detailed
    [window] = to_jsonable_python(outcome)["counts"]["windows"]
    assert (window["start"], window["end"], window["reason"], window["coverage"]) == (
        None,
        None,
        "after --until",
        "held",
    )


def test_a_run_apart_from_what_is_covered_leaves_it_and_says_why(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--since a day after the covered end: joining would claim that day, so it is held."""
    chosen = settings(tmp_path)
    run(
        chosen,
        monkeypatch,
        RefreshSite(issues={}),
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        RUN,
    )
    apart = Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=RUN + timedelta(days=1))
    with capture_logs() as events:
        run(chosen, monkeypatch, RefreshSite(issues={}), apart, RUN + timedelta(days=2))
    assert RawStore(chosen.raw, "confluence").coverage() == exactly(START, RUN)
    assert said_coverage(events) == [("project PRB", "held", "apart from what is covered")]


def test_a_coverage_record_of_pre_kb_mcp_is_written_anew_by_the_next_fetch(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Plan 056: read as the tag wrote it, it is written with each scope's type, periods kept.

    The fetch, of the project apart from its covered period, holds every period as it was,
    Confluence's too, which it did not fetch; it reads the project whole, plan 061's.
    """
    chosen = settings(tmp_path)
    chosen.raw.mkdir(parents=True)
    period = {"start": START.isoformat(), "end": RUN.isoformat()}
    former = [
        {"source": "confluence", "key": "MFS", **period},
        {"source": "jira", "key": "PRB", **period, "exact": True},
    ]
    (chosen.raw / "coverage.json").write_text(json.dumps(former), "utf-8")
    apart = Purview(scopes=[PRB], max_file_bytes=CAP, since=RUN + timedelta(days=1))
    run(chosen, monkeypatch, RefreshSite(issues={}), apart, RUN + timedelta(days=2))
    written = json.loads((chosen.raw / "coverage.json").read_text("utf-8"))
    assert written == [
        {"source": "confluence", "type": "space", "key": "MFS", **period},
        {
            "source": "jira",
            "type": "project",
            "key": "PRB",
            **period,
            "exact": True,
            "whole_read_at": (RUN + timedelta(days=2)).isoformat(),
        },
    ]


def test_an_issue_that_the_search_names_twice_is_fetched_once(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An issue saved while its search pages through shifts another into the next page."""
    chosen = settings(tmp_path)
    twice = RefreshSite(issues={"20002": issue_at("20002", FINE, files=False)})
    entries = [*twice.issues.values()] * 2
    search = {"/rest/api/3/search/jql": lambda _: httpx.Response(200, json={"issues": entries})}
    monkeypatch.setattr(twice, "changes", lambda: search)
    with capture_logs() as events:
        run(
            chosen,
            monkeypatch,
            twice,
            Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
            RUN,
        )
    assert jira_asked(twice).count("/rest/api/3/issue/20002") == 1
    tasks = [(each["done"], each["total"]) for each in events if each.get("task") == "documents"]
    assert tasks[-1] == (1, 1)


def test_a_dry_run_counts_once_an_issue_that_the_search_names_twice(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Its files too: the counts of a plan are those of the run it plans."""
    chosen = settings(tmp_path)
    twice = RefreshSite(issues={"20002": issue_at("20002", FINE)})
    entries = [*twice.issues.values()] * 2
    search = {"/rest/api/3/search/jql": lambda _: httpx.Response(200, json={"issues": entries})}
    monkeypatch.setattr(twice, "changes", lambda: search)
    monkeypatch.setattr(http, "client", lambda *_: twice.client())
    planned = plan_fetch(
        chosen,
        Purview(scopes=scopes([], ["PRB"]), max_file_bytes=CAP, since=START),
        lambda: RUN,
        lambda _: None,
    )
    assert planned.counts.counts["jira issues: to fetch"] == 1
    assert planned.counts.counts["files: to download"] == 1


# Plan 061: a project read whole, as a space is listed, starts its issues' absences.
WHOLE_READ = 'project = "PRB" ORDER BY key'
CLIENT_SITE = "https://client.example.invalid"


def whole_reads(fake: FakeSite) -> list[bool]:
    """Say of each search that a run asked, in order, whether it read the project whole."""
    asked = [url for url in fake.asked if url.path == "/rest/api/3/search/jql"]
    return [url.params["jql"] == WHOLE_READ for url in asked]


def test_a_project_is_searched_alone_within_its_interval_and_read_whole_past_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Criterion 2: its first fetch, and one a week after, read it whole first.

    A fetch between searches it by update time alone, and leaves the time of its last
    whole read as it was.
    """
    chosen = settings(tmp_path)
    first, within, past = RefreshSite(), RefreshSite(), RefreshSite()
    run(chosen, monkeypatch, first, first_week([], ["PRB"]), FIRST)
    run(chosen, monkeypatch, within, catch_up([], ["PRB"]), FIRST + WEEK - timedelta(minutes=1))
    assert RawStore(chosen.raw, "jira").coverage().whole_read_at == {PRB: FIRST}
    run(chosen, monkeypatch, past, catch_up([], ["PRB"]), FIRST + WEEK)
    assert (whole_reads(first), whole_reads(within), whole_reads(past)) == (
        [True, False],
        [False],
        [True, False],
    )
    assert RawStore(chosen.raw, "jira").coverage().whole_read_at == {PRB: FIRST + WEEK}


def test_an_issue_absent_from_a_whole_read_is_probed_at_each_run_until_confirmed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Gone at its first 404; a second within the hour confirms nothing, one past it does.

    The runs after the whole read that found it absent search by update time alone, and
    still probe it.
    """
    chosen = settings(tmp_path)
    kept = issue_at("20001", FIRST - timedelta(days=1), files=False)
    both = {"20001": kept, "20002": issue_at("20002", FIRST - timedelta(days=2), files=False)}
    run(chosen, monkeypatch, RefreshSite(issues=both), first_week([], ["PRB"]), FIRST)
    assert RawStore(chosen.raw, "jira").tombstones() == {}
    absent = FIRST + WEEK
    for moment in (absent, absent + CONFIRM_AFTER - timedelta(minutes=1)):
        run(chosen, monkeypatch, RefreshSite(issues={"20001": kept}), catch_up([], ["PRB"]), moment)
        [stone] = RawStore(chosen.raw, "jira").tombstones().values()
        assert (stone.key, stone.first_gone, stone.confirmed) == (
            ("jira", "issue", "20002"),
            absent,
            False,
        )
    later = RefreshSite(issues={"20001": kept})
    run(chosen, monkeypatch, later, catch_up([], ["PRB"]), absent + CONFIRM_AFTER)
    assert whole_reads(later) == [False]
    assert "/rest/api/3/issue/20002" in jira_asked(later)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert stone.confirmed


def test_an_issue_missing_from_a_whole_read_is_confirmed_gone_then_leaves_the_mirror(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Criterion 1: absent, probed gone at its first 404, confirmed gone past CONFIRM_AFTER.

    Prepare keeps its file while it is only probed gone, and removes it once confirmed;
    the issue that its project still holds keeps its own.
    """
    chosen = settings(tmp_path)
    kept = issue_at("20001", FIRST - timedelta(days=1), files=False)
    both = {"20001": kept, "20002": issue_at("20002", FIRST - timedelta(days=2), files=False)}
    project = chosen.docs / "jira" / "PRB"

    def mirrored() -> list[str]:
        prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
        return sorted(path.name for path in project.glob("*.md"))

    run(chosen, monkeypatch, RefreshSite(issues=both), first_week([], ["PRB"]), FIRST)
    assert mirrored() == ["PRB-20001.md", "PRB-20002.md"]
    absent = FIRST + WEEK
    run(chosen, monkeypatch, RefreshSite(issues={"20001": kept}), catch_up([], ["PRB"]), absent)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.key, stone.first_gone, stone.confirmed) == (
        ("jira", "issue", "20002"),
        absent,
        False,
    )
    assert mirrored() == ["PRB-20001.md", "PRB-20002.md"]
    later = absent + CONFIRM_AFTER
    run(chosen, monkeypatch, RefreshSite(issues={"20001": kept}), catch_up([], ["PRB"]), later)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert stone.confirmed
    assert mirrored() == ["PRB-20001.md"]


def test_an_issue_that_a_search_stored_since_the_last_whole_read_is_found_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: the whole read is compared with every issue of the project stored.

    The baseline names 20001; a day later the search by update time stores the new 20003,
    which is then deleted. The next whole read, a week after the baseline, finds it
    absent and gone; a run past CONFIRM_AFTER confirms it, and prepare removes its file.
    """
    chosen = settings(tmp_path)
    kept = issue_at("20001", FIRST - timedelta(days=1), files=False)
    project = chosen.docs / "jira" / "PRB"

    def mirrored() -> list[str]:
        prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
        return sorted(path.name for path in project.glob("*.md"))

    run(chosen, monkeypatch, RefreshSite(issues={"20001": kept}), first_week([], ["PRB"]), FIRST)
    new = issue_at("20003", FIRST + timedelta(hours=12), files=False)
    both = RefreshSite(issues={"20001": kept, "20003": new})
    run(chosen, monkeypatch, both, catch_up([], ["PRB"]), FIRST + timedelta(days=1))
    assert mirrored() == ["PRB-20001.md", "PRB-20003.md"]
    for moment in (FIRST + WEEK, FIRST + WEEK + CONFIRM_AFTER):
        run(chosen, monkeypatch, RefreshSite(issues={"20001": kept}), catch_up([], ["PRB"]), moment)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.key, stone.first_gone, stone.confirmed) == (
        ("jira", "issue", "20003"),
        FIRST + WEEK,
        True,
    )
    assert mirrored() == ["PRB-20001.md"]


def test_an_issue_listed_again_by_a_whole_read_loses_its_tombstone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Hidden from the sign-in for a while, it answered 404; read whole again, it is present."""
    chosen = settings(tmp_path)
    issue = {"20002": issue_at("20002", FIRST - timedelta(days=2), files=False)}
    run(chosen, monkeypatch, RefreshSite(issues=issue), first_week([], ["PRB"]), FIRST)
    run(chosen, monkeypatch, RefreshSite(issues={}), catch_up([], ["PRB"]), FIRST + WEEK)
    assert list(RawStore(chosen.raw, "jira").tombstones()) == [("jira", "issue", "20002")]
    run(chosen, monkeypatch, RefreshSite(issues=issue), catch_up([], ["PRB"]), FIRST + 2 * WEEK)
    assert RawStore(chosen.raw, "jira").tombstones() == {}


def in_project(issue_id: str, project: str) -> dict[str, object]:
    """Return an issue of another project, as its search entry and its GET give it."""
    issue = issue_at(issue_id, FIRST - timedelta(days=2), files=False)
    values = issue["fields"]
    assert isinstance(values, dict)
    project_of = {"id": "10100", "key": project}
    return {**issue, "key": f"{project}-1", "fields": {**values, "project": project_of}}


@pytest.mark.parametrize(
    ("keeper", "answer"),
    [("otherjira", "moved"), ("clientjira", "gone")],
    ids=["a source of the same site", "a source of another site"],
)
def test_an_issue_moved_to_a_project_is_followed_only_where_a_source_of_its_site_keeps_it(
    tmp_path: Path, monkeypatch: MonkeyPatch, keeper: str, answer: str
) -> None:
    """Revised at 059's merge: each source probes its own site; a project of another's is none.

    Two Jira sources of two sites read a project of one key, OPS: the issue absent from
    PRB, found in OPS on its site, has moved when a source of its site reads OPS whole
    and names it, and is gone when only the other site's source does, whose OPS is
    another project.
    """
    model = model_of(
        (
            *SOURCES,
            Source(name="otherjira", connector=JIRA),
            Source(name="clientjira", connector=JIRA),
        )
    )
    tables = {"jira": {"site": SITE}, "otherjira": {"connector": "jira", "site": SITE}}
    tables["clientjira"] = {"connector": "jira", "site": CLIENT_SITE}
    chosen = model(sources=tables, data_dir=tmp_path / "data")
    for site in (SITE, CLIENT_SITE):
        cookie = [{"name": "s", "value": "v", "domain": "x"}]
        write_cookies(folder_of(chosen.session, site) / COOKIES, cookie)
    moved = in_project("20002", "OPS")
    ours = RefreshSite(issues={"20002": issue_at("20002", FIRST - timedelta(days=2))})
    sites = {SITE: ours, CLIENT_SITE: RefreshSite(issues={"20002": moved})}
    monkeypatch.setattr(http, "client", lambda site, *_: sites[site].client())

    def fetched(source: str, key: str, now: datetime) -> None:
        scope = Scope(source=source, type=names.PROJECT, key=key)
        purview = Purview(scopes=[scope], max_file_bytes=CAP, since=FIRST - WEEK)
        assert run_fetch(chosen, purview, lambda: now, lambda _: None).ending == "done"

    fetched("jira", "PRB", FIRST)
    if keeper == "otherjira":
        sites[SITE] = RefreshSite(issues={"20002": moved})
    fetched(keeper, "OPS", FIRST)
    after = RefreshSite(issues={}, moved_issues={"20002": "OPS"})
    sites[SITE] = after
    fetched("jira", "PRB", FIRST + WEEK)
    assert "/rest/api/3/issue/20002" in jira_asked(after)
    stones = RawStore(chosen.raw, "jira").tombstones()
    gone = {key: stone.first_gone for key, stone in stones.items()}
    expected = {} if answer == "moved" else {("jira", "issue", "20002"): FIRST + WEEK}
    assert gone == expected


@dataclass
class ProjectSite(RefreshSite):
    """The scripted site whose searches answer by project: ``projects`` holds each one's issues.

    An issue of any project answers its GET, and any other 404, as deleted. With
    ``searches_fail``, a search by update time answers 400, and a whole read still answers;
    with ``whole_reads_fail``, the other way round. The site user that Jira signs in is
    nobody after ``myself_after`` asks.
    """

    projects: dict[str, dict[str, dict[str, object]]] = field(default_factory=dict)
    searches_fail: bool = False
    whole_reads_fail: bool = False
    myself_after: int | None = None
    myself_asks: int = 0

    def __post_init__(self) -> None:
        """Serve every project's issues by id."""
        self.issues = {
            key: each for issues in self.projects.values() for key, each in issues.items()
        }

    def routes(self) -> dict[str, Callable[[httpx.Request], httpx.Response]]:
        """Serve the scripted site, each search with the issues of its project alone."""
        routes = super().routes()
        routes["/rest/api/3/search/jql"] = self.by_project
        routes["/rest/api/3/myself"] = self.myself
        return routes

    def myself(self, _: httpx.Request) -> httpx.Response:
        """Answer the signed-in site user, until the session is made to expire."""
        self.myself_asks += 1
        expired = self.myself_after is not None and self.myself_asks > self.myself_after
        return httpx.Response(200, json={} if expired else {"accountId": "account-1"})

    def by_project(self, request: httpx.Request) -> httpx.Response:
        """Answer a search, whole or by update time, with every issue of its project."""
        jql = request.url.params["jql"]
        if self.searches_fail if "updated" in jql else self.whole_reads_fail:
            return httpx.Response(400, json={"errorMessages": ["refused"]})
        key = jql.split('"')[1]
        issues = list(self.projects.get(key, {}).values())
        return httpx.Response(200, json={"issues": issues, "isLast": True})


def moved_then_deleted(chosen: Settings, monkeypatch: MonkeyPatch) -> ProjectSite:
    """Read OPS whole naming 20002; 20002 moves to PRB, read whole three days later; then deleted.

    Return the site once it is deleted.
    """
    ops = ProjectSite(projects={"OPS": {"20002": in_project("20002", "OPS")}})
    run(chosen, monkeypatch, ops, first_week([], ["OPS"]), FIRST)
    prb = ProjectSite(projects={"PRB": {"20002": in_project("20002", "PRB")}})
    run(chosen, monkeypatch, prb, first_week([], ["PRB"]), FIRST + timedelta(days=3))
    return ProjectSite(projects={"OPS": {}, "PRB": {}})


def test_a_whole_read_of_before_resets_no_absence_found_by_another_project_s(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: only this run's whole read counts as presence.

    OPS's whole read misses 20002, which answers gone; PRB, not due, whose whole read of
    before names it, neither ends its absence nor dates it again, and the next run, past
    CONFIRM_AFTER, confirms it.
    """
    chosen = settings(tmp_path)
    deleted = moved_then_deleted(chosen, monkeypatch)
    for moment in (FIRST + WEEK, FIRST + WEEK + 2 * CONFIRM_AFTER):
        run(chosen, monkeypatch, deleted, catch_up([], ["OPS", "PRB"]), moment)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.key, stone.first_gone, stone.confirmed) == (
        ("jira", "issue", "20002"),
        FIRST + WEEK,
        True,
    )


@pytest.mark.parametrize("order", [["OPS", "PRB"], ["PRB", "OPS"]], ids=["OPS first", "PRB first"])
def test_a_confirmed_tombstone_stays_confirmed_when_another_project_misses_it(
    tmp_path: Path, monkeypatch: MonkeyPatch, order: list[str]
) -> None:
    """Review of 061: 20002, confirmed gone from OPS, is missing from PRB's whole read too.

    PRB, due a week after its whole read named 20002, keeps the confirmed tombstone of
    OPS rather than starting one of its own, whichever of the two the run reads first,
    and prepare writes no file of it.
    """
    chosen = settings(tmp_path)
    deleted = moved_then_deleted(chosen, monkeypatch)
    for moment in (FIRST + WEEK, FIRST + WEEK + 2 * CONFIRM_AFTER):
        run(chosen, monkeypatch, deleted, catch_up([], ["OPS"]), moment)
    due = FIRST + timedelta(days=3) + WEEK
    run(chosen, monkeypatch, deleted, catch_up([], order), due)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.key, stone.scope.key, stone.first_gone, stone.confirmed) == (
        ("jira", "issue", "20002"),
        "OPS",
        FIRST + WEEK,
        True,
    )
    prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
    assert sorted((chosen.docs / "jira").glob("*/*.md")) == []


def test_a_whole_read_of_before_drops_no_confirmed_tombstone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: 20002, confirmed gone from OPS, stays out of the mirror.

    A later run of OPS and PRB, PRB not due and its whole read of before naming it, keeps
    it confirmed, and prepare writes no file of it.
    """
    chosen = settings(tmp_path)
    deleted = moved_then_deleted(chosen, monkeypatch)
    for moment in (FIRST + WEEK, FIRST + WEEK + 2 * CONFIRM_AFTER):
        run(chosen, monkeypatch, deleted, catch_up([], ["OPS"]), moment)
    run(
        chosen, monkeypatch, deleted, catch_up([], ["OPS", "PRB"]), FIRST + WEEK + timedelta(days=1)
    )
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.key, stone.first_gone, stone.confirmed) == (
        ("jira", "issue", "20002"),
        FIRST + WEEK,
        True,
    )
    prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
    assert sorted((chosen.docs / "jira").glob("*/*.md")) == []


def test_a_run_reads_the_stored_issues_and_the_scopes_kept_once(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: what the store holds is read once a run, not once a project or a probe.

    A run of OPS and PRB, both read whole, reads the ids of the issues stored once; the
    three issues that OPS's whole read misses, each found in PRB, read the scopes kept
    once by each view of the site, Jira's and Confluence's, and PRB's whole read once by
    each, beside Jira's reading it as what PRB held.
    """
    chosen = settings(tmp_path)
    three = {each: in_project(each, "OPS") for each in ("20001", "20002", "20003")}
    first = ProjectSite(projects={"OPS": three, "PRB": {}})
    run(chosen, monkeypatch, first, first_week([], ["OPS", "PRB"]), FIRST)
    moved = ProjectSite(projects={"OPS": {}, "PRB": {}}, moved_issues=dict.fromkeys(three, "PRB"))
    calls: Counter[tuple[object, ...]] = Counter()
    for name in ("stored_ids", "holders", "listed_ids"):
        read = getattr(RawStore, name)

        def counted(
            store: RawStore, *given: object, name: str = name, read: Callable[..., object] = read
        ) -> object:
            calls[(store.source, name, *given)] += 1
            return read(store, *given)

        monkeypatch.setattr(RawStore, name, counted)
    run(chosen, monkeypatch, moved, catch_up([], ["OPS", "PRB"]), FIRST + WEEK)
    assert sorted(jira_asked(moved)) == [f"/rest/api/3/issue/{each}" for each in sorted(three)]
    assert calls == {
        ("jira", "stored_ids", Issue): 1,
        ("jira", "listed_ids", "OPS", Issue): 1,
        ("jira", "listed_ids", "PRB", Issue): 2,
        ("jira", "holders", Issue): 1,
        ("confluence", "holders", Issue): 1,
        ("confluence", "listed_ids", "PRB", Issue): 1,
    }


def test_a_whole_read_is_kept_for_a_project_without_a_period_yet(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: a first run whose search fails still records its whole read.

    The project has no covered period, and the next run, within the interval, searches
    it by update time alone.
    """
    chosen = settings(tmp_path)
    issues = {"PRB": {"20001": issue_at("20001", FIRST - timedelta(days=1), files=False)}}
    failing = ProjectSite(projects=issues, searches_fail=True)
    run(chosen, monkeypatch, failing, first_week([], ["PRB"]), FIRST)
    coverage = RawStore(chosen.raw, "jira").coverage()
    assert (coverage.periods, coverage.whole_read_at) == ({}, {PRB: FIRST})
    later = ProjectSite(projects=issues)
    run(chosen, monkeypatch, later, catch_up([], ["PRB"]), FIRST + timedelta(hours=1))
    assert whole_reads(later) == [False]


def test_a_failed_whole_read_keeps_the_last_and_the_search_goes_on(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: a whole read refused is no listing; nothing it misses is absent.

    The search by update time still fetches what changed; the last whole read, and when
    it was made, stay, so that the next run reads the project whole again.
    """
    chosen = settings(tmp_path)
    old = {each: issue_at(each, FIRST - timedelta(days=1), files=False) for each in ("1", "2")}
    run(chosen, monkeypatch, ProjectSite(projects={"PRB": old}), first_week([], ["PRB"]), FIRST)
    new = {"3": issue_at("3", FIRST + WEEK - timedelta(hours=1), files=False)}
    failing = ProjectSite(projects={"PRB": new}, whole_reads_fail=True)
    assert run(chosen, monkeypatch, failing, catch_up([], ["PRB"]), FIRST + WEEK) == "failed"
    assert "/rest/api/3/issue/3" in jira_asked(failing)
    store = RawStore(chosen.raw, "jira")
    assert (store.listed_ids("PRB", Issue), store.tombstones()) == ({"1", "2"}, {})
    assert store.coverage().whole_read_at == {PRB: FIRST}
    again = ProjectSite(projects={"PRB": new})
    run(chosen, monkeypatch, again, catch_up([], ["PRB"]), FIRST + WEEK + timedelta(hours=1))
    assert whole_reads(again) == [True, False]


def gone_from_prb(chosen: Settings, monkeypatch: MonkeyPatch, ids: tuple[str, ...]) -> None:
    """Read PRB whole, naming each of ``ids``, which are then deleted."""
    issues = {each: issue_at(each, FIRST - timedelta(days=1), files=False) for each in ids}
    run(chosen, monkeypatch, ProjectSite(projects={"PRB": issues}), first_week([], ["PRB"]), FIRST)


def test_a_run_probes_at_most_max_probes_issues_of_a_project(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: the cap holds for issues; those over it wait, pending, for a later run."""
    chosen = settings(tmp_path)
    gone_from_prb(chosen, monkeypatch, ("1", "2", "3"))
    monkeypatch.setattr(fetching, "MAX_PROBES", 2)
    deleted = ProjectSite(projects={"PRB": {}})
    run(chosen, monkeypatch, deleted, catch_up([], ["PRB"]), FIRST + WEEK)
    assert jira_asked(deleted) == ["/rest/api/3/issue/1", "/rest/api/3/issue/2"]
    stones = RawStore(chosen.raw, "jira").tombstones()
    assert {key[2]: stone.first_gone for key, stone in stones.items()} == {
        "1": FIRST + WEEK,
        "2": FIRST + WEEK,
        "3": None,
    }


def test_many_issues_answering_gone_are_believed_only_while_jira_signs_in(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: Jira's sign-in is checked before many answers of gone are believed.

    Every issue of PRB answers 404, more than a share of those stored; the session, asked
    again, signs in nobody, so the run stops for a sign-in and none of them is dated.
    """
    chosen = settings(tmp_path)
    gone_from_prb(chosen, monkeypatch, ("1", "2", "3"))
    expired = ProjectSite(projects={"PRB": {}}, myself_after=1)
    assert run(chosen, monkeypatch, expired, catch_up([], ["PRB"]), FIRST + WEEK) == (
        "sign in again"
    )
    asked = [url.path for url in expired.asked if url.path.endswith("/myself")]
    assert asked == ["/rest/api/3/myself", "/rest/api/3/myself"]  # at the start, then again
    stones = RawStore(chosen.raw, "jira").tombstones()
    assert {key[2]: stone.first_gone for key, stone in stones.items()} == dict.fromkeys(
        ("1", "2", "3")
    )


def test_this_run_s_whole_read_of_another_project_ends_an_absence(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: 20002, missing from OPS and found in PRB, is present once PRB names it.

    OPS's whole read misses it; found in PRB, whose last whole read does not name it yet,
    it is unsettled, pending; PRB's whole read of a later run names it, and its tombstone
    goes.
    """
    chosen = settings(tmp_path)
    ops = ProjectSite(projects={"OPS": {"20002": in_project("20002", "OPS")}, "PRB": {}})
    run(chosen, monkeypatch, ops, first_week([], ["OPS", "PRB"]), FIRST)
    prb = ProjectSite(projects={"OPS": {}, "PRB": {"20002": in_project("20002", "PRB")}})
    run(chosen, monkeypatch, prb, catch_up([], ["OPS"]), FIRST + WEEK)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.key, stone.scope.key, stone.first_gone) == (
        ("jira", "issue", "20002"),
        "OPS",
        None,
    )
    run(chosen, monkeypatch, prb, catch_up([], ["PRB"]), FIRST + WEEK + timedelta(hours=1))
    assert RawStore(chosen.raw, "jira").tombstones() == {}


def test_a_folder_stays_a_container_when_its_space_s_pages_first_failed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: a first fetch whose pages all fail still mirrors containers.

    Prepare writes the folders alone, then, once the pages come, the pages beside them;
    the index, built then updated, holds each folder with no section, as a whole build.
    """
    chosen = settings(tmp_path)
    index, path = chosen.data_dir / "index.sqlite", "confluence/MFS/2001-inner.md"

    def prepared_and_indexed() -> list[tuple[int, int]]:
        prepared_sources(RawStore(chosen.raw, "confluence"), chosen.docs, SITE, identity)
        if index.exists():
            updated(index, chosen.docs, {}, FIRST, None)
        else:
            build_index(chosen.docs, index, FIRST)
        with reading(index) as reader:
            return reader.bounds(path)

    failing = RefreshSite(pages_fail=True, posts={})
    run(chosen, monkeypatch, failing, first_week(["MFS"], []), FIRST)
    assert prepared_and_indexed() == []
    run(chosen, monkeypatch, RefreshSite(posts={}), catch_up(["MFS"], []), SECOND)
    assert prepared_and_indexed() == []
    build_index(chosen.docs, tmp_path / "whole.sqlite", FIRST)
    with reading(tmp_path / "whole.sqlite") as reader:
        assert reader.bounds(path) == []


def test_an_issue_found_moved_loses_the_tombstone_of_another_project(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Review of 061: OPS's pending tombstone of 20002 goes once PRB's probe finds it moved.

    OPS, PRB and ZED each read 20002 whole in turn; OPS's next whole read misses it and,
    with no probe to spare, keeps it pending; PRB's misses it too, and its probe finds it
    in ZED, whose whole read names it: moved, no tombstone stays.
    """
    chosen = settings(tmp_path)
    for day, key in enumerate(("OPS", "PRB", "ZED")):
        site = ProjectSite(projects={key: {"20002": in_project("20002", key)}})
        run(chosen, monkeypatch, site, first_week([], [key]), FIRST + timedelta(days=day))
    in_zed = ProjectSite(
        projects={"OPS": {}, "PRB": {}, "ZED": {"20002": in_project("20002", "ZED")}}
    )
    cap = fetching.MAX_PROBES
    monkeypatch.setattr(fetching, "MAX_PROBES", 0)
    run(chosen, monkeypatch, in_zed, catch_up([], ["OPS"]), FIRST + WEEK)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.scope.key, stone.first_gone) == ("OPS", None)
    monkeypatch.setattr(fetching, "MAX_PROBES", cap)
    run(chosen, monkeypatch, in_zed, catch_up([], ["PRB"]), FIRST + timedelta(days=1) + WEEK)
    assert "/rest/api/3/issue/20002" in jira_asked(in_zed)
    assert RawStore(chosen.raw, "jira").tombstones() == {}


@pytest.mark.parametrize("order", [["OPS", "PRB"], ["PRB", "OPS"]], ids=["OPS first", "PRB first"])
def test_an_issue_named_by_this_run_s_whole_read_ends_the_run_without_a_tombstone(
    tmp_path: Path, monkeypatch: MonkeyPatch, order: list[str]
) -> None:
    """Review of 061: 20002, confirmed gone from OPS, comes back in PRB, read whole.

    Whichever project the run reads first, OPS, not due, does not bring back the
    tombstone that PRB's whole read ended.
    """
    chosen = settings(tmp_path)
    deleted = moved_then_deleted(chosen, monkeypatch)
    for moment in (FIRST + WEEK, FIRST + WEEK + 2 * CONFIRM_AFTER):
        run(chosen, monkeypatch, deleted, catch_up([], ["OPS"]), moment)
    back = ProjectSite(projects={"OPS": {}, "PRB": {"20002": in_project("20002", "PRB")}})
    run(chosen, monkeypatch, back, catch_up([], order), FIRST + timedelta(days=3) + WEEK)
    assert RawStore(chosen.raw, "jira").tombstones() == {}


@pytest.mark.parametrize(("first", "then"), [("PRB", "OPS"), ("OPS", "PRB")])
def test_a_first_answer_of_gone_in_one_project_is_confirmed_by_the_other_s_probe(
    tmp_path: Path, monkeypatch: MonkeyPatch, first: str, then: str
) -> None:
    """Review of 061: another project's tombstone keeps its date, not only once confirmed.

    Both whole reads named 20002 before it was deleted; the first project read whole
    again dates it gone, the other, two hours later, confirms that tombstone.
    """
    chosen = settings(tmp_path)
    deleted = moved_then_deleted(chosen, monkeypatch)
    due = FIRST + timedelta(days=3) + WEEK
    run(chosen, monkeypatch, deleted, catch_up([], [first]), due)
    run(chosen, monkeypatch, deleted, catch_up([], [then]), due + 2 * CONFIRM_AFTER)
    [stone] = RawStore(chosen.raw, "jira").tombstones().values()
    assert (stone.key, stone.scope.key, stone.first_gone, stone.confirmed) == (
        ("jira", "issue", "20002"),
        first,
        due,
        True,
    )
