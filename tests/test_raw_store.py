"""The raw store keeps responses as received, whole, by revision, and files once."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.outcome import Problem
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import (
    RawStore,
    StoreBusyError,
    StoredSnapshot,
)
from kb_mcp.sources.atlassian.fetch.domain import names
from kb_mcp.sources.atlassian.fetch.domain.content import (
    BlogPost,
    Folder,
    Issue,
    Page,
    SiteUser,
    Space,
)
from kb_mcp.sources.atlassian.fetch.domain.coverage import Coverage, Scope
from kb_mcp.sources.atlassian.fetch.domain.deletions import Tombstone
from kb_mcp.sources.atlassian.fetch.domain.period import Period
from tests.samples import (
    v1_user,
    v2_attachment,
    v2_folder,
    v2_page,
    v2_space,
    v2_view,
    v3_comment,
    v3_issue,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

FETCHED = datetime(2026, 10, 22, 9, 15, tzinfo=timezone(timedelta(hours=1)))
NEWER = 10


@pytest.fixture
def store(tmp_path: Path) -> Iterator[RawStore]:
    """Give a store under a scratch folder, held for writing."""
    raw = RawStore(tmp_path / "raw")
    with raw.writing():
        yield raw


def page_responses(version: int, page_id: str = "196845", **changes: object) -> dict[str, object]:
    """Return the responses of a page's snapshot at a version, with one attachment."""
    stamp = {"number": version, "createdAt": "2026-10-20T21:52:41Z"}
    return {
        confluence_v2.DOCUMENT: v2_page(id=page_id, version=stamp, **changes),
        confluence_v2.VIEW: v2_view(id=page_id, version=stamp),
        confluence_v2.ATTACHMENTS: [v2_attachment()],
    }


def readable(results: Iterator[StoredSnapshot | Problem] | list[object]) -> list[StoredSnapshot]:
    """Keep the snapshots that were read, and fail on any that was not."""
    items = list(results)
    assert not [item for item in items if isinstance(item, Problem)]
    return [item for item in items if isinstance(item, StoredSnapshot)]


def test_the_newest_snapshot_of_each_document_is_read_back(store: RawStore) -> None:
    """Of versions 9 and 10, version 10 is the one read back."""
    store.put(Page, page_responses(9), FETCHED, {})
    store.put(Page, page_responses(NEWER), FETCHED, {})
    [latest] = readable(store.latest(Page))
    assert latest.snapshot.document.revision == "000010"


def test_a_snapshot_reads_back_as_the_domain_with_its_record(store: RawStore) -> None:
    """What was stored comes back read by its adapter, with the time it was fetched."""
    folder = store.put(Page, page_responses(3), FETCHED, {})
    [stored] = readable(store.latest(Page))
    assert stored.folder == folder
    assert stored.snapshot.html == "<p>Hello, rendered</p>"
    assert stored.fetched_at == FETCHED
    assert json.loads((folder / "store.json").read_text("utf-8"))["fetched_at"] == (
        "2026-10-22T08:15:00Z"
    )
    assert stored.blobs == {}


def test_responses_are_kept_as_received(store: RawStore) -> None:
    """Fields that no adapter reads, and any text the site sent, come back unchanged."""
    responses = page_responses(1, ancestors=[{"id": "1"}], note="café \ud800")
    folder = store.put(Page, responses, FETCHED, {})
    assert store.responses(folder) == responses


def test_issues_are_stored_by_their_id_and_update_time(store: RawStore) -> None:
    """An issue's folder is its id, and its revision its update time in UTC."""
    responses = {jira_v3.ISSUE: v3_issue(), jira_v3.COMMENTS: [v3_comment()]}
    folder = store.put(Issue, responses, FETCHED, {})
    assert folder == store.root / "jira" / "issues" / "10000" / "20261020T213758.027000Z"
    [stored] = readable(store.latest(Issue))
    assert stored.snapshot.document.title == "What are archived ideas?"


def test_a_stored_revision_is_not_written_again(store: RawStore) -> None:
    """A revision's responses are immutable: storing it again keeps the first."""
    store.put(Page, page_responses(1, title="First"), FETCHED, {})
    store.put(Page, page_responses(1, title="Second"), FETCHED, {})
    [stored] = readable(store.latest(Page))
    assert stored.snapshot.document.title == "First"


def test_a_snapshot_that_fails_while_written_leaves_nothing(store: RawStore) -> None:
    """A snapshot is stored whole or not at all, with no hidden folder left behind."""
    responses = {**page_responses(1), "unwritable.json": object()}
    with pytest.raises(TypeError):
        store.put(Page, responses, FETCHED, {})
    assert list(store.latest(Page)) == []
    assert list((store.root / "confluence" / "pages" / "196845").iterdir()) == []


def test_a_changed_response_is_kept_and_reported_when_read(store: RawStore) -> None:
    """Raw first: a response the adapter refuses is still stored, then read as Problem.

    The others still come back, so one changed response never hides the rest.
    """
    labels = {"results": [{"label": "renamed field"}]}
    store.put(Page, page_responses(1, page_id="100"), FETCHED, {})
    store.put(Page, page_responses(1, page_id="200", labels=labels), FETCHED, {})
    store.put(Page, page_responses(1, page_id="300"), FETCHED, {})
    results = list(store.latest(Page))
    assert [type(item) for item in results] == [StoredSnapshot, Problem, StoredSnapshot]
    unreadable = results[1]
    assert isinstance(unreadable, Problem)
    assert unreadable.where == "confluence/pages/200/000001"
    assert unreadable.reason == "document.json.labels.results[0].name: missing"


@pytest.mark.parametrize(
    ("view", "field"),
    [
        ({"id": "999"}, r"view\.json\.id"),
        ({"version": {"number": 2}}, r"view\.json\.version\.number"),
    ],
)
def test_a_view_of_another_page_or_version_is_refused(
    store: RawStore, view: dict[str, object], field: str
) -> None:
    """A snapshot is one document at one revision: a mismatched view is never stored."""
    responses = page_responses(3)
    stamp = {"number": 3, "createdAt": "2026-10-20T21:52:41Z"}
    responses[confluence_v2.VIEW] = v2_view(**{"version": stamp, **view})
    with pytest.raises(RepresentationError, match=f"^{field}: does not match"):
        store.put(Page, responses, FETCHED, {})
    assert not (store.root / "confluence").exists()


def test_stray_entries_are_not_snapshots(store: RawStore) -> None:
    """Hidden leftovers, Finder's .DS_Store and copies are skipped, at every level."""
    folder = store.put(Page, page_responses(1), FETCHED, {})
    (folder.parent / ".zzzzzz.crashed").mkdir()
    (folder.parent / "old").mkdir()
    (folder.parent / "000001 copy").mkdir()
    (folder.parent / "notes.txt").write_text("", "utf-8")
    (folder.parent.parent / ".DS_Store").write_text("", "utf-8")
    (folder / "._view.json").write_text("not JSON", "utf-8")
    [stored] = readable(store.latest(Page))
    assert stored.folder == folder


@pytest.mark.parametrize("name", ["../escape.json", "plain", "store.json", ".hidden.json"])
def test_a_response_name_that_is_not_a_plain_json_file_is_refused(
    store: RawStore, name: str
) -> None:
    """A response name cannot place a file outside its snapshot, nor be the store's own."""
    with pytest.raises(ValueError, match="not "):
        store.put(Page, {**page_responses(1), name: {}}, FETCHED, {})


def test_blobs_must_name_files_already_stored(store: RawStore) -> None:
    """Files first, snapshot last: a record never names a file that is not stored."""
    digest = hashlib.sha256(b"never stored").hexdigest()
    with pytest.raises(ValueError, match="blobs:"):
        store.put(Page, page_responses(1), FETCHED, {"att196895": digest})
    assert not (store.root / "confluence").exists()


def test_a_file_downloaded_later_is_added_to_its_snapshot(store: RawStore) -> None:
    """A file that failed on the first run is recorded when a later run downloads it."""
    store.put(Page, page_responses(1), FETCHED, {})
    [stored] = readable(store.latest(Page))
    digest = store.put_blob(b"image bytes")
    store.add_blobs(stored.snapshot.document, {"att196895": digest})
    again = store.read(stored.snapshot.document)
    assert again.blobs == {"att196895": digest}
    assert again.fetched_at == FETCHED


def test_putting_a_stored_revision_records_its_new_blobs(store: RawStore) -> None:
    """A second put of the same revision keeps the responses and adds the files given."""
    store.put(Page, page_responses(1), FETCHED, {})
    digest = store.put_blob(b"image bytes")
    folder = store.put(Page, page_responses(1, title="Second"), FETCHED, {"att196895": digest})
    [stored] = readable(store.latest(Page))
    assert (stored.folder, stored.blobs) == (folder, {"att196895": digest})
    assert stored.snapshot.document.title == "Probe complex"


def test_a_file_is_stored_once_under_its_digest(store: RawStore) -> None:
    """The same bytes stored twice make one file, named by their SHA-256."""
    digest = store.put_blob(b"image bytes")
    assert digest == hashlib.sha256(b"image bytes").hexdigest()
    assert store.put_blob(b"image bytes") == digest
    assert store.blob(digest).read_bytes() == b"image bytes"
    assert [path.name for path in store.blob(digest).parent.iterdir()] == [digest]


def test_a_digest_that_is_a_path_is_refused(store: RawStore) -> None:
    """A digest read from a record cannot name a file outside the blobs."""
    with pytest.raises(ValueError, match="not a SHA-256 digest"):
        store.blob("../../../x")


def test_writing_needs_the_lock_and_one_writer_holds_it(tmp_path: Path) -> None:
    """Writes happen inside writing(); a second writer is refused while the first holds."""
    store = RawStore(tmp_path / "raw")
    with pytest.raises(RuntimeError, match="only inside"):
        store.put_blob(b"bytes")
    with store.writing(), pytest.raises(StoreBusyError), RawStore(store.root).writing():
        pass
    with store.writing():
        store.put_blob(b"bytes")


def test_an_empty_store_has_nothing(tmp_path: Path) -> None:
    """A store that was never written has no snapshots, spaces or users."""
    store = RawStore(tmp_path / "raw")
    assert list(store.latest(Issue)) == []
    assert store.spaces() == []
    assert store.users() == []


def test_spaces_listed_on_different_runs_are_all_kept(store: RawStore) -> None:
    """A run naming one space never drops another space that an earlier run listed."""
    store.put_space(v2_space(), [v2_page()], [], [v2_folder()])
    store.put_space(v2_space(id="300000", key="OPS", name="Another"), [], [], [])
    assert store.spaces() == [
        Space(id="196613", key="MFS", name="A space"),
        Space(id="300000", key="OPS", name="Another"),
    ]
    [page] = store.listed("196613", Page)
    assert isinstance(page, Page)
    assert page.parent_type == "page"
    assert store.listed("196613", BlogPost) == []
    assert store.folders("196613") == [
        Folder(id="197001", title="A folder", parent_id="196725", parent_type="page")
    ]


def test_a_space_listing_is_replaced_whole(store: RawStore) -> None:
    """The newest listing of a space replaces the last."""
    store.put_space(v2_space(), [v2_page(), v2_page(id="196846")], [], [])
    store.put_space(v2_space(), [v2_page()], [], [])
    assert [page.id for page in store.listed("196613", Page) if isinstance(page, Page)] == [
        "196845"
    ]


def test_an_entry_of_a_listing_that_its_adapter_refuses_is_reported_alone(
    store: RawStore,
) -> None:
    """One changed entry is Problem at its index; the others are read."""
    store.put_space(v2_space(), [v2_page(), v2_page(id="2", title=None)], [], [])
    first, second = store.listed("196613", Page)
    assert isinstance(first, Page)
    where = "confluence/spaces/196613/pages.json[1]"
    assert second == Problem(where=where, reason=f"{where}.title: expected a string")


def test_a_space_id_that_is_a_path_is_refused(store: RawStore) -> None:
    """A space's id names its folder of listings."""
    with pytest.raises(RepresentationError, match="space id: does not match"):
        store.put_space(v2_space(id="../x"), [], [], [])


def test_users_are_merged_across_runs_by_account_id(store: RawStore) -> None:
    """Authors seen by earlier runs stay; a user seen again takes the newer name."""
    store.put_users([v1_user(), v1_user(accountId="account-2", displayName="Two")])
    store.put_users([v1_user(displayName="Renamed")])
    assert store.users() == [
        SiteUser(account_id="account-1", display_name="Renamed"),
        SiteUser(account_id="account-2", display_name="Two"),
    ]


@pytest.mark.parametrize(
    ("document_class", "missing"),
    [(Page, confluence_v2.ATTACHMENTS), (Page, confluence_v2.VIEW), (Issue, jira_v3.COMMENTS)],
)
def test_a_snapshot_without_one_of_its_responses_is_refused(
    store: RawStore, document_class: type[Page | Issue], missing: str
) -> None:
    """A stored revision is never written again, so it must be whole when first stored."""
    responses: dict[str, object] = (
        page_responses(1)
        if document_class is Page
        else {jira_v3.ISSUE: v3_issue(), jira_v3.COMMENTS: [v3_comment()]}
    )
    del responses[missing]
    with pytest.raises(ValueError, match=f"a snapshot without {missing}"):
        store.put(document_class, responses, FETCHED, {})
    assert not (store.root / document_class.source).exists()


def test_a_blob_of_another_attachment_is_not_a_file_of_this_snapshot(store: RawStore) -> None:
    """A record naming an attachment the snapshot lacks gives it no file."""
    digest = store.put_blob(b"image bytes")
    store.put(Page, page_responses(1), FETCHED, {"att196895": digest, "att-elsewhere": digest})
    [stored] = readable(store.latest(Page))
    assert stored.blobs == {"att196895": digest}


def test_a_user_without_an_account_id_is_named_by_its_index(store: RawStore) -> None:
    """The refusal names the entry of the users given, not of those kept."""
    store.put_users([v1_user()])
    with pytest.raises(RepresentationError, match=r"^users\[0\]\.accountId: missing"):
        store.put_users([{"displayName": "No id"}])
    assert store.users() == [SiteUser(account_id="account-1", display_name="A Person")]


@pytest.mark.parametrize(
    "write",
    [
        lambda store: store.put(Page, page_responses(1), FETCHED, {}),
        lambda store: store.put_space(v2_space(), [], [], []),
        lambda store: store.put_users([v1_user()]),
        lambda store: store.put_blob(b"bytes"),
    ],
)
def test_every_write_needs_the_lock(tmp_path: Path, write: object) -> None:
    """No method writes outside writing()."""
    store = RawStore(tmp_path / "raw")
    with pytest.raises(RuntimeError, match="only inside"):
        write(store)  # type: ignore[operator]
    assert not (store.root / "confluence").exists()


def test_coverage_and_tombstones_read_back_as_written(store: RawStore) -> None:
    """The store's two records of runs keep what was put, in any time zone, as UTC."""
    start = datetime(2026, 10, 15, 11, tzinfo=timezone(timedelta(hours=2)))
    coverage = Coverage(
        periods={
            Scope(source="confluence", type=names.SPACE, key="MFS"): Period(start, FETCHED),
            Scope(source="jira", type=names.PROJECT, key="PRB"): Period(
                start - timedelta(days=1), FETCHED
            ),
            Scope(source="jira", type=names.PROJECT, key="OPS"): Period(start, FETCHED),
        },
        exact=frozenset({Scope(source="jira", type=names.PROJECT, key="PRB")}),
    )
    store.put_coverage(coverage)
    assert store.coverage() == coverage
    stone = Tombstone(
        resource_type="pages", id="1001", space_id="196613", first_gone=FETCHED, confirmed=True
    )
    store.put_tombstones([stone])
    assert store.tombstones() == {("pages", "1001"): stone}


def test_a_coverage_record_keeps_the_format_of_before_034_beside_exact(store: RawStore) -> None:
    """Its four keys as they were, ``exact`` only on an exact entry: old versions read it.

    A record from before plan 034, without ``exact``, reads as inexact.
    """
    start = datetime(2026, 10, 15, 9, tzinfo=UTC)
    period = Period(start, start + timedelta(days=7))
    space, project = (
        Scope(source="confluence", type=names.SPACE, key="MFS"),
        Scope(source="jira", type=names.PROJECT, key="PRB"),
    )
    store.put_coverage(
        Coverage(periods={space: period, project: period}, exact=frozenset({project}))
    )
    written = json.loads((store.root / "coverage.json").read_text("utf-8"))
    times = {"start": "2026-10-15T09:00:00+00:00", "end": "2026-10-22T09:00:00+00:00"}
    assert written == [
        {"source": "confluence", "key": "MFS", **times},
        {"source": "jira", "key": "PRB", **times, "exact": True},
    ]
    old = [{key: value for key, value in entry.items() if key != "exact"} for entry in written]
    (store.root / "coverage.json").write_text(json.dumps(old), "utf-8")
    assert store.coverage() == Coverage(periods={space: period, project: period})


def test_a_space_s_entry_marked_exact_is_read_as_inexact(store: RawStore) -> None:
    """A space is listed whole: a hand-edited or later record does not change its catch-up."""
    (store.root / "coverage.json").write_text(
        '[{"source": "confluence", "key": "MFS", "start": "2026-10-15T09:00:00+00:00",'
        ' "end": "2026-10-16T09:00:00+00:00", "exact": true}]',
        "utf-8",
    )
    assert store.coverage().exact == frozenset()


def test_records_never_written_read_as_empty(tmp_path: Path) -> None:
    """A first run has no coverage and no tombstone."""
    store = RawStore(tmp_path / "raw")
    assert store.coverage() == Coverage()
    assert store.tombstones() == {}


def test_a_record_naming_a_key_that_is_a_path_is_refused(store: RawStore) -> None:
    """A record read back is checked like any response."""
    (store.root / "coverage.json").write_text(
        '[{"source": "confluence", "key": "../x", "start": "2026-10-15T09:00:00+00:00",'
        ' "end": "2026-10-16T09:00:00+00:00"}]',
        "utf-8",
    )
    with pytest.raises(RepresentationError, match=r"coverage\.json\[0\]: key: does not match"):
        store.coverage()


def test_a_tombstone_confirmed_without_a_first_answer_is_refused(store: RawStore) -> None:
    """A damaged record is refused by name, rather than hiding a page for no reason."""
    (store.root / "tombstones.json").write_text(
        '[{"kind": "pages", "id": "1001", "space": "196613", "first_gone": null,'
        ' "confirmed": true}]',
        "utf-8",
    )
    with pytest.raises(RepresentationError, match=r"tombstones\.json\[0\]: confirmed"):
        store.tombstones()


@pytest.mark.parametrize("name", ["coverage.json", "tombstones.json"])
def test_a_record_that_no_read_reaches_is_refused_by_name(store: RawStore, name: str) -> None:
    """A folder in its place: not an ``OSError`` that no caller of a record's read expects."""
    (store.root / name).mkdir()
    read = store.coverage if name == "coverage.json" else store.tombstones
    with pytest.raises(RepresentationError, match=rf"^{name}: not read: IsADirectoryError$"):
        read()


def test_the_ids_stored_are_those_with_a_snapshot(store: RawStore) -> None:
    """A folder left without a revision is not a stored document."""
    store.put(Page, page_responses(1), FETCHED, {})
    (store.root / "confluence" / "pages" / "999").mkdir()
    assert store.stored_ids(Page) == {"196845"}
