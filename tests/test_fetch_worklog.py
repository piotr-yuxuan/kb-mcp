"""The work log's fetch: plan 060's step 2 and its migration, into the source's copy store.

Expectations come from the plan's decisions, as revised: the fetch reads the folder in
place and keeps each document's properties and text, its revision the digest of that
text alone; a file not read keeps its documents' last copies; a document missing from a
read without a problem is gone at once; only such a read sets the as-of time; a store's
first fetch carries over the created dates of the mirror before it reads, in today's
front matter or plan 058's. The mirror of ``fixtures/worklog_mirror/`` is what the
branch's base wrote from the fixture, with a pandoc that writes its input back.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from kb_mcp.config.domain.settings import Settings
from kb_mcp.kernel.outcome import Problem
from kb_mcp.mirror.adapters.markdown import dump, load
from kb_mcp.mirror.adapters.source_files import SOURCE_FILE
from kb_mcp.sources.declaration import Source
from kb_mcp.sources.registry import SOURCES
from kb_mcp.sources.stages import SourceRun
from kb_mcp.sources.worklog.declared import WORKLOG
from kb_mcp.sources.worklog.fetch.adapters.copy_store import COPIES, CopyStore
from kb_mcp.sources.worklog.fetch.app import fetcher, fetching
from kb_mcp.sources.worklog.fetch.app.fetching import WorklogFetched, fetch_worklog
from kb_mcp.sources.worklog.fetch.domain.copies import Carried
from kb_mcp.sources.worklog.settings import WorklogTable
from tests.test_prepare_worklog import (
    DOCUMENTS,
    FIXTURE,
    LATER,
    MODIFIED,
    NOT_UTF8,
    UNLINKED_MEETING,
    former,
    settle,
)

if TYPE_CHECKING:
    from kb_mcp.kernel.outcome import Outcome
    from kb_mcp.sources.worklog.fetch.domain.copies import Copies

# The mirror that the branch's base wrote from the fixture, as of MODIFIED.
MIRROR = Path(__file__).parent / "fixtures" / "worklog_mirror"
# When an undated entry was first seen, before the fixture's time.
SEEN = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
# When each fetch's read begins.
FIRST = datetime(2026, 11, 16, 8, 30, 0, 250_000, tzinfo=UTC)
SECOND = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
TIDY, READING, WAITING = "e-0b0fba6d93b9dce8", "e-ae8a4155d6acedf1", "t-d99a5f2dc74e8488"


class Fetch:
    """The work log's fetch over a copy of the fixture, into a data folder of its own."""

    def __init__(self, root: Path, data: Path) -> None:
        """Fetch the work log at ``root`` into the data folder ``data``."""
        self.root = root
        self.settings = Settings(data_dir=data)
        self.store = CopyStore(self.settings.copies, "worklog")

    def __call__(
        self, at: datetime = FIRST, *, dry_run: bool = False, archives: bool = True
    ) -> Outcome[WorklogFetched]:
        """Fetch, the read beginning at ``at``; return what the fetch did."""
        table = WorklogTable(path=self.root, archives=archives)
        return fetch_worklog(self.settings, table, "worklog", lambda: at, dry_run=dry_run)

    def held(self) -> Copies:
        """Read what the store holds, which a fetch wrote."""
        found = self.store.read()
        assert found is not None
        return found

    def edit(self, relative: str, old: str, new: str) -> None:
        """Replace text in a file of the work log, then set its time to LATER."""
        path = self.root / relative
        text = path.read_text("utf-8")
        assert old in text
        path.write_text(text.replace(old, new, 1), "utf-8")
        settle(path, LATER)

    def run(self, *, dry_run: bool = False) -> SourceRun:
        """Give a run of the work log's fetcher, at FIRST."""
        return SourceRun(
            source=Source(name="worklog", connector=WORKLOG),
            sources=SOURCES,
            settings=self.settings,
            source_table=WorklogTable(path=self.root),
            options={},
            now=lambda: FIRST,
            sleep=lambda _: None,
            dry_run=dry_run,
        )


@pytest.fixture
def fetch(tmp_path: Path) -> Fetch:
    """Copy the fixture's work log, at fixed times."""
    root = tmp_path / "todo"
    shutil.copytree(FIXTURE, root)
    settle(root)
    return Fetch(root, tmp_path / "data")


def counted(outcome: Outcome[WorklogFetched]) -> tuple[int, int, int, int]:
    """Give a fetch's counts of documents read, new, changed and gone."""
    assert outcome.counts is not None
    counts = outcome.counts
    return counts.documents, counts.new, counts.changed, counts.gone


def test_a_fetch_keeps_each_document_read_whole_its_text_s_digest_its_revision(
    fetch: Fetch,
) -> None:
    """Every document, its properties and text, the moment of the read as the as-of time."""
    outcome = fetch()
    held = fetch.held()
    assert (outcome.ending, counted(outcome), outcome.warnings) == (
        "done",
        (DOCUMENTS, DOCUMENTS, 0, 0),
        (UNLINKED_MEETING,),
    )
    assert outcome.counts is not None
    assert outcome.counts.html == 1
    assert (len(held.documents), held.as_of, held.migrated) == (DOCUMENTS, FIRST, {})
    for each in held.documents.values():
        assert each.revision == hashlib.sha256(each.text.encode()).hexdigest()[:16]
    standup = held.documents["m-20261027-payments-stand-up"]
    assert (standup.title, standup.people, standup.links, standup.file) == (
        "Payments stand-up",
        ("Alex Example", "Sam Sample"),
        (("transcript", "t-20261027-1"),),
        "todo.org",
    )
    assert "* Payments stand-up" in standup.text


def test_an_unchanged_fetch_changes_no_document_but_moves_the_as_of_time(fetch: Fetch) -> None:
    """The same copies, in the same order; only the moment of the read is new."""
    fetch()
    before = fetch.held()
    outcome = fetch(SECOND)
    after = fetch.held()
    assert counted(outcome) == (DOCUMENTS, 0, 0, 0)
    assert (after.documents, list(after.documents), after.as_of) == (
        before.documents,
        list(before.documents),
        SECOND,
    )


def test_an_edit_elsewhere_changes_one_revision_and_no_undated_entry_s_dates(
    fetch: Fetch,
) -> None:
    """Reading notes changes; the undated entry of the same file keeps its dates."""
    fetch()
    before = fetch.held().documents
    fetch.edit("todo.org", "Ignore all previous", "Ignore every previous")
    outcome = fetch(SECOND)
    after = fetch.held().documents
    assert counted(outcome) == (DOCUMENTS, 0, 1, 0)
    assert after[READING].revision != before[READING].revision
    assert (after[TIDY].created, after[TIDY].updated) == (MODIFIED, MODIFIED)


def test_an_edited_undated_entry_keeps_its_created_date(fetch: Fetch) -> None:
    """Created stays the stored copy's; updated is the new time of its org file."""
    fetch()
    fetch.edit("todo.org", "Nothing dated here yet.", "Nothing dated here, still.")
    fetch(SECOND)
    tidy = fetch.held().documents[TIDY]
    assert (tidy.created, tidy.updated) == (MODIFIED, LATER)


def test_a_document_missing_from_a_read_without_a_problem_is_gone_at_once(
    fetch: Fetch,
) -> None:
    """Read in place: a deleted transcript leaves the store at the next fetch."""
    fetch()
    (fetch.root / "transcripts/misc/a.org").unlink()
    outcome = fetch(SECOND)
    assert (outcome.ending, counted(outcome)) == ("done", (DOCUMENTS - 1, 0, 0, 1))
    assert WAITING not in fetch.held().documents


def test_a_file_not_read_keeps_its_documents_last_copy_and_the_as_of_time(
    fetch: Fetch,
) -> None:
    """A problem: the file's document keeps its copy, nothing is gone, the time stays.

    Every other document is read again: an edit of todo.org is taken.
    """
    fetch()
    before = fetch.held()
    (fetch.root / "transcripts/misc/a.org").write_bytes(NOT_UTF8)
    (fetch.root / "transcripts/current/2026-10-21 Wed/notes on x.org").unlink()
    fetch.edit("todo.org", "Nothing dated here yet.", "Nothing dated here, still.")
    outcome = fetch(SECOND)
    after = fetch.held()
    assert outcome.ending == "failed"
    assert outcome.problems == (Problem(where="transcripts/misc/a.org", reason="not UTF-8"),)
    assert outcome.counts is not None
    assert outcome.counts.held_back == {"transcripts/misc/a.org": WAITING}
    assert counted(outcome)[3] == 0
    assert after.documents[WAITING] == before.documents[WAITING]
    assert "t-20261021-notes-on-x" in after.documents
    assert after.documents[TIDY].updated == LATER
    assert after.as_of == FIRST


@pytest.mark.parametrize("name", ["todo.org", "todo.org_archive"])
def test_a_journal_file_not_read_keeps_every_copy(fetch: Fetch, name: str) -> None:
    """Every document draws on the journal: none is taken, not even a transcript edited."""
    fetch()
    before = fetch.held()
    (fetch.root / name).write_bytes(NOT_UTF8)
    fetch.edit("transcripts/misc/a.org", "one word only", "one edited word only")
    outcome = fetch(SECOND)
    assert [each.where for each in outcome.problems] == [name]
    assert fetch.held() == before


def test_a_dry_run_writes_nothing_and_counts_what_a_fetch_would_change(fetch: Fetch) -> None:
    """Nothing at first, not even the carried dates; then one edit and one deletion."""
    planned = fetch(dry_run=True)
    assert (planned.ending, counted(planned)) == ("not run", (DOCUMENTS, DOCUMENTS, 0, 0))
    assert not fetch.settings.copies.exists()
    fetch()
    written = (fetch.store.folder / COPIES).read_bytes()
    fetch.edit("todo.org", "Drafted on", "First drafted on")
    (fetch.root / "transcripts/misc/a.org").unlink()
    planned = fetch(SECOND, dry_run=True)
    assert (planned.ending, counted(planned)) == ("not run", (DOCUMENTS - 1, 0, 1, 1))
    assert (fetch.store.folder / COPIES).read_bytes() == written


def test_the_fetcher_refuses_a_work_log_that_is_not_a_folder(fetch: Fetch) -> None:
    """By its setting, before any source starts."""
    assert fetcher.preflight(fetch.run()) is None
    (fetch.root / "todo.org").rename(fetch.root.parent / "elsewhere.org")
    shutil.rmtree(fetch.root)
    assert fetcher.preflight(fetch.run()) == "sources.worklog.path: not a folder"


def test_a_busy_store_fails_the_fetch_saying_so(fetch: Fetch) -> None:
    """Another run writes it: the fetch fails before it reads, an error names the source."""
    with fetch.store.writing(), capture_logs() as logged:
        outcome = fetcher.fetch(fetch.run())
    assert (outcome.ending, outcome.problems) == (
        "failed",
        (Problem(where="copy store", reason=fetcher.BUSY),),
    )
    (busy,) = [each for each in logged if each["event"] == "fetch.store_busy"]
    assert (busy["log_level"], busy["source"]) == ("error", "worklog")
    assert fetch.store.read() is None


def test_a_store_that_does_not_read_fails_the_fetch_naming_it(fetch: Fetch) -> None:
    """By its file and why, never its content; the store stays as it is, for the user."""
    fetch.store.folder.mkdir(parents=True)
    (fetch.store.folder / COPIES).write_text("{not json", "utf-8")
    with capture_logs() as logged:
        outcome = fetcher.fetch(fetch.run())
    assert (outcome.ending, outcome.problems) == (
        "failed",
        (Problem(where="copy store", reason="worklog/copies.json: not JSON"),),
    )
    (refused,) = [each for each in logged if each["event"] == "fetch.refused"]
    assert (refused["source"], refused["reason"]) == ("worklog", "worklog/copies.json: not JSON")
    assert (fetch.store.folder / COPIES).read_text("utf-8") == "{not json"


def test_the_fetcher_says_each_problem_and_what_it_held_back(fetch: Fetch) -> None:
    """worklog.problem by place, reason and what keeps its last copy; nothing gone."""
    fetch()
    (fetch.root / "transcripts/misc/a.org").write_bytes(NOT_UTF8)
    with capture_logs() as logged:
        outcome = fetcher.fetch(fetch.run())
    assert outcome.ending == "failed"
    (problem,) = [each for each in logged if each["event"] == "worklog.problem"]
    assert (problem["where"], problem["reason"], problem["held_back"]) == (
        "transcripts/misc/a.org",
        "not UTF-8",
        WAITING,
    )
    assert [each["problems"] for each in logged if each["event"] == "worklog.nothing_removed"] == [
        1
    ]


def mirrored(docs: Path, *, change: bool = False) -> dict[str, tuple[datetime, datetime]]:
    """Copy the base's mirror into ``docs``, in plan 058's front matter if ``change``.

    Give each document's created and updated dates, by id, as that mirror holds them.
    """
    dates: dict[str, tuple[datetime, datetime]] = {}
    for path in sorted(MIRROR.rglob("*.md")):
        target = docs / path.relative_to(MIRROR)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text("utf-8")
        target.write_text(former(text) if change else text, "utf-8")
        matter, _ = load(text, path.name)
        dates[matter.id] = (matter.created, matter.updated)
    return dates


@pytest.mark.parametrize("change", [False, True], ids=["today's", "plan 058's"])
def test_a_store_s_first_fetch_carries_over_every_date_of_the_mirror(
    fetch: Fetch, *, change: bool
) -> None:
    """Plan 060, criterion 3, at the store: the org files' times have moved on.

    So that a date taken afresh would differ from the one that the mirror held, an
    undated entry's among them, first seen earlier than its file's last change: each
    document read takes both dates of its file, its text taken as theirs.
    """
    dates = mirrored(fetch.settings.docs)
    (tidy,) = (fetch.settings.docs / "worklog" / "entries").glob(f"{TIDY}-*.md")
    matter, body = load(tidy.read_text("utf-8"), tidy.name)
    tidy.write_text(dump(copy.replace(matter, created=SEEN), body), "utf-8")
    for each in (fetch.settings.docs / "worklog").rglob("*.md") if change else ():
        each.write_text(former(each.read_text("utf-8")), "utf-8")
    settle(fetch.root, LATER)
    with capture_logs() as logged:
        outcome = fetch()
    held = fetch.held()
    assert (outcome.ending, held.migrated) == ("done", {})
    assert {key: (each.created, each.updated) for key, each in held.documents.items()} == (
        dates | {TIDY: (SEEN, matter.updated)}
    )
    (carried,) = [each for each in logged if each["event"] == "worklog.carried"]
    assert (carried["documents"], carried["not_read"]) == (DOCUMENTS, 0)


def test_a_store_s_first_fetch_reads_the_work_log_s_folders_of_the_mirror_alone(
    fetch: Fetch,
) -> None:
    """Those of its document types, which the prepare owns: a copy moved aside is not read.

    The copy, of an undated entry under another date, would else give its date.
    """
    dates = mirrored(fetch.settings.docs)
    (tidy,) = (fetch.settings.docs / "worklog" / "entries").glob(f"{TIDY}-*.md")
    matter, body = load(tidy.read_text("utf-8"), tidy.name)
    aside = fetch.settings.docs / "worklog" / "old" / tidy.name
    aside.parent.mkdir()
    aside.write_text(dump(copy.replace(matter, created=SEEN), body), "utf-8")
    (fetch.settings.docs / "worklog" / "old" / "notes.md").write_text("not a document\n", "utf-8")
    settle(fetch.root, LATER)
    with capture_logs() as logged:
        outcome = fetch()
    assert (outcome.ending, fetch.held().documents[TIDY].created) == ("done", dates[TIDY][0])
    (carried,) = [each for each in logged if each["event"] == "worklog.carried"]
    assert (carried["documents"], carried["not_read"]) == (DOCUMENTS, 0)


def test_the_carried_dates_are_kept_while_a_file_is_not_read(fetch: Fetch) -> None:
    """Plan 060: one org file not read at the first fetch; its date waits until it is read."""
    dates = mirrored(fetch.settings.docs)
    settle(fetch.root, LATER)
    text = (fetch.root / "transcripts/misc/a.org").read_bytes()
    (fetch.root / "transcripts/misc/a.org").write_bytes(NOT_UTF8)
    assert fetch().ending == "failed"
    held = fetch.held()
    assert WAITING not in held.documents
    assert {key: (each.created, each.updated) for key, each in held.migrated.items()} == {
        WAITING: dates[WAITING]
    }
    (fetch.root / "transcripts/misc/a.org").write_bytes(text)
    settle(fetch.root / "transcripts/misc/a.org", LATER)
    assert fetch(SECOND).ending == "done"
    held = fetch.held()
    waiting = held.documents[WAITING]
    assert ((waiting.created, waiting.updated), held.migrated) == (dates[WAITING], {})


def test_the_carried_dates_are_written_before_the_read(
    fetch: Fetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In one step, whatever the read then meets, even a failure that ends the run.

    Each with the path of the file where it was found, from the mirror's folder.
    """
    dates = mirrored(fetch.settings.docs)
    paths = {
        load(path.read_text("utf-8"), path.name)[0].id: path.relative_to(MIRROR).as_posix()
        for path in MIRROR.rglob("*.md")
    }

    def failing(*_: object, **__: object) -> None:
        message = "the read fails"
        raise RuntimeError(message)

    monkeypatch.setattr(fetching, "read_worklog", failing)
    with pytest.raises(RuntimeError, match="the read fails"):
        fetch()
    assert fetch.held().migrated == {
        key: Carried(path=paths[key], created=created, updated=updated)
        for key, (created, updated) in dates.items()
    }


def test_a_file_of_the_mirror_that_does_not_read_fails_the_fetch_its_dates_lost(
    fetch: Fetch,
) -> None:
    """A problem by its path in the mirror, never its content, so that the loss is loud.

    Every document is read, that one dated afresh, but as by any problem, the read is not
    the as-of time; the next fetch, its store begun, meets no such problem.
    """
    dates = mirrored(fetch.settings.docs)
    damaged = next((fetch.settings.docs / "worklog" / "entries").glob(f"{TIDY}-*.md"))
    damaged.write_text("not a file of the mirror, secret\n", "utf-8")
    path = damaged.relative_to(fetch.settings.docs).as_posix()
    settle(fetch.root, LATER)
    with capture_logs() as logged:
        outcome = fetcher.fetch(fetch.run())
    reason = f"{path}: no front matter; its dates are not carried over"
    assert (outcome.ending, outcome.problems, outcome.warnings) == (
        "failed",
        (Problem(where=path, reason=reason),),
        (UNLINKED_MEETING,),
    )
    (problem,) = [each for each in logged if each["event"] == "worklog.problem"]
    assert (problem["where"], problem["held_back"]) == (path, fetching.NOTHING)
    assert "secret" not in repr(logged)
    held = fetch.held()
    assert (len(held.documents), held.as_of) == (len(dates), None)
    assert (held.documents[TIDY].created, held.documents[TIDY].updated) == (LATER, LATER)
    assert (fetch(SECOND).ending, fetch.held().as_of) == ("done", SECOND)


def test_a_source_s_file_of_the_mirror_that_does_not_read_fails_the_first_fetch(
    fetch: Fetch,
) -> None:
    """By its path, never its content: its as-of time is lost, every date carried over."""
    dates = mirrored(fetch.settings.docs)
    path = f"worklog/{SOURCE_FILE}"
    (fetch.settings.docs / path).write_text('{"secret', "utf-8")
    outcome = fetch()
    (problem,) = outcome.problems
    assert (outcome.ending, problem.where, problem.reason.startswith(f"{path}: not JSON")) == (
        "failed",
        path,
        True,
    )
    assert "secret" not in problem.reason
    assert outcome.counts is not None
    assert outcome.counts.held_back == {path: fetching.NOTHING}
    held = fetch.held()
    assert (
        held.as_of,
        {key: (each.created, each.updated) for key, each in held.documents.items()},
    ) == (
        None,
        dates,
    )


def test_two_work_logs_keep_a_store_each(fetch: Fetch, tmp_path: Path) -> None:
    """Plan 060, at 059's merge: each source its own store, dates and as-of time.

    A problem of one leaves the other's as-of time to move on.
    """
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "todo.org").write_text("* An entry of the notes\n", "utf-8")
    settle(notes)
    table = WorklogTable(path=notes)
    fetch()
    assert (
        fetch_worklog(fetch.settings, table, "notes", lambda: SECOND, dry_run=False).problems == ()
    )
    other = CopyStore(fetch.settings.copies, "notes").read()
    assert other is not None
    assert ([each.title for each in other.documents.values()], other.as_of) == (
        ["An entry of the notes"],
        SECOND,
    )
    (fetch.root / "todo.org").write_bytes(NOT_UTF8)
    assert fetch(SECOND).problems
    assert (
        fetch_worklog(fetch.settings, table, "notes", lambda: LATER, dry_run=False).problems == ()
    )
    assert fetch.held().as_of == FIRST
    other = CopyStore(fetch.settings.copies, "notes").read()
    assert other is not None
    assert other.as_of == LATER
    stored = json.loads((fetch.settings.copies / "notes" / COPIES).read_bytes())
    assert [each["id"] for each in stored["documents"]] == list(other.documents)
