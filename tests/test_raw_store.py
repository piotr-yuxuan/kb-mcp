"""The raw store keeps whole snapshots by revision, and files once by digest."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters.raw_store import RawStore
from atlassian_offline_mcp.domain.content import Page

if TYPE_CHECKING:
    from pathlib import Path


def page(version: int) -> Page:
    """Return a page at a version."""
    moment = datetime(2026, 10, 20, tzinfo=UTC)
    return Page(
        id="196845",
        title="Probe",
        author=None,
        created=moment,
        updated=moment,
        url="/wiki/spaces/MFS/pages/196845",
        space_id="196613",
        version=version,
        status="current",
    )


def test_the_newest_snapshot_of_each_document_is_read_back(tmp_path: Path) -> None:
    """Of versions 9 and 10, version 10 is the one read back."""
    store = RawStore(tmp_path)
    for version in (9, 10):
        store.put(page(version), {"document.json": {"version": version}})
    [latest] = store.latest("confluence", "pages")
    assert store.responses(latest) == {"document.json": {"version": 10}}


def test_a_stored_revision_is_not_written_again(tmp_path: Path) -> None:
    """A revision is immutable: storing it again keeps the first."""
    store = RawStore(tmp_path)
    first = store.put(page(1), {"document.json": {"seen": "first"}})
    again = store.put(page(1), {"document.json": {"seen": "second"}})
    assert again == first
    assert store.responses(first) == {"document.json": {"seen": "first"}}


def test_an_unfinished_snapshot_is_never_read(tmp_path: Path) -> None:
    """A hidden folder left by a crash is not a snapshot."""
    store = RawStore(tmp_path)
    store.put(page(1), {"document.json": {}})
    (store.folder(page(2)).parent / ".000002.crashed").mkdir()
    [latest] = store.latest("confluence", "pages")
    assert latest == store.folder(page(1))


def test_a_response_name_that_is_not_a_plain_json_file_is_refused(tmp_path: Path) -> None:
    """A response name cannot place a file outside its snapshot."""
    with pytest.raises(ValueError, match="not plain JSON file names"):
        RawStore(tmp_path).put(page(1), {"../escape.json": {}})


def test_a_file_is_stored_once_under_its_digest(tmp_path: Path) -> None:
    """The same bytes stored twice make one file, named by their SHA-256."""
    store = RawStore(tmp_path)
    digest = store.put_blob(b"image bytes")
    assert digest == hashlib.sha256(b"image bytes").hexdigest()
    assert store.put_blob(b"image bytes") == digest
    assert store.blob(digest).read_bytes() == b"image bytes"
    assert [path.name for path in store.blob(digest).parent.iterdir()] == [digest]


def test_an_empty_store_has_no_snapshots(tmp_path: Path) -> None:
    """A store that was never written has nothing to read."""
    assert list(RawStore(tmp_path).latest("jira", "issues")) == []
