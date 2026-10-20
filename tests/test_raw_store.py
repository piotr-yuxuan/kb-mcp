"""The raw store keeps whole snapshots by revision, and files once by digest."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters import confluence_v2, jira_v3
from atlassian_offline_mcp.adapters.fields import RepresentationError
from atlassian_offline_mcp.adapters.raw_store import RawStore
from tests.samples import v2_attachment, v2_page, v2_view, v3_comment, v3_issue

if TYPE_CHECKING:
    from pathlib import Path

FETCHED = datetime(2026, 10, 22, 9, 15, tzinfo=timezone(timedelta(hours=1)))
NEWER = 10


def page_responses(version: int, **changes: object) -> dict[str, object]:
    """Return the responses of a page's snapshot at a version, with one attachment."""
    stamp = {"number": version, "createdAt": "2026-10-20T21:52:41Z"}
    return {
        confluence_v2.DOCUMENT: v2_page(version=stamp, **changes),
        confluence_v2.VIEW: v2_view(version=stamp),
        confluence_v2.ATTACHMENTS: [v2_attachment()],
    }


def put_page(store: RawStore, version: int, **changes: object) -> Path:
    """Store a page's snapshot at a version, without files, and return its folder."""
    return store.put("confluence", "pages", page_responses(version, **changes), FETCHED, {}).folder


def test_the_newest_snapshot_of_each_document_is_read_back(tmp_path: Path) -> None:
    """Of versions 9 and 10, version 10 is the one read back."""
    store = RawStore(tmp_path)
    put_page(store, 9)
    put_page(store, NEWER)
    [latest] = store.latest("confluence", "pages")
    assert latest.snapshot.document.revision == "000010"


def test_a_snapshot_reads_back_as_the_domain_with_its_record(tmp_path: Path) -> None:
    """What was stored comes back read by its adapter, fetched at the time given, in UTC."""
    store = RawStore(tmp_path)
    put_page(store, 3)
    [stored] = store.latest("confluence", "pages")
    assert stored.snapshot.html == "<p>Hello, rendered</p>"
    assert stored.fetched_at == datetime(2026, 10, 22, 8, 15, tzinfo=UTC)
    assert stored.blobs == {}
    assert set(store.responses(stored.folder)) == {
        confluence_v2.DOCUMENT,
        confluence_v2.VIEW,
        confluence_v2.ATTACHMENTS,
    }


def test_issues_are_stored_by_their_id_and_update_time(tmp_path: Path) -> None:
    """An issue's folder is its id, and its revision its update time in UTC."""
    store = RawStore(tmp_path)
    responses = {jira_v3.ISSUE: v3_issue(), jira_v3.COMMENTS: [v3_comment()]}
    stored = store.put("jira", "issues", responses, FETCHED, {})
    assert stored.folder == tmp_path / "jira" / "issues" / "10000" / "20261020T213758.027000Z"


def test_a_stored_revision_is_not_written_again(tmp_path: Path) -> None:
    """A revision is immutable: storing it again keeps the first."""
    store = RawStore(tmp_path)
    put_page(store, 1, title="First")
    put_page(store, 1, title="Second")
    [stored] = store.latest("confluence", "pages")
    assert stored.snapshot.document.title == "First"


def test_a_snapshot_that_fails_while_written_leaves_nothing(tmp_path: Path) -> None:
    """A snapshot is stored whole or not at all, with no hidden folder left behind."""
    store = RawStore(tmp_path)
    responses = {**page_responses(1), "unwritable.json": object()}
    with pytest.raises(TypeError):
        store.put("confluence", "pages", responses, FETCHED, {})
    assert list(store.latest("confluence", "pages")) == []
    assert list((tmp_path / "confluence" / "pages" / "196845").iterdir()) == []


def test_responses_that_their_adapter_refuses_are_not_stored(tmp_path: Path) -> None:
    """Nothing unreadable is stored: a snapshot without its view is refused."""
    store = RawStore(tmp_path)
    responses = page_responses(1)
    del responses[confluence_v2.VIEW]
    with pytest.raises(RepresentationError, match=r"^view\.json: "):
        store.put("confluence", "pages", responses, FETCHED, {})
    assert not (tmp_path / "confluence").exists()


def test_hidden_folders_and_stray_files_are_not_snapshots(tmp_path: Path) -> None:
    """A crash's hidden folder and Finder's .DS_Store are skipped, at every level."""
    store = RawStore(tmp_path)
    folder = put_page(store, 1)
    (folder.parent / ".000002.crashed").mkdir()
    (folder.parent / "notes.txt").write_text("", "utf-8")
    (folder.parent.parent / ".DS_Store").write_text("", "utf-8")
    assert [stored.folder for stored in store.latest("confluence", "pages")] == [folder]


@pytest.mark.parametrize("name", ["../escape.json", "plain", "store.json"])
def test_a_response_name_that_is_not_a_plain_json_file_is_refused(
    tmp_path: Path, name: str
) -> None:
    """A response name cannot place a file outside its snapshot, nor be the store's own."""
    with pytest.raises(ValueError, match="not plain JSON file names"):
        RawStore(tmp_path).put("confluence", "pages", {**page_responses(1), name: {}}, FETCHED, {})


def test_blobs_must_be_stored_files_of_the_snapshot_attachments(tmp_path: Path) -> None:
    """A snapshot never names a file that is not stored, nor one of another attachment."""
    store = RawStore(tmp_path)
    digest = hashlib.sha256(b"never stored").hexdigest()
    with pytest.raises(ValueError, match="blobs:"):
        store.put("confluence", "pages", page_responses(1), FETCHED, {"att196895": digest})
    stored = store.put_blob(b"image bytes")
    with pytest.raises(ValueError, match="blobs:"):
        store.put("confluence", "pages", page_responses(1), FETCHED, {"att1": stored})


def test_a_file_downloaded_later_is_added_to_its_snapshot(tmp_path: Path) -> None:
    """A file that failed on the first run is recorded when a later run downloads it."""
    store = RawStore(tmp_path)
    document = store.put("confluence", "pages", page_responses(1), FETCHED, {}).snapshot.document
    digest = store.put_blob(b"image bytes")
    stored = store.add_blobs(document, {"att196895": digest})
    assert stored.blobs == {"att196895": digest}
    assert stored.fetched_at == FETCHED
    assert store.read(document).blobs == {"att196895": digest}


def test_a_file_is_stored_once_under_its_digest(tmp_path: Path) -> None:
    """The same bytes stored twice make one file, named by their SHA-256."""
    store = RawStore(tmp_path)
    digest = store.put_blob(b"image bytes")
    assert digest == hashlib.sha256(b"image bytes").hexdigest()
    assert store.put_blob(b"image bytes") == digest
    assert store.blob(digest).read_bytes() == b"image bytes"
    assert [path.name for path in store.blob(digest).parent.iterdir()] == [digest]


def test_a_digest_that_is_a_path_is_refused(tmp_path: Path) -> None:
    """A digest read from a record cannot name a file outside the blobs."""
    with pytest.raises(ValueError, match="not a SHA-256 digest"):
        RawStore(tmp_path).blob("../../../x")


def test_an_empty_store_has_no_snapshots(tmp_path: Path) -> None:
    """A store that was never written has nothing to read."""
    assert list(RawStore(tmp_path).latest("jira", "issues")) == []


def test_a_listing_is_replaced_whole(tmp_path: Path) -> None:
    """The newest listing replaces the last; one never stored reads as None."""
    store = RawStore(tmp_path)
    assert store.listing("confluence", "pages-196613") is None
    store.put_listing("confluence", "pages-196613", [v2_page(), v2_page(id="196846")])
    store.put_listing("confluence", "pages-196613", [v2_page()])
    [result] = store.listing("confluence", "pages-196613") or []
    assert confluence_v2.document(result, confluence_v2.Page).id == "196845"
    assert [path.name for path in (tmp_path / "confluence" / "listings").iterdir()] == [
        "pages-196613.json"
    ]


@pytest.mark.parametrize(("source", "name"), [("confluence", "../pages"), ("../x", "spaces")])
def test_a_listing_outside_the_listings_is_refused(tmp_path: Path, source: str, name: str) -> None:
    """Neither a listing's source nor its name can place it elsewhere."""
    store = RawStore(tmp_path)
    with pytest.raises(ValueError, match="not a source and a listing name"):
        store.put_listing(source, name, [])
    with pytest.raises(ValueError, match="not a source and a listing name"):
        store.listing(source, name)
