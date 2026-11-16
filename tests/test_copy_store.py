"""The work log's copy store: plan 060's step 1, its file and its writers' lock, per source.

Expectations come from the plan's "The copy store" and the data layout's section on it:
for each document, its type, properties, text and org file; the revision, the digest of
the text alone; the dates carried over from the mirror; the as-of time; one
file per source, replaced whole, written by one run at a time.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from kb_mcp.config.domain.settings import Settings
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.names import RefusedError
from kb_mcp.sources.worklog.fetch.adapters.copy_store import COPIES, CopyStore, CopyStoreBusyError
from kb_mcp.sources.worklog.fetch.domain.copies import Carried, Copies, WorklogCopy

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

DAY = datetime(2026, 10, 27, tzinfo=UTC)
SEEN = datetime(2026, 10, 22, 6, 0, 1, 250_000, tzinfo=UTC)
MEETING = WorklogCopy(
    type="meeting",
    id="m-20261027-payments-stand-up",
    title="Payments stand-up",
    status="current",
    labels=("work",),
    breadcrumb=("todo.org", "Entries", "<2026-10-27 Tue>"),
    people=("Alex Example", "Kim (ops, payments)"),
    links=(("transcript", "t-20261027-1"),),
    created=DAY,
    updated=DAY,
    file="todo.org",
    text="#+TODO: TODO | DONE\n* Payments stand-up\nCafé, \N{LINE SEPARATOR} and \U0001f600.\n",
)
ENTRY = WorklogCopy(
    type="entry",
    id="e-0b0fba6d93b9dce8",
    title="Tidy the runbooks folder",
    status="TODO",
    labels=(),
    breadcrumb=("todo.org",),
    people=(),
    links=(),
    created=SEEN,
    updated=SEEN,
    file="todo.org",
    text="* TODO Tidy the runbooks folder\n",
)
CARRIED = "t-20261021-notes-on-x"
HELD = Copies(
    documents={MEETING.id: MEETING, ENTRY.id: ENTRY},
    migrated={
        CARRIED: Carried(
            path=f"worklog/transcripts/{CARRIED}-notes-on-the-ledger.md", created=SEEN, updated=DAY
        )
    },
    as_of=SEEN,
)


@pytest.fixture
def store(tmp_path: Path) -> CopyStore:
    """Give a work log's copy store, in a data folder of its own."""
    return CopyStore(Settings(data_dir=tmp_path / "data").copies, "worklog")


def test_what_is_put_reads_back_whole_in_its_order(store: CopyStore) -> None:
    """Every field, the documents in their order, times to the microsecond, any text."""
    with store.writing():
        store.put(HELD)
    found = store.read()
    assert found == HELD
    assert found is not None
    assert list(found.documents) == [MEETING.id, ENTRY.id]
    before = copy.replace(HELD, as_of=None, migrated={})
    with store.writing():
        store.put(before)
    assert store.read() == before


def test_a_store_never_written_reads_as_none(store: CopyStore) -> None:
    """None, which a fetch tells from a store that holds no document."""
    assert store.read() is None
    with store.writing():
        store.put(Copies(documents={}, migrated={}, as_of=None))
    assert store.read() == Copies(documents={}, migrated={}, as_of=None)


def test_the_revision_is_the_digest_of_the_text_alone() -> None:
    """The first 16 hex digits of the text's SHA-256: no converter, no property is in it."""
    expected = hashlib.sha256(MEETING.text.encode()).hexdigest()[:16]
    assert MEETING.revision == expected
    assert copy.replace(MEETING, title="Another title", labels=()).revision == expected


def test_it_lies_in_its_source_s_folder_of_the_copy_stores(tmp_path: Path) -> None:
    """<data>/copies/<source>/copies.json, a folder per source, judged with the others."""
    settings = Settings(data_dir=tmp_path / "data")
    store = CopyStore(settings.copies, "notes")
    with store.writing():
        store.put(HELD)
    assert (tmp_path / "data" / "copies" / "notes" / COPIES).is_file()
    assert settings.copies in settings.parts


def test_writing_needs_the_lock_and_one_writer_holds_it(store: CopyStore) -> None:
    """A put outside writing() is refused; a second writer is refused while the first holds."""
    with pytest.raises(RuntimeError, match="only inside"):
        store.put(HELD)
    with (
        store.writing(),
        pytest.raises(CopyStoreBusyError),
        CopyStore(store.folder.parent, "worklog").writing(),
    ):
        pass
    with store.writing():
        store.put(HELD)


def test_each_source_has_its_own_file_and_lock(store: CopyStore) -> None:
    """Two work logs: one writing leaves the other free, and neither reads the other's."""
    other = CopyStore(store.folder.parent, "notes")
    with store.writing(), other.writing():
        store.put(HELD)
    assert (store.read(), other.read()) == (HELD, None)


def test_a_write_that_fails_leaves_the_last_whole_file_and_no_hidden_one(
    store: CopyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Written aside then renamed: a failure before the rename changes nothing."""
    with store.writing():
        store.put(HELD)
    before = (store.folder / COPIES).read_bytes()

    def failing(_descriptor: int) -> None:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(os, "fsync", failing)
    with store.writing(), pytest.raises(OSError, match="disk full"):
        store.put(copy.replace(HELD, as_of=None))
    assert (store.folder / COPIES).read_bytes() == before
    assert sorted(path.name for path in store.folder.iterdir()) == [".lock", COPIES]


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda _: b"{not json", "worklog/copies.json: not JSON"),
        (lambda _: b"\xff\xfe", "worklog/copies.json: not JSON"),
        (lambda _: b"[]", "worklog/copies.json: expected an object"),
        (
            lambda value: {**value, "as_of": "yesterday"},
            "worklog/copies.json.as_of: expected an ISO 8601 time with an offset",
        ),
        (
            lambda value: {k: v for k, v in value.items() if k != "migrated"},
            "worklog/copies.json.migrated: missing",
        ),
        (
            lambda value: {**value, "migrated": {CARRIED: {"created": SEEN.isoformat()}}},
            f"worklog/copies.json.migrated.{CARRIED}.path: missing",
        ),
        (
            lambda value: {**value, "documents": [{**value["documents"][0], "id": "d-x"}]},
            "worklog/copies.json.documents[0]: id: does not match",
        ),
        (
            lambda value: {
                **value,
                "documents": [{k: v for k, v in value["documents"][0].items() if k != "text"}],
            },
            "worklog/copies.json.documents[0].text: missing",
        ),
        (
            lambda value: {
                **value,
                "documents": [
                    {**value["documents"][0], "links": [{"relation": "x", "document": "t-1"}]}
                ],
            },
            "worklog/copies.json.documents[0]: links: a relation not of RELATIONS",
        ),
        (
            lambda value: {**value, "documents": value["documents"][:1] * 2},
            "worklog/copies.json.documents[1]: id: given twice",
        ),
    ],
    ids=[
        "not JSON",
        "not UTF-8",
        "not an object",
        "a time",
        "a field missing",
        "a carried path missing",
        "an id off its rule",
        "a document's field missing",
        "a relation",
        "one id twice",
    ],
)
def test_a_store_that_does_not_read_is_refused_by_its_path_never_its_content(
    store: CopyStore, change: Callable[[dict[str, Any]], object], said: str
) -> None:
    """Named from the stores' root, then the field and the rule; the store is never guessed."""
    with store.writing():
        store.put(HELD)
    path = store.folder / COPIES
    changed = change(json.loads(path.read_bytes()))
    path.write_bytes(changed if isinstance(changed, bytes) else json.dumps(changed).encode())
    with pytest.raises(RepresentationError) as refused:
        store.read()
    assert str(refused.value).startswith(said)
    assert "Payments" not in str(refused.value)


def test_a_copy_off_the_work_log_s_rules_is_refused() -> None:
    """A type of another connector, a day bearing a meeting's id, a link to no safe id."""
    with pytest.raises(RefusedError, match="type"):
        copy.replace(MEETING, type="page")
    with pytest.raises(RefusedError, match="id: does not match"):
        copy.replace(MEETING, type="day")
    with pytest.raises(RefusedError, match="links: does not match"):
        copy.replace(MEETING, links=(("transcript", "../x"),))
    with pytest.raises(RefusedError, match="another id"):
        Copies(documents={ENTRY.id: MEETING}, migrated={}, as_of=None)
