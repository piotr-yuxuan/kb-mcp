"""Runs after the first: catch-up, backfill, plans, deletions and moves, over a scripted site."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic_core import to_jsonable_python
from structlog.testing import capture_logs

from kb_mcp.cli.main import main
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore, StoredSnapshot
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.fetch.app.fetching import Targets, plan_fetch, run_fetch
from kb_mcp.sources.atlassian.fetch.domain.content import Page
from kb_mcp.sources.atlassian.fetch.domain.coverage import Coverage, FetchWindow, Target
from kb_mcp.sources.atlassian.fetch.domain.period import EPOCH, Period, PeriodError
from tests.composed import MODEL
from tests.mirrors import mirrored
from tests.samples import v2_page, v2_space
from tests.test_fetching import (
    CAP,
    ISSUE,
    PAGES,
    SIGN_IN_NEEDED,
    SITE,
    SOME_FAILED,
    SPACE,
    FakeSite,
    stamp,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings

FIRST = datetime(2026, 10, 22, 9, tzinfo=UTC)
SECOND = datetime(2026, 10, 23, 9, tzinfo=UTC)
WEEK = timedelta(days=7)
YEAR = timedelta(days=365)
MANY = 30
OTHER_SPACE = "300000"
REFUSED = 2


@dataclass
class RefreshSite(FakeSite):
    """The scripted site of plan 004, whose listing and pages can change between runs.

    ``listing`` replaces the space's pages; ``gone`` answer 404 when probed, ``moved``
    answer from another space; Confluence reads as anonymous after ``anonymous_after``
    asks for the current user.
    """

    listing: dict[str, dict[str, object]] = field(default_factory=lambda: dict(PAGES))
    gone: set[str] = field(default_factory=set)
    moved: dict[str, str] = field(default_factory=dict)
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
    chosen = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=tmp_path / "data")
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    return chosen


def run(
    chosen: Settings,
    monkeypatch: MonkeyPatch,
    fake: FakeSite,
    targets: Targets,
    now: datetime,
) -> int | None:
    """Run one download at ``now`` over the fake site, and return its status."""
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    return run_fetch(chosen, targets, lambda: now, lambda _: None).status


def first_week(spaces: list[str], projects: list[str]) -> Targets:
    """Return the targets of a first run over the week before ``FIRST``."""
    return Targets(spaces=spaces, projects=projects, max_file_bytes=CAP, since=FIRST - WEEK)


def catch_up(spaces: list[str], projects: list[str]) -> Targets:
    """Return the targets of a later run, from what is covered."""
    return Targets(spaces=spaces, projects=projects, max_file_bytes=CAP)


def stored_pages(chosen: Settings) -> dict[str, str]:
    """Map each stored page to its stored revision."""
    return {
        item.snapshot.document.id: item.snapshot.document.revision
        for item in RawStore(chosen.raw).latest(Page)
        if isinstance(item, StoredSnapshot)
    }


def test_a_first_run_starts_the_coverage_of_each_target(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A run of each source with --since 7d covers the week, for every target listed whole."""
    chosen = settings(tmp_path)
    assert run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST) == 0
    assert run(chosen, monkeypatch, RefreshSite(), first_week([], ["PRB"]), FIRST) == 0
    assert RawStore(chosen.raw).coverage().periods == {
        Target(source="confluence", key="MFS"): Period(FIRST - WEEK, FIRST),
        Target(source="jira", key="PRB"): Period(FIRST - WEEK, FIRST),
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
    assert run(chosen, monkeypatch, later, catch_up(["MFS"], []), SECOND) == 0
    assert stored_pages(chosen)["1003"] == "000004"
    assert RawStore(chosen.raw).coverage().periods[
        Target(source="confluence", key="MFS")
    ] == Period(FIRST - WEEK, SECOND)


def test_an_earlier_since_reaches_further_and_moves_the_covered_start(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--since 1y, where --back went: the old page comes, and the coverage starts a year back."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    targets = Targets(spaces=["MFS"], projects=[], max_file_bytes=CAP, since=SECOND - YEAR)
    assert run(chosen, monkeypatch, RefreshSite(), targets, SECOND) == 0
    assert stored_pages(chosen)["1003"] == "000003"
    covered = RawStore(chosen.raw).coverage().periods[Target(source="confluence", key="MFS")]
    assert covered == Period(SECOND - YEAR, SECOND)


def test_an_until_before_since_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Refused by name, before any request, and nothing is written."""
    chosen = settings(tmp_path)
    fake = RefreshSite()
    backwards = Targets(
        spaces=["MFS"], projects=[], max_file_bytes=CAP, since=FIRST, until=FIRST - WEEK
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
    assert set(RawStore(chosen.raw).coverage().periods) == {Target(source="confluence", key="MFS")}


def test_a_plan_lists_and_decides_and_writes_nothing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A dry run asks only for listings and searches, and leaves the data directory as it was."""
    chosen = settings(tmp_path)
    fake = RefreshSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    outcome = plan_fetch(chosen, first_week(["MFS"], ["PRB"]), lambda: FIRST, lambda _: None)
    assert outcome.status == 0
    assert outcome.report.counts["confluence pages: to fetch"] == len(["1001", "1002"])
    assert outcome.report.counts["jira issues: to fetch"] == 1
    assert outcome.report.counts["files: to download"] == 1
    assert outcome.report.counts["files: bytes to download"] > 0
    fetched = [url.path for url in fake.asked if "/pages/" in url.path or "/issue/" in url.path]
    assert fetched == []
    left = sorted(
        path.relative_to(chosen.data_dir).as_posix() for path in chosen.data_dir.rglob("*")
    )
    assert left == ["session", "session/cookies.json"]


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
    [stone] = RawStore(chosen.raw).tombstones().values()
    assert (stone.key, stone.confirmed) == (("pages", "1002"), False)
    gone_again = RefreshSite(listing=without("1002"), gone={"1002"})
    run(chosen, monkeypatch, gone_again, catch_up(["MFS"], []), SECOND + timedelta(days=1))
    [stone] = RawStore(chosen.raw).tombstones().values()
    assert stone.confirmed
    run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), SECOND + timedelta(days=2))
    assert RawStore(chosen.raw).tombstones() == {}


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
    assert RawStore(chosen.raw).tombstones() == {}


def test_a_page_found_in_a_stored_space_that_does_not_list_it_waits(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Found in a space this run does not list, whose stored listing lacks it: kept, pending."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    store = RawStore(chosen.raw)
    with store.writing():
        store.put_space(v2_space(id=OTHER_SPACE, key="OPS", name="Ops"), [], [], [])
    for day in (0, 1):
        moved = RefreshSite(listing=without("1001"), moved={"1001": OTHER_SPACE})
        run(chosen, monkeypatch, moved, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    [stone] = store.tombstones().values()
    assert (stone.key, stone.first_gone, stone.confirmed) == (("pages", "1001"), None, False)
    mirrored(store, chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1001-*.md"))


def test_a_page_found_in_a_stored_space_whose_listing_names_it_is_followed_there(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Named by a space's stored listing, though this run does not list it: moved, not hidden."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    store = RawStore(chosen.raw)
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [{**PAGES["1001"], "spaceId": OTHER_SPACE}], [], [], listed_at=FIRST)
    for day in (0, 1):
        moved = RefreshSite(listing=without("1001"), moved={"1001": OTHER_SPACE})
        run(chosen, monkeypatch, moved, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    assert store.tombstones() == {}
    mirrored(store, chosen.docs, SITE, identity)
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
    stones = RawStore(chosen.raw).tombstones()
    assert stones[("pages", "1002")].confirmed
    assert stones[("pages", "1001")].first_gone is None


def test_a_listed_entry_that_the_reader_refuses_is_not_absent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The new listing is read by id too: an entry refused for its version is still listed."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    versionless = {key: value for key, value in PAGES["1002"].items() if key != "version"}
    refused = RefreshSite(listing={**PAGES, "1002": versionless}, gone={"1002"})
    run(chosen, monkeypatch, refused, catch_up(["MFS"], []), SECOND)
    assert RawStore(chosen.raw).tombstones() == {}


def test_a_page_moved_out_of_the_kept_spaces_is_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Moved where no run looks: it has left the mirror's scope, like a deleted page."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    moved = RefreshSite(listing=without("1001"), moved={"1001": OTHER_SPACE})
    run(chosen, monkeypatch, moved, catch_up(["MFS"], []), SECOND)
    assert list(RawStore(chosen.raw).tombstones()) == [("pages", "1001")]


def test_many_gone_with_a_lost_session_write_no_tombstone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Thirty pages gone at once, and Confluence then reads as anonymous: believe none."""
    chosen = settings(tmp_path)
    many = {str(5000 + n): v2_page(id=str(5000 + n), version=stamp(20)) for n in range(MANY)}
    run(chosen, monkeypatch, RefreshSite(listing=many), first_week(["MFS"], []), FIRST)
    lost = RefreshSite(listing={}, gone=set(many), anonymous_after=1)
    assert run(chosen, monkeypatch, lost, catch_up(["MFS"], []), SECOND) == SIGN_IN_NEEDED
    stones = RawStore(chosen.raw).tombstones().values()
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
    mirrored(RawStore(chosen.raw), chosen.docs, SITE, identity)
    names = sorted(path.name for path in (chosen.docs / "confluence" / "MFS").glob("*.md"))
    assert [name for name in names if name.startswith("1002-")] == []
    assert [name for name in names if name.startswith("1001-")]


def test_the_mirror_places_a_page_in_the_space_that_lists_it(tmp_path: Path) -> None:
    """A page listed in another space than its snapshot names is mirrored there."""
    store = RawStore(tmp_path / "raw")
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
    mirrored(store, tmp_path / "docs", SITE, identity)
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
    assert run(chosen, monkeypatch, deleted, catch_up(["MFS"], []), SECOND) == 0
    assert len(RawStore(chosen.raw).tombstones()) == MANY


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
    mirrored(RawStore(chosen.raw), chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))


def test_a_gone_page_leaves_the_mirror_even_when_another_has_a_problem(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Problems elsewhere keep last good copies, but never a page known to be gone."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    mirrored(RawStore(chosen.raw), chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    broken = next((chosen.raw / "confluence" / "pages" / "1001").iterdir()) / "view.json"
    broken.write_text("{}", "utf-8")  # another document now unreadable
    outcome = mirrored(RawStore(chosen.raw), chosen.docs, SITE, identity)["confluence"]
    assert outcome.problems
    assert not list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))
    assert list((chosen.docs / "confluence" / "MFS").glob("1001-*.md"))


def test_a_corrupt_coverage_record_is_refused_by_the_command(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """A record that cannot be read refuses the run, naming it, rather than starting over."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    data = (home / "kb-mcp").resolve()
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "coverage.json").write_text("[{}]", "utf-8")
    options = [
        "fetch",
        "--yes",
        "--config",
        str(home / "none.toml"),
        "--site",
        SITE,
        "--space",
        "MFS",
    ]
    assert main(options) == REFUSED
    assert "coverage.json[0]" in capsys.readouterr().err


def test_a_moved_page_takes_its_new_space_everywhere_and_leaves_the_old(tmp_path: Path) -> None:
    """The freshest listing wins: path, front matter, tree, and the old file goes."""
    store = RawStore(tmp_path / "raw")
    docs = tmp_path / "docs"
    responses = {
        "document.json": v2_page(),
        "view.json": v2_page(body={"view": {"value": "<p>v</p>", "representation": "view"}}),
        "attachments.json": [],
    }
    with store.writing():
        store.put(Page, responses, FIRST, {})
        store.put_space(v2_space(), [v2_page()], [], [], listed_at=FIRST)
    mirrored(store, docs, SITE, identity)
    assert list((docs / "confluence" / "MFS").glob("196845-*.md"))
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [v2_page(spaceId=OTHER_SPACE)], [], [], listed_at=SECOND)
    mirrored(store, docs, SITE, identity)
    [moved] = (docs / "confluence").rglob("196845-*.md")
    assert moved.parent.name == "OPS"
    assert "space: OPS" in moved.read_text("utf-8")
    assert moved.name in (docs / "confluence" / "OPS" / "_tree.md").read_text("utf-8")


def test_a_damaged_listing_time_is_one_problem_not_one_per_document(tmp_path: Path) -> None:
    """The time a space was listed is read once a run, and a damaged record named once."""
    store = RawStore(tmp_path / "raw")
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
    outcome = mirrored(store, tmp_path / "docs", SITE, identity)["confluence"]
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
    run(chosen, monkeypatch, failing, catch_up(["MFS"], []), SECOND)
    [pending] = RawStore(chosen.raw).tombstones().values()
    assert (pending.key, pending.first_gone, pending.confirmed) == (("pages", "1002"), None, False)
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    [stone] = RawStore(chosen.raw).tombstones().values()
    assert stone.confirmed


def test_a_moved_page_whose_new_file_fails_keeps_its_old_file(tmp_path: Path) -> None:
    """The last good copy of a moved page stays until its new file is built."""
    store = RawStore(tmp_path / "raw")
    docs = tmp_path / "docs"
    responses = {
        "document.json": v2_page(),
        "view.json": v2_page(body={"view": {"value": "<p>v</p>", "representation": "view"}}),
        "attachments.json": [],
    }
    with store.writing():
        store.put(Page, responses, FIRST, {})
        store.put_space(v2_space(), [v2_page()], [], [], listed_at=FIRST)
    mirrored(store, docs, SITE, identity)
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [v2_page(spaceId=OTHER_SPACE)], [], [], listed_at=SECOND)

    def failing(html: str) -> str:
        if "<p>v</p>" in html:
            message = "pandoc failed"
            raise PandocFailedError(message)
        return html

    outcome = mirrored(store, docs, SITE, failing)["confluence"]
    assert outcome.problems
    assert list((docs / "confluence" / "MFS").glob("196845-*.md"))


def test_a_window_never_ends_past_the_run() -> None:
    """An --until in the future stops at now: coverage never claims time not yet seen."""
    later = Targets(
        spaces=["MFS"], projects=[], max_file_bytes=CAP, since=FIRST - WEEK, until=FIRST + WEEK
    )
    window = later.windows(Coverage(), FIRST)[Target(source="confluence", key="MFS")]
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
    assert "1002" in RawStore(chosen.raw).stored_ids(Page)
    rest = {key: page for key, page in titleless.items() if key != "1002"}
    for day in (1, 2):
        gone = RefreshSite(listing=rest, gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    [stone] = RawStore(chosen.raw).tombstones().values()
    assert (stone.key, stone.confirmed) == (("pages", "1002"), True)


def test_a_stale_listing_never_brings_back_a_page_confirmed_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A space listed long before the page answered gone cannot revive it."""
    chosen = settings(tmp_path)
    store = RawStore(chosen.raw)
    with store.writing():
        stale = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        entry = {**PAGES["1002"], "spaceId": OTHER_SPACE}
        store.put_space(stale, [entry], [], [], listed_at=FIRST - timedelta(days=30))
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    mirrored(store, chosen.docs, SITE, identity)
    assert list(chosen.docs.rglob("1002-*.md")) == []


def test_a_since_before_the_epoch_starts_at_the_epoch() -> None:
    """Nothing on the site is older; the dates searched stay within the calendar."""
    early = Targets(
        spaces=["MFS"], projects=[], max_file_bytes=CAP, since=datetime(1, 1, 2, tzinfo=UTC)
    )
    window = early.windows(Coverage(), FIRST)[Target(source="confluence", key="MFS")]
    assert window is not None
    assert window.period.start == EPOCH


# Plan 034: a project's coverage ends exactly, at its earliest document not stored whole.
PRB = Target(source="jira", key="PRB")
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


def exactly(start: datetime, end: datetime) -> Coverage:
    """Return PRB covered exactly from ``start`` to ``end``."""
    return Coverage(periods={PRB: Period(start, end)}, exact=frozenset({PRB}))


def said_coverage(events: list[dict[str, object]]) -> list[tuple[object, ...]]:
    """Give what ``fetch.coverage`` said, target by target: the outcome, and why if held."""
    return [
        (event["target"], event["outcome"], *([event["reason"]] if "reason" in event else []))
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
            Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
            RUN,
        )
    assert RawStore(chosen.raw).coverage() == exactly(START, FAILING)
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    stored_issue(chosen, "20001").write_text("{}", "utf-8")
    again = Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START)
    with capture_logs() as events:
        run(chosen, monkeypatch, RefreshSite(issues=two_issues()), again, NEXT)
    assert RawStore(chosen.raw).coverage() == exactly(START, FAILING)
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    again = RefreshSite(issues=two_issues())
    with capture_logs() as events:
        run(chosen, monkeypatch, again, catch_up([], ["PRB"]), NEXT)
    assert asked_again in [url.path for url in again.asked]
    assert RawStore(chosen.raw).coverage() == exactly(START, NEXT)
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), catch_up([], ["PRB"]), NEXT)
    assert RawStore(chosen.raw).coverage() == exactly(START, FAILING)
    stored_issue(chosen, "20001").write_text(json.dumps(issue_at("20001", FAILING)), "utf-8")
    again = RefreshSite(issues=two_issues())
    later = NEXT + timedelta(hours=6)
    run(chosen, monkeypatch, again, catch_up([], ["PRB"]), later)
    assert ISSUE_FILE in [url.path for url in again.asked]
    assert RawStore(chosen.raw).coverage() == exactly(START, later)


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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    assert RawStore(chosen.raw).coverage() == exactly(START, earlier)


def test_a_search_entry_that_the_adapter_refuses_holds_the_coverage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Without its update time, it has no moment to stop at: the coverage stays, said held."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), first_week([], ["PRB"]), FIRST)
    before = RawStore(chosen.raw).coverage()
    timeless = issue_at("20004", FINE)
    values = timeless["fields"]
    assert isinstance(values, dict)
    timeless["fields"] = {key: value for key, value in values.items() if key != "updated"}
    refused = RefreshSite(issues={**two_issues(), "20004": timeless})
    with capture_logs() as events:
        run(chosen, monkeypatch, refused, catch_up([], ["PRB"]), RUN)
    assert RawStore(chosen.raw).coverage() == before
    assert said_coverage(events) == [("project PRB", "held", "entries refused")]


@pytest.mark.parametrize(("status", "stopped"), [(503, SOME_FAILED), (401, SIGN_IN_NEEDED)])
def test_a_run_stopped_during_a_project_leaves_its_coverage_and_extends_those_before(
    status: int, stopped: int, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Failures in a row, or a sign-in lost, during PRB's fetch: MFS, fetched first, grows.

    PRB's coverage stays as it was.
    """
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), first_week(["MFS"], []), FIRST)
    run(chosen, monkeypatch, RefreshSite(issues=two_issues()), first_week([], ["PRB"]), FIRST)
    before = RawStore(chosen.raw).coverage().periods[PRB]
    many = {str(30000 + n): issue_at(str(30000 + n), RUN - timedelta(hours=1)) for n in range(MANY)}
    failing = RefreshSite(issues=many, failing_issues=dict.fromkeys(many, status))
    assert run(chosen, monkeypatch, failing, catch_up(["MFS"], []), RUN) == 0
    assert run(chosen, monkeypatch, failing, catch_up([], ["PRB"]), RUN) == stopped
    periods = RawStore(chosen.raw).coverage().periods
    assert periods[PRB] == before
    assert periods[Target(source="confluence", key="MFS")] == Period(FIRST - WEEK, RUN)


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
    windows = catch_up([], ["PRB"]).windows(RawStore(chosen.raw).coverage(), NEXT)
    assert windows == {PRB: FetchWindow(period=Period(START, NEXT), reason="covered start")}
    failing = RefreshSite(issues=two_issues(), failing_issues={"20001": 500})
    run(chosen, monkeypatch, failing, catch_up([], ["PRB"]), NEXT)
    assert RawStore(chosen.raw).coverage() == exactly(START, FAILING)
    again = RefreshSite(issues=two_issues())
    later = NEXT + timedelta(hours=6)
    run(chosen, monkeypatch, again, catch_up([], ["PRB"]), later)
    assert "/rest/api/3/issue/20001" in [url.path for url in again.asked]
    assert RawStore(chosen.raw).coverage() == exactly(START, later)


def test_an_entry_from_before_034_met_by_a_later_since_stays_inexact(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--since after its start joins it as before, whatever failed: no failure is blessed."""
    chosen = settings(tmp_path)
    chosen.raw.mkdir(parents=True)
    old = [{"source": "jira", "key": "PRB", "start": START.isoformat(), "end": RUN.isoformat()}]
    (chosen.raw / "coverage.json").write_text(json.dumps(old), "utf-8")
    failing = RefreshSite(issues=two_issues(), failing_issues={"20001": 500})
    inside = Targets(
        spaces=[], projects=["PRB"], max_file_bytes=CAP, since=FAILING - timedelta(hours=1)
    )
    run(chosen, monkeypatch, failing, inside, NEXT)
    after = RawStore(chosen.raw).coverage()
    assert after == Coverage(periods={PRB: Period(START, NEXT)})
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        LAST_FETCH,
    )
    assert RawStore(chosen.raw).coverage() == exactly(START, LAST_FETCH)
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
    assert RawStore(chosen.raw).coverage() == exactly(START, CATCH_UP)


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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        LAST_FETCH,
    )
    until = datetime(2026, 10, 28, 6, tzinfo=UTC)
    issues = {"20013": issue_at("20013", CATCH_UP - timedelta(hours=2), files=False)}
    later = RefreshSite(issues=issues)
    run(
        chosen,
        monkeypatch,
        later,
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, until=until),
        CATCH_UP,
    )
    assert jira_asked(later) == []
    assert RawStore(chosen.raw).coverage() == exactly(START, until)


def test_a_failure_at_the_start_of_a_catch_up_ends_the_coverage_there(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """At a day before the covered end: the coverage ends there, and the next run asks again."""
    chosen = settings(tmp_path)
    run(
        chosen,
        monkeypatch,
        RefreshSite(issues={}),
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    start_of_catch_up = RUN - timedelta(days=1)
    issues = {"20020": issue_at("20020", start_of_catch_up)}
    failing = RefreshSite(issues=issues, failing_issues={"20020": 500})
    run(chosen, monkeypatch, failing, catch_up([], ["PRB"]), NEXT)
    assert RawStore(chosen.raw).coverage() == exactly(START, start_of_catch_up)
    again = RefreshSite(issues=issues)
    later = NEXT + timedelta(hours=6)
    run(chosen, monkeypatch, again, catch_up([], ["PRB"]), later)
    assert "/rest/api/3/issue/20020" in jira_asked(again)
    assert RawStore(chosen.raw).coverage() == exactly(START, later)


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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    targets = catch_up(["MFS"], ["PRB"])
    assert targets.windows(RawStore(chosen.raw).coverage(), NEXT) == {
        Target(source="confluence", key="MFS"): FetchWindow(
            period=Period(NEXT - WEEK, NEXT), reason="first fetch"
        ),
        PRB: FetchWindow(
            period=Period(RUN - timedelta(days=1), NEXT), reason="since the last fetch"
        ),
    }
    assert run(chosen, monkeypatch, RefreshSite(issues={}), catch_up(["MFS"], []), NEXT) == 0
    assert run(chosen, monkeypatch, RefreshSite(issues={}), catch_up([], ["PRB"]), NEXT) == 0
    assert RawStore(chosen.raw).coverage().periods == {
        Target(source="confluence", key="MFS"): Period(NEXT - WEEK, NEXT),
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    before = RawStore(chosen.raw).coverage().periods[PRB]
    until = RUN - timedelta(days=1)
    fake = RefreshSite(issues=two_issues())
    with capture_logs() as events:
        space = Targets(spaces=["MFS"], projects=[], max_file_bytes=CAP, until=until)
        run(chosen, monkeypatch, fake, space, NEXT)
        project = Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, until=until)
        run(chosen, monkeypatch, fake, project, NEXT)
    assert not [url for url in fake.asked if url.path.startswith("/rest/api/3/search")]
    periods = RawStore(chosen.raw).coverage().periods
    assert periods[PRB] == before
    assert periods[Target(source="confluence", key="MFS")] == Period(FIRST - WEEK, until)
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    again = RefreshSite(issues=two_issues(), media_fails=True)
    with capture_logs() as events:
        run(chosen, monkeypatch, again, catch_up([], ["PRB"]), NEXT)
    assert ISSUE_FILE in [url.path for url in again.asked]
    assert RawStore(chosen.raw).coverage() == exactly(START, FAILING)
    assert said_coverage(events) == [("project PRB", "capped")]


def test_a_space_whose_catch_up_starts_after_until_is_skipped_and_said_so(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No listing, the coverage as it was; the summary and the JSON say why, without a window."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    before = RawStore(chosen.raw).coverage()
    fake = RefreshSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    early = Targets(spaces=["MFS"], projects=[], max_file_bytes=CAP, until=FIRST - WEEK)
    outcome = run_fetch(chosen, early, lambda: SECOND, lambda _: None)
    assert not [url for url in fake.asked if url.path.startswith("/wiki/api/v2/spaces")]
    assert RawStore(chosen.raw).coverage() == before
    detailed = outcome.text("detailed")
    assert "space MFS: skipped, after --until; coverage held\n" in detailed
    [window] = to_jsonable_python(outcome)["windows"]
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        RUN,
    )
    apart = Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=RUN + timedelta(days=1))
    with capture_logs() as events:
        run(chosen, monkeypatch, RefreshSite(issues={}), apart, RUN + timedelta(days=2))
    assert RawStore(chosen.raw).coverage() == exactly(START, RUN)
    assert said_coverage(events) == [("project PRB", "held", "apart from what is covered")]


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
            Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
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
        Targets(spaces=[], projects=["PRB"], max_file_bytes=CAP, since=START),
        lambda: RUN,
        lambda _: None,
    )
    assert planned.report.counts["jira issues: to fetch"] == 1
    assert planned.report.counts["files: to download"] == 1
