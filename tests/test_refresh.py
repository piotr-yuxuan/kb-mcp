"""Runs after the first: catch-up, backfill, plans, deletions and moves, over a scripted site."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from atlassian_offline_mcp.adapters import http
from atlassian_offline_mcp.adapters.pandoc import PandocFailedError
from atlassian_offline_mcp.adapters.raw_store import RawStore, Stored
from atlassian_offline_mcp.adapters.session_file import COOKIES, write_cookies
from atlassian_offline_mcp.app.download import SIGN_IN_NEEDED, Targets, download, plan
from atlassian_offline_mcp.app.mirror import mirror
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.content import Page
from atlassian_offline_mcp.domain.coverage import Coverage, Target
from atlassian_offline_mcp.domain.period import Period, PeriodError
from atlassian_offline_mcp.domain.settings import Settings
from tests.samples import v2_page, v2_space
from tests.test_download import CAP, PAGES, SITE, SPACE, FakeSite, stamp

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

FIRST = datetime(2026, 10, 22, 9, tzinfo=UTC)
SECOND = datetime(2026, 10, 23, 9, tzinfo=UTC)
WEEK = timedelta(days=7)
SIX_MONTHS = timedelta(days=180)
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
    anonymous_after: int | None = None
    user_asks: int = 0

    def routes(self) -> dict[str, Callable[[httpx.Request], httpx.Response]]:
        """Serve the base site, with this run's listing, pages and probes."""
        routes = super().routes()
        routes[f"/wiki/api/v2/spaces/{SPACE}/pages"] = lambda _: httpx.Response(
            200, json={"results": list(self.listing.values()), "_links": {}}
        )
        routes["/wiki/rest/api/user/current"] = self.user
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
    chosen = Settings(SITE, tmp_path / "data")
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
    return download(chosen, targets, lambda: now, lambda _: None).status


def first_week(spaces: list[str], projects: list[str]) -> Targets:
    """Return the targets of a first run over the week before ``FIRST``."""
    return Targets(spaces, projects, CAP, since=FIRST - WEEK)


def catch_up(spaces: list[str], projects: list[str], back: timedelta | None = None) -> Targets:
    """Return the targets of a later run, from what is covered, and reaching ``back``."""
    return Targets(spaces, projects, CAP, back=back)


def stored_pages(chosen: Settings) -> dict[str, str]:
    """Map each stored page to its stored revision."""
    return {
        item.snapshot.document.id: item.snapshot.document.revision
        for item in RawStore(chosen.raw).latest(Page)
        if isinstance(item, Stored)
    }


def test_a_first_run_starts_the_coverage_of_each_target(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A run with --since 7d covers the week, for every target listed whole."""
    chosen = settings(tmp_path)
    assert run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], ["PRB"]), FIRST) == 0
    assert RawStore(chosen.raw).coverage().periods == {
        Target("confluence", "MFS"): Period(FIRST - WEEK, FIRST),
        Target("jira", "PRB"): Period(FIRST - WEEK, FIRST),
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
    assert RawStore(chosen.raw).coverage().periods[Target("confluence", "MFS")] == Period(
        FIRST - WEEK, SECOND
    )


def test_back_reaches_further_and_moves_the_covered_start(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--back 6mo fetches the old page, and the coverage starts six months earlier."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    targets = catch_up(["MFS"], [], back=SIX_MONTHS)
    assert run(chosen, monkeypatch, RefreshSite(), targets, SECOND) == 0
    assert stored_pages(chosen)["1003"] == "000003"
    covered = RawStore(chosen.raw).coverage().periods[Target("confluence", "MFS")]
    assert covered == Period(FIRST - WEEK - SIX_MONTHS, SECOND)


def test_a_target_with_nowhere_to_start_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """No --since and no coverage: refused by name, and nothing is written."""
    chosen = settings(tmp_path)
    with pytest.raises(PeriodError, match=r"^space MFS: nothing covered yet"):
        run(chosen, monkeypatch, RefreshSite(), catch_up(["MFS"], []), FIRST)
    assert not chosen.raw.exists()
    assert not chosen.runs.exists()


def test_a_target_whose_listing_failed_keeps_its_coverage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A refused search leaves the project uncovered; the space is covered all the same."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(search_status=400), first_week(["MFS"], ["PRB"]), FIRST)
    assert set(RawStore(chosen.raw).coverage().periods) == {Target("confluence", "MFS")}


def test_a_plan_lists_and_decides_and_writes_nothing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """--plan asks only for listings and searches, and leaves the data directory as it was."""
    chosen = settings(tmp_path)
    fake = RefreshSite()
    monkeypatch.setattr(http, "client", lambda *_: fake.client())
    outcome = plan(chosen, first_week(["MFS"], ["PRB"]), lambda: FIRST, lambda _: None)
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


def test_a_page_moved_to_another_kept_space_is_not_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Absent from its space, but answering from another space the store keeps."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    store = RawStore(chosen.raw)
    with store.writing():
        store.put_space(v2_space(id=OTHER_SPACE, key="OPS", name="Ops"), [], [], [])
    moved = RefreshSite(listing=without("1001"), moved={"1001": OTHER_SPACE})
    run(chosen, monkeypatch, moved, catch_up(["MFS"], []), SECOND)
    assert store.tombstones() == {}


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
    assert RawStore(chosen.raw).tombstones() == {}


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
    mirror(RawStore(chosen.raw), chosen.docs, SITE, identity)
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
    mirror(store, tmp_path / "docs", SITE, identity)
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
    mirror(RawStore(chosen.raw), chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))


def test_a_gone_page_leaves_the_mirror_even_when_another_has_a_problem(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Problems elsewhere keep last good copies, but never a page known to be gone."""
    chosen = settings(tmp_path)
    run(chosen, monkeypatch, RefreshSite(), first_week(["MFS"], []), FIRST)
    mirror(RawStore(chosen.raw), chosen.docs, SITE, identity)
    assert list((chosen.docs / "confluence" / "MFS").glob("1002-*.md"))
    for day in (1, 2):
        gone = RefreshSite(listing=without("1002"), gone={"1002"})
        run(chosen, monkeypatch, gone, catch_up(["MFS"], []), SECOND + timedelta(days=day))
    broken = next((chosen.raw / "confluence" / "pages" / "1001").iterdir()) / "view.json"
    broken.write_text("{}", "utf-8")  # another document now unreadable
    outcome = mirror(RawStore(chosen.raw), chosen.docs, SITE, identity)
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
    data = (home / "atlassian-offline-mcp").resolve()
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "coverage.json").write_text("[{}]", "utf-8")
    options = ["download", "--config", str(home / "none.toml"), "--site", SITE, "--space", "MFS"]
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
    mirror(store, docs, SITE, identity)
    assert list((docs / "confluence" / "MFS").glob("196845-*.md"))
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [v2_page(spaceId=OTHER_SPACE)], [], [], listed_at=SECOND)
    mirror(store, docs, SITE, identity)
    [moved] = (docs / "confluence").rglob("196845-*.md")
    assert moved.parent.name == "OPS"
    assert "space: OPS" in moved.read_text("utf-8")
    assert moved.name in (docs / "confluence" / "OPS" / "_tree.md").read_text("utf-8")


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
    mirror(store, docs, SITE, identity)
    with store.writing():
        ops = v2_space(id=OTHER_SPACE, key="OPS", name="Ops")
        store.put_space(ops, [v2_page(spaceId=OTHER_SPACE)], [], [], listed_at=SECOND)

    def failing(html: str) -> str:
        if "<p>v</p>" in html:
            message = "pandoc failed"
            raise PandocFailedError(message)
        return html

    outcome = mirror(store, docs, SITE, failing)
    assert outcome.problems
    assert list((docs / "confluence" / "MFS").glob("196845-*.md"))


def test_a_window_never_ends_past_the_run() -> None:
    """An --until in the future stops at now: coverage never claims time not yet seen."""
    later = Targets(["MFS"], [], CAP, since=FIRST - WEEK, until=FIRST + WEEK)
    assert later.windows(Coverage(), FIRST)[Target("confluence", "MFS")].end == FIRST
