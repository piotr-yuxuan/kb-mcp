"""The work log mirrored end to end: plan 017's criteria 7 to 12, through its step.

The fixture, ``fixtures/worklog/``, is invented, as the plan's acceptance criteria
describe it; Emacs's lock, autosave and backup files are added to each copy, since git
ignores them. Times are fixed by ``os.utime``. Expectations come from the plan's tables,
written by hand, and every file is read back by ``markdown.load``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.mirror.adapters.markdown import load
from atlassian_offline_mcp.mirror.adapters.mirror_files import owned, sync
from atlassian_offline_mcp.mirror.adapters.pandoc import ORG, VERSION, Pandoc, PandocFailedError
from atlassian_offline_mcp.mirror.app.worklog import Outcome, mirror_worklog

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
    "Transcript, 2026-09-15 Tue, 1",
    "WAITING Notes",
]


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

    def files(self) -> list[Mirrored]:
        """Read back every file of the work log's step, as search will."""
        found = sorted((self.docs / "worklog").rglob("*.md"))
        return [
            Mirrored(path.relative_to(self.docs).as_posix(), *load(path.read_text("utf-8"), "x"))
            for path in found
        ]

    def by_title(self, title: str) -> Mirrored:
        """Return the one file of this title."""
        (found,) = [each for each in self.files() if each.matter.title == title]
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


def identities(files: list[Mirrored]) -> list[tuple[str, str]]:
    """Return each file's id and path."""
    return sorted((each.matter.id, each.path) for each in files)


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Return every file under a folder, hidden ones too: its bytes and modification time."""
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_the_documents_are_the_top_level_headings_and_the_org_transcripts(run: Run) -> None:
    """Both files' top-level headings, COMMENT and noexport with their text; one per .org."""
    outcome = run()
    files = run.files()
    assert sorted(each.matter.title for each in files if each.matter.type == "entry") == ENTRIES
    assert sorted(each.matter.title for each in files if each.matter.type == "transcript") == (
        TRANSCRIPTS
    )
    assert (outcome.documents, outcome.html, outcome.problems, outcome.warnings) == (
        len(ENTRIES) + len(TRANSCRIPTS),
        1,
        (),
        (),
    )
    assert "Commented text that org would not publish." in run.by_title("Private scratch").body
    assert "Text tagged noexport" in run.by_title("Hand-over checklist").body
    assert all(each.matter.source == "worklog" for each in files)


def test_without_archives_the_archived_documents_and_text_go(run: Run) -> None:
    """The archive file's entries, the archived transcript and the ARCHIVE text."""
    run()
    outcome = run(archives=False)
    titles = {each.matter.title for each in run.files()}
    gone = {"Vendor contract renewal", "Old incident log", "Transcript, 2026-09-15 Tue, 1"}
    assert titles == (set(ENTRIES) | set(TRANSCRIPTS)) - gone
    assert outcome.changes.removed == len(gone)
    assert "Archived text inside an entry." not in run.by_title("Reading notes").body
    assert all("Archived text" not in each.body for each in run.files())


@pytest.mark.parametrize(
    ("title", "status", "labels", "breadcrumb"),
    [
        ("Review the ledger migration", "WAITING", ("review", "ledger", "work"), ("todo.org",)),
        ("Old incident log", "current", ("ARCHIVE", "work"), ("todo.org",)),
        ("Vendor contract renewal", "WAITING", ("vendor", "ARCHIVE"), ("todo.org_archive",)),
        ("Tidy the runbooks folder", "TODO", ("work",), ("todo.org",)),
        (
            "Payments stand-up",
            "current",
            ("standup",),
            ("transcripts", "current", "2026-10-20 Tue"),
        ),
        (
            "Transcript, 2026-09-15 Tue, 1",
            "current",
            ("ARCHIVE",),
            ("transcripts", "archive", "2026", "2026-09", "2026-09-15 Tue"),
        ),
        ("WAITING Notes", "current", (), ("transcripts", "misc")),
    ],
)
def test_front_matter_says_status_labels_and_place(
    run: Run, title: str, status: str, labels: tuple[str, ...], breadcrumb: tuple[str, ...]
) -> None:
    """Keyword or current; tags, #+FILETAGS and ARCHIVE; the file or the folders."""
    run()
    matter = run.by_title(title).matter
    assert (matter.status, matter.labels, matter.breadcrumb) == (status, labels, breadcrumb)
    assert (matter.fetched_at, matter.key, matter.space, matter.url) == (MODIFIED, None, None, None)


@pytest.mark.parametrize(
    ("title", "created", "updated"),
    [
        ("Plan the next quarter", datetime(2026, 10, 14, 16, tzinfo=UTC), None),
        (
            "Review the ledger migration",
            datetime(2026, 10, 19, 10, tzinfo=UTC),
            datetime(2026, 10, 19, 11, 20, tzinfo=UTC),
        ),
        ("Tidy the runbooks folder", MODIFIED, None),
        ("Payments stand-up", datetime(2026, 10, 20, tzinfo=UTC), None),
        ("WAITING Notes", MODIFIED, None),
    ],
)
def test_dates_are_the_earliest_and_latest_events_up_to_the_file_time(
    run: Run, title: str, created: datetime, updated: datetime | None
) -> None:
    """A later timestamp is a plan; no event, the file's time; a transcript, its day."""
    run()
    matter = run.by_title(title).matter
    assert (matter.created, matter.updated) == (created, updated or created)


def test_ids_of_undated_or_unruly_transcripts_are_digests(run: Run) -> None:
    """A blank in notes on x.org, no day for misc/a.org: t- and 16 hex digits."""
    run()
    for title in ("Notes on the ledger", "WAITING Notes"):
        assert HASHED.fullmatch(run.by_title(title).matter.id)
    assert run.by_title("Payments stand-up").matter.id == "t-20261020-1"


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
    ],
    ids=["body", "keyword", "tags", "cookie", "closing", "archiving", "moving"],
)
def test_ids_and_paths_hold_through_org_s_edits(run: Run, change: Callable[[Run], None]) -> None:
    """Editing, closing, retagging, ticking, archiving, moving: each id keeps its file."""
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
    assert "three -- as agreed" in run.by_title("Payments stand-up").body
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
        matter = run.by_title("Payments stand-up").matter
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
