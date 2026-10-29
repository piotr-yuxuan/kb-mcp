"""The work log mirrored end to end: plan 017's criteria 7 to 12, through its step.

The fixture, ``fixtures/worklog/``, is invented, as the plan's acceptance criteria
describe it; Emacs's lock, autosave and backup files are added to each copy, since git
ignores them. Times are fixed by ``os.utime``. Expectations come from the plan's tables,
written by hand, and every file is read back by ``markdown.load``. Plan 042's journal of
two days, its archived parts and its meetings are expected as its "Days and meetings:
the rule", "Ids" and criterion 4 describe them; its transcripts, the meeting file under
``meetings/`` among them, as its "Ids", "Dates" and "Participants" and criteria 5, 6
and 8 do.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from atlassian_offline_mcp.mirror.adapters.markdown import load
from atlassian_offline_mcp.mirror.adapters.mirror_files import owned, sync
from atlassian_offline_mcp.mirror.adapters.pandoc import ORG, VERSION, Pandoc, PandocFailedError
from atlassian_offline_mcp.mirror.app.worklog import (
    Outcome,
    Planned,
    mirror_worklog,
    plan_worklog,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter

FIXTURE = Path(__file__).parent / "fixtures" / "worklog"
# The fixture's time: in every zone from UTC-12 to UTC+14, its wall clock falls between
# the fixture's last past event (the 19th) and its first plan (the 23rd).
MODIFIED = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
NOT_UTF8 = b"* Emacs \xff\xfe never read\n"
HASHED = re.compile(r"t-[0-9a-f]{16}")
DAY = "transcripts/current/2026-10-20 Tue"
ARCHIVED_DAY = "transcripts/archive/2026/2026-10/2026-10-20 Tue"
ENTRIES = [
    "From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)",
    "Hand-over checklist",
    "Old incident log",
    "Payout gateway rollback runbook",
    "Plan the next quarter",
    "Private scratch",
    "Reading notes",
    "Retrospective notes",
    "Retrospective notes",
    "Review the ledger migration",
    "Tidy the runbooks folder",
    "Vendor contract renewal",
    "Weekly sync with the platform team",
]
TRANSCRIPTS = [
    "Notes on the ledger",
    "Payments stand-up",
    "Payments stand-up, 27 October",
    "Transcript, 2026-09-15 Tue, 1",
    "Vendor call, 27 October",
    "WAITING Notes",
]
# The journal's days, by id, and its meetings, by id and title: those of the archive last.
DAYS = ["d-20261026", "d-20261027"]
MEETINGS = {
    "m-20261026-one-to-one": "One-to-one",
    "m-20261026-one-to-one--2": "One-to-one",
    "m-20261026-incident-review": "Incident review",
    "m-20261027-payments-stand-up": "Payments stand-up",
    "m-20261027-ledger-review": "Ledger review",
    "m-20261027-vendor-call": "Vendor call",
    "m-20261027-rollout-planning": "Rollout planning",
    "m-20261027-capacity-planning": "Capacity planning",
}
ARCHIVED_MEETINGS = {"Incident review", "Capacity planning"}
DOCUMENTS = len(ENTRIES) + len(TRANSCRIPTS) + len(DAYS) + len(MEETINGS)


@dataclass(frozen=True)
class Counting(Pandoc):
    """Pandoc, counting its runs by their arguments, and failing on a marker if given."""

    runs: list[tuple[str, ...]] = field(default_factory=list)
    failing: str | None = None

    def run(self, arguments: Sequence[str], text: str) -> str:
        """Count the run, then fail as pandoc would on the marker, or run pandoc."""
        self.runs.append(tuple(arguments))
        if self.failing is not None and self.failing in text:
            message = "pandoc: exit status 9"
            raise PandocFailedError(message)
        return super().run(arguments, text)


@dataclass(frozen=True)
class Mirrored:
    """A document's file: where, its front matter, its body."""

    path: str
    matter: FrontMatter
    body: str


@dataclass
class Run:
    """The work log's step over a copy of the fixture, into a data folder of its own.

    ``runs`` holds pandoc's runs of each mirroring, in order.
    """

    root: Path
    docs: Path
    runs: list[list[tuple[str, ...]]] = field(default_factory=list)

    def __call__(self, *, archives: bool = True, failing: str | None = None) -> Outcome:
        """Mirror the work log; return what the run did."""
        pandoc = Counting(Pandoc.find().path, failing=failing)
        outcome = mirror_worklog(self.root, self.docs, pandoc, archives=archives)
        self.runs.append(pandoc.runs)
        return outcome

    def plan(self, *, archives: bool = True) -> Planned:
        """Say what mirroring would do; pandoc's runs are recorded as for a run."""
        pandoc = Counting(Pandoc.find().path)
        planned = plan_worklog(self.root, self.docs, pandoc, archives=archives)
        self.runs.append(pandoc.runs)
        return planned

    def files(self) -> list[Mirrored]:
        """Read back every file of the work log's step, as search will."""
        found = sorted((self.docs / "worklog").rglob("*.md"))
        return [
            Mirrored(path.relative_to(self.docs).as_posix(), *load(path.read_text("utf-8"), "x"))
            for path in found
        ]

    def by_title(self, title: str, kind: str | None = None) -> Mirrored:
        """Return the one file of this title, and of this type when given."""
        (found,) = [
            each
            for each in self.files()
            if each.matter.title == title and kind in (None, each.matter.type)
        ]
        return found

    def by_id(self, identifier: str) -> Mirrored:
        """Return the file of this id."""
        (found,) = [each for each in self.files() if each.matter.id == identifier]
        return found

    def edit(self, relative: str, old: str, new: str, moment: datetime = LATER) -> None:
        """Replace text in a file of the work log, then set its time."""
        path = self.root / relative
        text = path.read_text("utf-8")
        assert old in text
        path.write_text(text.replace(old, new, 1), "utf-8")
        settle(path, moment)


def settle(path: Path, moment: datetime = MODIFIED) -> None:
    """Set a file's times, or those of every file under a folder."""
    targets = [path] if path.is_file() else [each for each in path.rglob("*") if each.is_file()]
    for each in targets:
        os.utime(each, (moment.timestamp(), moment.timestamp()), follow_symlinks=False)


@pytest.fixture
def run(tmp_path: Path) -> Run:
    """Copy the fixture with Emacs's files beside a transcript, at fixed times."""
    root = tmp_path / "todo"
    shutil.copytree(FIXTURE, root)
    for name in (".#1.org", "#1.org#", "1.org~"):
        (root / DAY / name).write_bytes(NOT_UTF8)
    settle(root)
    return Run(root, tmp_path / "data" / "docs")


def identities(files: list[Mirrored]) -> list[tuple[str, str, tuple[str, ...]]]:
    """Return each file's id, path and people: two files that swap contents differ."""
    return sorted(
        (each.matter.id, each.path, tuple(person.name for person in each.matter.people))
        for each in files
    )


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Return every file under a folder, hidden ones too: its bytes and modification time."""
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_the_documents_are_the_entries_days_meetings_and_org_transcripts(run: Run) -> None:
    """Top-level headings and the journal's others, its days and meetings; one per .org.

    COMMENT and noexport headings are entries, with their text.
    """
    outcome = run()
    files = run.files()
    assert sorted(each.matter.title for each in files if each.matter.type == "entry") == ENTRIES
    assert sorted(each.matter.title for each in files if each.matter.type == "transcript") == (
        TRANSCRIPTS
    )
    assert sorted(each.matter.id for each in files if each.matter.type == "day") == DAYS
    meetings = {
        each.matter.id: each.matter.title for each in files if each.matter.type == "meeting"
    }
    assert meetings == MEETINGS
    assert (outcome.documents, outcome.html, outcome.problems, outcome.warnings) == (
        DOCUMENTS,
        1,
        (),
        (),
    )
    assert "Commented text that org would not publish." in run.by_title("Private scratch").body
    assert "Text tagged noexport" in run.by_title("Hand-over checklist").body
    assert all(each.matter.source == "worklog" for each in files)


def test_without_archives_the_archived_documents_and_text_go(run: Run) -> None:
    """The archive file's entries and meetings, the archived transcript, the ARCHIVE text."""
    run()
    outcome = run(archives=False)
    titles = {each.matter.title for each in run.files()}
    gone = {"Vendor contract renewal", "Old incident log", "Transcript, 2026-09-15 Tue, 1"}
    gone |= ARCHIVED_MEETINGS
    kept = {*ENTRIES, *TRANSCRIPTS, *MEETINGS.values(), "<2026-10-26 Mon>", "<2026-10-27 Tue>"}
    assert titles == kept - gone
    assert outcome.changes.removed == len(gone)
    assert "Archived text inside an entry." not in run.by_title("Reading notes").body
    assert all("Archived text" not in each.body for each in run.files())


@pytest.mark.parametrize(
    ("document", "status", "labels", "breadcrumb"),
    [
        (
            ("entry", "Review the ledger migration"),
            "WAITING",
            ("review", "ledger", "work"),
            ("todo.org",),
        ),
        (("entry", "Old incident log"), "current", ("ARCHIVE", "work"), ("todo.org",)),
        (
            ("entry", "Vendor contract renewal"),
            "WAITING",
            ("vendor", "ARCHIVE"),
            ("todo.org_archive",),
        ),
        (("entry", "Tidy the runbooks folder"), "TODO", ("work",), ("todo.org",)),
        (
            ("entry", "From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)"),
            "current",
            ("work",),
            ("todo.org", "Entries"),
        ),
        (("day", "<2026-10-27 Tue>"), "current", ("work",), ("todo.org", "Entries")),
        (("day", "<2026-10-26 Mon>"), "current", ("work", "ARCHIVE"), ("todo.org", "Entries")),
        (
            ("meeting", "Ledger review"),
            "current",
            ("work",),
            ("todo.org", "Entries", "<2026-10-27 Tue>"),
        ),
        (
            ("meeting", "Capacity planning"),
            "current",
            ("ARCHIVE",),
            ("todo.org_archive", "Entries", "<2026-10-27 Tue>"),
        ),
        (
            ("transcript", "Payments stand-up"),
            "current",
            ("standup",),
            ("transcripts", "current", "2026-10-20 Tue"),
        ),
        (
            ("transcript", "Transcript, 2026-09-15 Tue, 1"),
            "current",
            ("ARCHIVE",),
            ("transcripts", "archive", "2026", "2026-09", "2026-09-15 Tue"),
        ),
        (("transcript", "WAITING Notes"), "current", (), ("transcripts", "misc")),
        (
            ("transcript", "Vendor call, 27 October"),
            "current",
            (),
            ("meetings", "2026-10-27 Tue"),
        ),
    ],
)
def test_front_matter_says_status_labels_and_place(
    run: Run,
    document: tuple[str, str],
    status: str,
    labels: tuple[str, ...],
    breadcrumb: tuple[str, ...],
) -> None:
    """Keyword or current; tags, #+FILETAGS and ARCHIVE; the file and journal, or folders."""
    run()
    kind, title = document
    matter = run.by_title(title, kind).matter
    assert (matter.status, matter.labels, matter.breadcrumb) == (status, labels, breadcrumb)
    assert (matter.fetched_at, matter.key, matter.space, matter.url) == (MODIFIED, None, None, None)


@pytest.mark.parametrize(
    ("kind", "title", "created", "updated"),
    [
        ("entry", "Plan the next quarter", datetime(2026, 10, 14, 16, tzinfo=UTC), None),
        (
            "entry",
            "Review the ledger migration",
            datetime(2026, 10, 19, 10, tzinfo=UTC),
            datetime(2026, 10, 19, 11, 20, tzinfo=UTC),
        ),
        ("entry", "Tidy the runbooks folder", MODIFIED, None),
        ("transcript", "Payments stand-up", datetime(2026, 10, 20, tzinfo=UTC), None),
        ("transcript", "WAITING Notes", MODIFIED, None),
        ("day", "<2026-10-27 Tue>", datetime(2026, 10, 27, tzinfo=UTC), None),
        ("meeting", "Ledger review", datetime(2026, 10, 27, tzinfo=UTC), None),
        ("meeting", "Capacity planning", datetime(2026, 10, 27, tzinfo=UTC), None),
        (
            "transcript",
            "Payments stand-up, 27 October",
            datetime(2026, 10, 27, 9, 31, tzinfo=UTC),
            None,
        ),
        ("meeting", "Payments stand-up", datetime(2026, 10, 27, 9, 31, tzinfo=UTC), None),
        ("transcript", "Vendor call, 27 October", datetime(2026, 10, 27, 15, tzinfo=UTC), None),
        ("meeting", "Vendor call", datetime(2026, 10, 27, 15, tzinfo=UTC), None),
    ],
)
def test_dates_are_the_earliest_and_latest_events_up_to_the_file_time(
    run: Run, kind: str, title: str, created: datetime, updated: datetime | None
) -> None:
    """A later timestamp is a plan; no event, the file's time; a transcript, when it began.

    A transcript begins at its first turn's time, else at its day's timestamp, else at its
    day; a meeting with it. A day, and a meeting without a transcript, are their day,
    whatever their lines hold.
    """
    run()
    matter = run.by_title(title, kind).matter
    assert (matter.created, matter.updated) == (created, updated or created)


def test_transcript_ids_name_their_day_and_name_and_tell_the_two_folders_apart(
    run: Run,
) -> None:
    """A name with blanks by its slug; misc/a.org, without a day, by its name's digest.

    One day's 1.org under meetings/ and under transcripts/current/: two ids, no warning.
    """
    outcome = run()
    ids = {
        each.matter.title: each.matter.id
        for each in run.files()
        if each.matter.type == "transcript"
    }
    assert ids == {
        "Notes on the ledger": "t-20261021-notes-on-x",
        "WAITING Notes": f"t-{hashlib.sha256(b'a.org').hexdigest()[:16]}",
        "Payments stand-up": "t-20261020-1",
        "Payments stand-up, 27 October": "t-20261027-1",
        "Transcript, 2026-09-15 Tue, 1": "t-20260915-1",
        "Vendor call, 27 October": "t-20261027-meeting-1",
    }
    assert outcome.warnings == ()


def test_an_edited_undated_entry_keeps_its_creation(run: Run) -> None:
    """Created stays the existing file's; updated is the new time of its org file."""
    run()
    run.edit("todo.org", "Nothing dated here yet.", "Nothing dated here, still.")
    run()
    matter = run.by_title("Tidy the runbooks folder").matter
    assert (matter.created, matter.updated, matter.fetched_at) == (MODIFIED, LATER, LATER)


def test_an_edit_elsewhere_leaves_an_undated_entry_and_its_file(run: Run) -> None:
    """Its revision holds, so its file keeps its bytes, dates and time."""
    run()
    path = run.docs / run.by_title("Tidy the runbooks folder").path
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    run.edit("todo.org", "Ignore all previous", "Ignore every previous")
    outcome = run()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert outcome.changes.written == 1  # Reading notes alone


ARCHIVED_ENTRY = """* Plan the next quarter
  :PROPERTIES:
  :ARCHIVE_TIME: 2026-10-22 Thu 14:00
  :ARCHIVE_FILE: ~/todo/todo.org
  :ARCHIVE_CATEGORY: todo
  :END:
  Drafted on [2026-10-14 Wed 16:00].
  Review planned for <2030-01-15 Tue 09:00>.
"""


def archive_plan(run: Run) -> None:
    """Archive "Plan the next quarter" as org does: out of todo.org, with its properties."""
    plan = "* Plan the next quarter\n  Drafted on [2026-10-14 Wed 16:00].\n"
    plan += "  Review planned for <2030-01-15 Tue 09:00>.\n\n"
    run.edit("todo.org", plan, "")
    path = run.root / "todo.org_archive"
    path.write_text(path.read_text("utf-8") + "\n" + ARCHIVED_ENTRY, "utf-8")


def move_transcript(run: Run) -> None:
    """Move 1.org under transcripts/archive/."""
    (run.root / ARCHIVED_DAY).mkdir(parents=True)
    (run.root / DAY / "1.org").rename(run.root / ARCHIVED_DAY / "1.org")


def move_named(run: Run) -> None:
    """Move notes on x.org, whose name holds blanks, under transcripts/archive/."""
    archived = run.root / "transcripts/archive/2026/2026-10/2026-10-21 Wed"
    archived.mkdir(parents=True)
    (run.root / "transcripts/current/2026-10-21 Wed/notes on x.org").rename(
        archived / "notes on x.org"
    )


LEDGER_REVIEW = """*** Ledger review
:PROPERTIES:
:PARTICIPANTS: Robin Example, Kim (not in the header), Sam Sample
:END:
**** Summary
The ledger migration waits on the schema owner.
**** Actions
***** WAITING Ask the schema owner for a date
"""
# What org adds to an archived heading's drawer, after its own properties.
ARCHIVING = (
    ":ARCHIVE_TIME: 2026-10-28 Wed 10:00\n:ARCHIVE_FILE: ~/todo/todo.org\n"
    ":ARCHIVE_OLPATH: {}\n:ARCHIVE_CATEGORY: todo\n"
)


def archive(run: Run, text: str, path: str) -> None:
    """Archive a subtree of todo.org as org does: at level 1, its drawer told its path."""
    run.edit("todo.org", text, "")
    above = len(text) - len(text.lstrip("*")) - 1  # the levels above its first heading
    first, rest = re.sub(rf"(?m)^\*{{{above}}}(\*+ )", r"\1", text).split("\n", 1)
    drawer = ARCHIVING.format(path)
    if rest.startswith(":PROPERTIES:\n"):
        rest = rest.replace(":END:\n", drawer + ":END:\n", 1)
    else:
        rest = f":PROPERTIES:\n{drawer}:END:\n{rest}"
    archived = run.root / "todo.org_archive"
    archived.write_text(f"{archived.read_text('utf-8')}\n{first}\n{rest}", "utf-8")


def archive_meeting(run: Run) -> None:
    """Archive the ledger review alone, out of its day."""
    archive(run, LEDGER_REVIEW, "Entries/<2026-10-27 Tue>")


def archive_day(run: Run) -> None:
    """Archive the Tuesday whole, its meetings with it."""
    text = (run.root / "todo.org").read_text("utf-8")
    day = text[text.index("** <2026-10-27 Tue>\n") : text.index("** From <2026-10-05")]
    archive(run, day, "Entries")


def archive_monday(run: Run) -> None:
    """Archive the Monday whole, its two One-to-ones with it, in their order."""
    text = (run.root / "todo.org").read_text("utf-8")
    day = text[text.index("** <2026-10-26 Mon>\n") : text.index("** <2026-10-27 Tue>\n")]
    archive(run, day, "Entries")


@pytest.mark.parametrize(
    "change",
    [
        lambda run: run.edit("todo.org", "Drafted on", "First drafted on"),
        lambda run: run.edit("todo.org", "* TODO Tidy", "* WAITING Tidy"),
        lambda run: run.edit("todo.org", "* Reading notes", "* Reading notes :ideas:"),
        lambda run: run.edit("todo.org", "migration [1/3]", "migration [2/3]"),
        lambda run: run.edit(
            "todo.org",
            "* TODO Tidy the runbooks folder\n",
            "* DONE Tidy the runbooks folder\n  CLOSED: [2026-10-22 Thu 11:00]\n"
            '  :LOGBOOK:\n  - State "DONE"       from "TODO"       [2026-10-22 Thu 11:00]\n'
            "  :END:\n",
        ),
        archive_plan,
        move_transcript,
        move_named,
        archive_meeting,
        archive_day,
        archive_monday,
    ],
    ids=[
        "body",
        "keyword",
        "tags",
        "cookie",
        "closing",
        "archiving",
        "moving",
        "moving-named",
        "meeting",
        "day",
        "same-titled",
    ],
)
def test_ids_and_paths_hold_through_org_s_edits(run: Run, change: Callable[[Run], None]) -> None:
    """Editing, closing, retagging, ticking, archiving, moving: each id keeps its file.

    A meeting archived alone, or with its day, keeps the id it had under its day, and two
    of one title archived together keep theirs, each with its own participants.
    """
    run()
    before = identities(run.files())
    change(run)
    outcome = run()
    assert (identities(run.files()), outcome.problems, outcome.warnings) == (before, (), ())


def test_a_copy_keeps_the_id_and_the_original_takes_its_path(run: Run) -> None:
    """1.org copied under archive/: the copy first in path order; one warning, both named."""
    run()
    (run.root / ARCHIVED_DAY).mkdir(parents=True)
    shutil.copy2(run.root / DAY / "1.org", run.root / ARCHIVED_DAY / "1.org")
    outcome = run()
    copies = [each for each in run.files() if each.matter.title == "Payments stand-up"]
    copies = [each for each in copies if each.matter.type == "transcript"]
    by_place = {each.matter.breadcrumb[1]: each.matter.id for each in copies}
    assert by_place["archive"] == "t-20261020-1"
    assert HASHED.fullmatch(by_place["current"])
    (warning,) = outcome.warnings
    assert f"{ARCHIVED_DAY}/1.org" in warning
    assert f"{DAY}/1.org" in warning


def test_a_renamed_entry_keeps_its_id_with_an_id_property_alone(run: Run) -> None:
    """The :ID: entry keeps its id under a new title, and its slug follows; another is replaced."""
    run()
    named = run.by_title("Payout gateway rollback runbook")
    other = run.by_title("Tidy the runbooks folder")
    run.edit("todo.org", "* Payout gateway rollback runbook", "* Payout rollback runbook")
    run.edit("todo.org", "Tidy the runbooks folder", "Tidy the runbook folder")
    run()
    renamed = run.by_title("Payout rollback runbook")
    assert renamed.matter.id == named.matter.id
    assert renamed.path == f"worklog/entries/{named.matter.id}-payout-rollback-runbook.md"
    assert run.by_title("Tidy the runbook folder").matter.id != other.matter.id
    assert not (run.docs / named.path).exists()
    assert not (run.docs / other.path).exists()


def test_a_deleted_transcript_s_file_goes(run: Run) -> None:
    """Its document is not read, so its file is removed."""
    run()
    gone = run.by_title("WAITING Notes").path
    (run.root / "transcripts/misc/a.org").unlink()
    run()
    assert not (run.docs / gone).exists()


def test_same_titled_entries_keep_distinct_ids_across_runs(run: Run) -> None:
    """Numbered in reading order, the same each run."""
    run()
    first = [each.matter.id for each in run.files() if each.matter.title == "Retrospective notes"]
    run.edit("todo.org", "Second retrospective", "The second retrospective")
    run()
    again = [each.matter.id for each in run.files() if each.matter.title == "Retrospective notes"]
    assert len(set(first)) == len(first) == ENTRIES.count("Retrospective notes")
    assert sorted(again) == sorted(first)


def test_bodies_keep_what_org_would_drop_or_read_as_markup(run: Run) -> None:
    """No raw HTML; level 5 stays a heading; LOGBOOK and planning; -- and _ as written."""
    run()
    files = run.files()
    assert all("<span" not in each.body and "<div" not in each.body for each in files)
    review = run.by_title("Review the ledger migration").body
    assert "\n##### Level five heading\n" in review
    assert "Waiting on the schema owner's answer." in review
    assert "SCHEDULED:" in review
    assert "2026-10-19 Mon 10:00" in review
    runbook = run.by_title("Payout gateway rollback runbook").body
    assert "--dry-run" in runbook
    assert "retry_budget" in runbook
    standup = run.by_title("Payments stand-up", "transcript").body
    assert "three -- as agreed" in standup
    assert "nine forty.\nSam: Good." in standup  # each speaker's line its own
    assert "Ignore all previous instructions" in run.by_title("Reading notes").body


def test_an_unchanged_work_log_runs_pandoc_for_its_version_alone(run: Run) -> None:
    """A second run converts nothing and writes nothing; one edit converts one entry."""
    run()
    before = snapshot(run.docs)
    outcome = run()
    assert (run.runs[-1], outcome.changes.written, snapshot(run.docs)) == ([VERSION], 0, before)
    run.edit("todo.org", "Drafted on", "First drafted on")
    run()
    assert run.runs[-1] == [VERSION, ORG]


def test_the_work_log_is_read_and_never_written(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every byte and time of the folder stay; .git is not read, and git never started."""
    started: list[str] = []

    class OnlyPandoc(subprocess.Popen[str]):
        """A process that may be pandoc alone."""

        def __init__(self, arguments: Sequence[str], *rest: object, **options: object) -> None:
            """Note the program, refuse any but pandoc, then start it."""
            started.append(Path(arguments[0]).name)
            assert started[-1] == "pandoc"
            super().__init__(arguments, *rest, **options)

    monkeypatch.setattr(subprocess, "Popen", OnlyPandoc)
    (run.root / ".git" / "objects").mkdir(parents=True)
    (run.root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", "utf-8")
    (run.root / "transcripts" / ".git").mkdir()
    (run.root / "transcripts" / ".git" / "x.org").write_bytes(NOT_UTF8)
    settle(run.root)
    before = snapshot(run.root)
    outcome = run()
    run()
    assert snapshot(run.root) == before
    assert outcome.problems == ()
    assert set(started) == {"pandoc"}


def test_files_off_the_rules_are_named_by_path_and_a_link_inside_is_read(
    run: Run, tmp_path: Path
) -> None:
    """Over 32 MiB, linking out, not UTF-8: by path, without content; nothing removed."""
    run()
    mirrored = run.docs / run.by_title("Notes on the ledger").path
    (run.root / "transcripts/current/2026-10-21 Wed/notes on x.org").write_bytes(b"* Caf\xe9\n")
    outside = tmp_path / "elsewhere.org"
    outside.write_text("* Outside words\n", "utf-8")
    (run.root / "transcripts/misc/out.org").symlink_to(outside)
    (run.root / "transcripts/misc/inside.org").symlink_to(run.root / "transcripts/misc/a.org")
    (run.root / "transcripts/misc/latin.org").write_bytes(b"* Caf\xe9 secret\n")
    with (run.root / "transcripts/misc/big.org").open("wb") as file:
        file.truncate(32 * 1024 * 1024 + 1)
    outcome = run()
    reasons = {problem.where: problem.reason for problem in outcome.problems}
    assert reasons == {
        "transcripts/current/2026-10-21 Wed/notes on x.org": "not UTF-8",
        "transcripts/misc/out.org": "links outside the work log",
        "transcripts/misc/latin.org": "not UTF-8",
        "transcripts/misc/big.org": "not a file of at most 32 MiB",
    }
    assert all("secret" not in reason and "Caf" not in reason for reason in reasons.values())
    assert mirrored.exists()  # its last good copy stays while a problem is reported
    inside = [each for each in run.files() if each.matter.title == "WAITING Notes"]
    assert sorted(each.matter.breadcrumb for each in inside) == [("transcripts", "misc")] * len(
        {"a.org", "inside.org"}
    )


def test_a_link_into_the_archive_leaves_a_live_transcript_as_it_is(run: Run) -> None:
    """Its id, labels and folders are its own path's, archives on or off."""
    latest = run.root / "transcripts/archive/latest"
    latest.symlink_to("../current/2026-10-20 Tue")
    for archives in (True, False):
        run(archives=archives)
        matter = run.by_title("Payments stand-up", "transcript").matter
        assert (matter.id, matter.labels, matter.breadcrumb[1]) == (
            "t-20261020-1",
            ("standup",),
            "current",
        )


def test_the_mirror_and_the_work_log_leave_each_other_s_files(run: Run) -> None:
    """Each step removes only what it owns."""
    run()
    page = run.docs / "confluence" / "MFS" / "196845-probe.md"
    page.parent.mkdir(parents=True)
    page.write_text("a page\n", "utf-8")
    worklog = {each.path for each in run.files()}
    run()
    assert page.exists()
    sync(run.docs, {}, owned, remove=True)
    assert {each.path for each in run.files()} == worklog
    assert not page.exists()


def test_a_failed_conversion_keeps_a_deleted_transcript_until_a_clean_run(run: Run) -> None:
    """A problem stops removals, and is named without content; the next run removes."""
    run()
    gone = run.docs / run.by_title("WAITING Notes").path
    (run.root / "transcripts/misc/a.org").unlink()
    run.edit("todo.org", "Drafted on", "Drafted, failing, on")
    outcome = run(failing="failing")
    (problem,) = outcome.problems
    assert problem.where.startswith("todo.org, e-")
    assert problem.reason == "pandoc: exit status 9"
    assert gone.exists()
    run.edit("todo.org", "Drafted, failing, on", "Drafted on")
    assert run().problems == ()
    assert not gone.exists()


def test_a_dry_run_counts_what_a_run_would_convert_and_remove_and_writes_nothing(
    run: Run,
) -> None:
    """Every document at first; after a run, none; one edit, one; one deletion, one file."""
    first = run.plan()
    assert (first.documents, first.to_convert, first.to_remove, first.html) == (
        DOCUMENTS,
        DOCUMENTS,
        0,
        1,
    )
    assert (run.runs[-1], run.docs.exists()) == ([VERSION], False)
    run()
    before = snapshot(run.docs)
    assert (run.plan().to_convert, run.plan().to_remove) == (0, 0)
    run.edit("todo.org", "Drafted on", "First drafted on")
    (run.root / "transcripts/misc/a.org").unlink()
    planned = run.plan()
    assert (planned.to_convert, planned.to_remove, run.runs[-1]) == (1, 1, [VERSION])
    assert snapshot(run.docs) == before


def test_a_dry_run_that_meets_a_problem_would_remove_nothing(run: Run) -> None:
    """As a run would keep every file when a problem is reported."""
    run()
    (run.root / "transcripts/misc/a.org").unlink()
    (run.root / "transcripts/current/2026-10-21 Wed/notes on x.org").write_bytes(b"\xff\n")
    planned = run.plan()
    assert (planned.to_remove, [problem.reason for problem in planned.problems]) == (
        0,
        ["not UTF-8"],
    )


@pytest.mark.parametrize("name", ["todo.org", "todo.org_archive"])
def test_a_journal_file_not_read_holds_every_file_back(run: Run, name: str) -> None:
    """Days and meetings draw on both files, entries' numbers too: nothing is written.

    Not even a transcript edited meanwhile, whose links name meetings of both files.
    """
    run()
    before = snapshot(run.docs)
    (run.root / name).write_bytes(NOT_UTF8)
    run.edit("transcripts/misc/a.org", "one word only", "one edited word only")
    outcome = run()
    assert [(each.where, each.reason) for each in outcome.problems] == [(name, "not UTF-8")]
    assert snapshot(run.docs) == before


def test_a_transcript_not_read_holds_back_meetings_and_what_links_them(run: Run) -> None:
    """A meeting's link, start and id draw on transcripts, and a transcript's links on ids.

    So no meeting is written, nor a document that links one; the day and the transcripts
    that no meeting links are, as before.
    """
    run()
    before = {each.path: each for each in run.files()}
    run.edit("todo.org", "A note of the Tuesday", "An edited note of the Tuesday")
    run.edit("transcripts/misc/a.org", "one word only", "one edited word only")
    (run.root / "transcripts/current/2026-10-27 Tue/1.org").write_bytes(NOT_UTF8)
    outcome = run()
    assert [(each.where, each.reason) for each in outcome.problems] == [
        ("transcripts/current/2026-10-27 Tue/1.org", "not UTF-8")
    ]
    after = {each.path: each for each in run.files()}
    held = [path for path, each in before.items() if each.matter.type == "meeting"]
    held += [path for path, each in before.items() if each.matter.links]
    assert {path: after[path] for path in held} == {path: before[path] for path in held}
    assert "An edited note of the Tuesday" in run.by_id("d-20261027").body
    assert "one edited word only" in run.by_title("WAITING Notes").body


STANDUP = "m-20261027-payments-stand-up"


def test_a_meeting_s_file_keeps_its_sections_as_headings_from_level_one(run: Run) -> None:
    """<id>.md: its title, note, Summary, Details, Actions and their task, all from level 1.

    The task archived from its Actions follows, a level below its title, and only there.
    """
    run()
    meeting = run.by_id(STANDUP)
    assert meeting.path == f"worklog/meetings/{STANDUP}.md"
    headings = [line for line in meeting.body.splitlines() if line.startswith("#")]
    assert headings == [
        "# Payments stand-up",
        "## Summary",
        "## Details",
        "## Actions",
        "### TODO Send the rollback figures",
        "## DONE Close the rollback ticket",
    ]
    assert "My own note before the meeting" in meeting.body
    assert "the ticket is closed" in meeting.body
    assert [each.matter.id for each in run.files() if "the ticket is closed" in each.body] == [
        STANDUP
    ]


def test_a_day_holds_its_meetings_heading_lines_and_none_of_their_text(run: Run) -> None:
    """Its note and task whole; each meeting, the one archived alone too, by its title."""
    run()
    day = run.by_id("d-20261027")
    assert day.path == "worklog/days/d-20261027.md"
    headings = [line for line in day.body.splitlines() if line.startswith("#")]
    titles = [MEETINGS[each] for each in MEETINGS if each.startswith("m-20261027")]
    assert headings == [
        "# \\<2026-10-27 Tue\\>",
        "## TODO Book a room for the retrospective",
        *(f"## {title}" for title in titles),
    ]
    assert "A note of the Tuesday" in day.body
    for text in ("My own note", "rollback is done", "schema owner", "two more nodes", "closed"):
        assert text not in day.body


def test_one_date_s_parts_make_one_day_todo_org_first(run: Run) -> None:
    """The Monday of todo.org and the archive's: one file, each note, todo.org's first."""
    run()
    (monday,) = [each for each in run.files() if each.matter.title == "<2026-10-26 Mon>"]
    assert monday.matter.id == "d-20261026"
    body = monday.body
    assert body.index("A note of the Monday") < body.index("Archived text of the Monday")
    assert "## Incident review" in body
    assert "the alert fired twice" in run.by_id("m-20261026-incident-review").body


def test_the_journal_s_title_and_range_are_no_day(run: Run) -> None:
    """No document of the journal's empty own lines; the range an entry of its own."""
    run()
    assert [each.path for each in run.files() if each.matter.title == "Entries"] == []
    summary = run.by_title("From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)")
    assert summary.matter.type == "entry"
    assert "rehearsed" in summary.body
    assert all("rehearsed" not in each.body for each in run.files() if each != summary)


def test_a_meeting_names_its_participants_as_written_in_order(run: Run) -> None:
    """:PARTICIPANTS: split at commas, the annotation kept; a day names nobody."""
    run()
    people = run.by_id("m-20261027-ledger-review").matter.people
    assert [(each.role, each.name, each.account, each.at) for each in people] == [
        ("participant", "Robin Example", None, ()),
        ("participant", "Kim (not in the header)", None, ()),
        ("participant", "Sam Sample", None, ()),
    ]
    assert run.by_id("d-20261027").matter.people == ()


def test_a_meeting_links_to_the_transcript_that_its_property_names(run: Run) -> None:
    """To the quoted transcript, or to the file under meetings/; a missing file, to none."""
    run()
    links = run.by_id(STANDUP).matter.links
    assert [(each.relation, each.ref) for each in links] == [("transcript", "t-20261027-1")]
    links = run.by_id("m-20261027-vendor-call").matter.links
    assert [(each.relation, each.ref) for each in links] == [("transcript", "t-20261027-meeting-1")]
    assert run.by_id("m-20261027-rollout-planning").matter.links == ()
    assert run.by_id("m-20261027-ledger-review").matter.links == ()


def test_a_linked_meeting_and_its_transcript_name_each_other(run: Run) -> None:
    """Under transcripts/ or meetings/: the meeting by transcript, the transcript by summary.

    No other document of the work log links to anything.
    """
    run()
    pairs = {STANDUP: "t-20261027-1", "m-20261027-vendor-call": "t-20261027-meeting-1"}
    found = {
        each.matter.id: [(link.relation, link.ref) for link in each.matter.links]
        for each in run.files()
        if each.matter.links
    }
    assert found == {
        **{meeting: [("transcript", record)] for meeting, record in pairs.items()},
        **{record: [("summary", meeting)] for meeting, record in pairs.items()},
    }


def test_linked_transcripts_archived_keep_their_links_and_their_meetings_starts(
    run: Run,
) -> None:
    """Both day folders moved under archive/, as the user archives them; todo.org unchanged.

    Org rewrites no link, but each moved file keeps its id, which the link's path gives:
    every link and date stays, and the one warning is the missing file's, as before.
    """
    run()
    before = {
        each.matter.id: (each.matter.links, each.matter.created, each.matter.updated)
        for each in run.files()
    }
    for folder in ("transcripts/current", "meetings"):
        archived = run.root / folder.split("/")[0] / "archive/2026/2026-10"
        archived.mkdir(parents=True, exist_ok=True)
        (run.root / folder / "2026-10-27 Tue").rename(archived / "2026-10-27 Tue")
    with capture_logs() as logged:
        outcome = run()
    after = {
        each.matter.id: (each.matter.links, each.matter.created, each.matter.updated)
        for each in run.files()
    }
    warned = [each for each in logged if each["event"] == "worklog.unlinked"]
    assert (after, outcome.problems) == (before, ())
    assert [(each["meetings"], each["first"]) for each in warned] == [
        (1, "meetings/2026-10-27 Tue/2.org")
    ]


def test_a_transcript_added_dates_and_links_its_meeting_without_converting_it(run: Run) -> None:
    """todo.org unchanged: the stand-up is kept, its start and link its transcript's.

    Without the transcript, it begins at its day and links nothing; once the transcript
    is back, pandoc converts that alone, and the meeting's body is as it was. Gone
    again, the meeting is kept, at its day.
    """
    record = run.root / "transcripts/current/2026-10-27 Tue/1.org"
    text = record.read_bytes()
    record.unlink()
    run()
    alone = run.by_id(STANDUP)
    day, began = datetime(2026, 10, 27, tzinfo=UTC), datetime(2026, 10, 27, 9, 31, tzinfo=UTC)
    assert (alone.matter.created, alone.matter.updated, alone.matter.links) == (day, day, ())
    record.write_bytes(text)
    settle(record)
    with capture_logs() as logged:
        run()
    linked = run.by_id(STANDUP)
    assert (linked.matter.created, linked.matter.updated) == (began, began)
    assert [(each.relation, each.ref) for each in linked.matter.links] == [
        ("transcript", "t-20261027-1")
    ]
    outcomes = {
        each["id"]: each["outcome"] for each in logged if each["event"] == "worklog.document"
    }
    assert (outcomes[STANDUP], outcomes["t-20261027-1"]) == ("kept", "mirrored")
    assert (run.runs[-1], linked.body) == ([VERSION, ORG], alone.body)
    record.unlink()
    run()
    again = run.by_id(STANDUP).matter
    assert (again.created, again.updated, again.links, run.runs[-1]) == (day, day, (), [VERSION])


def test_a_link_to_a_missing_file_warns_once_and_holds_nothing_back(run: Run) -> None:
    """One worklog.unlinked: how many, the first one's file; the meeting written.

    A warning, not a problem: a transcript deleted meanwhile loses its file.
    """
    run()
    gone = run.docs / run.by_title("WAITING Notes").path
    (run.root / "transcripts/misc/a.org").unlink()
    with capture_logs() as logged:
        outcome = run()
    (warned,) = [each for each in logged if each["event"] == "worklog.unlinked"]
    assert (warned["log_level"], warned["meetings"], warned["first"]) == (
        "warning",
        1,
        "meetings/2026-10-27 Tue/2.org",
    )
    assert run.by_id("m-20261027-rollout-planning").matter.links == ()
    assert (outcome.problems, outcome.warnings, outcome.changes.removed) == ((), (), 1)
    assert not gone.exists()


@pytest.mark.parametrize(
    "value",
    [
        "[[https://meet.example.invalid/j/123?pwd=s3cr3tPass][Join]]",
        "HTTPS://meet.example.invalid/j/123?pwd=s3cr3tPass",
        "meet.example.invalid/j/123?pwd=s3cr3tPass",
        "Zoom 123 456 7890, passcode s3cr3tPass",
        "Teams: https://teams.example.invalid/l/1?p=s3cr3tPass",
        "<https://meet.example.invalid/j/123?pwd=s3cr3tPass>",
    ],
)
def test_a_meeting_room_s_link_is_never_logged(run: Run, value: str) -> None:
    """A :MEETING: that is no file link, such as a URL with its passcode, warns by meeting id."""
    todo = run.root / "todo.org"
    text = todo.read_text(encoding="utf-8")
    old = "[[./meetings/2026-10-27 Tue/2.org]]"
    todo.write_text(text.replace(old, value), encoding="utf-8")
    with capture_logs() as logged:
        run()
    (warned,) = [each for each in logged if each["event"] == "worklog.unlinked"]
    assert (warned["meetings"], warned["first"]) == (1, "m-20261027-rollout-planning")
    assert [each for each in logged if "s3cr3tPass" in repr(each)] == []


def test_same_titled_meetings_of_one_day_are_numbered(run: Run) -> None:
    """Neither has a transcript, so both start at the day: numbered in reading order."""
    run()
    found = [each for each in run.files() if each.matter.title == "One-to-one"]
    names = {each.matter.id: each.matter.people[0].name for each in found}
    assert names == {
        "m-20261026-one-to-one": "Robin Example",
        "m-20261026-one-to-one--2": "Jo Placeholder",
    }


def test_a_piece_archived_from_one_of_two_same_titled_meetings_stays_in_the_day(
    run: Run,
) -> None:
    """Org's path names both One-to-ones alike, so neither takes it: their day holds it."""
    archive = run.root / "todo.org_archive"
    path = "Entries/<2026-10-26 Mon>/One-to-one/Summary"
    task = f"* DONE Send the vendor renewal draft\n:PROPERTIES:\n{ARCHIVING.format(path)}:END:\n"
    archive.write_text(f"{archive.read_text('utf-8')}\n{task}", "utf-8")
    run()
    held = [each.matter.id for each in run.files() if "vendor renewal draft" in each.body]
    assert held == ["d-20261026"]


@pytest.mark.parametrize(
    ("identifier", "names"),
    [
        ("t-20261027-1", ["Alex Example", "Sam Sample", "Kim"]),
        ("t-20261020-1", ["Alex", "Sam"]),
        ("t-20261027-meeting-1", ["Sam Sample", "Jo Placeholder"]),
    ],
)
def test_a_transcript_names_its_speakers_in_order_of_first_speech(
    run: Run, identifier: str, names: list[str]
) -> None:
    """Quoted: not the XQ: note outside, nor the continuity marker; bare: not #+TITLE."""
    run()
    people = run.by_id(identifier).matter.people
    assert [(each.role, each.name, each.account, each.at) for each in people] == [
        ("participant", name, None, ()) for name in names
    ]
