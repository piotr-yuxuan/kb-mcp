"""The work log's folder, read in place, as plan 017's "Read in place, never written" says.

What is read: ``todo.org``, ``todo.org_archive`` and every ``*.org`` under
``transcripts/``, and under ``meetings/`` by the same rules (plan 042's "The meeting
files under meetings/"); HTML transcripts counted, never read; hidden and Emacs names
passed over; links followed inside the folder alone; 32 MiB a file and 20,000
transcripts in both folders; a file breaking a rule named by its path, never by its
content.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from kb_mcp.sources.worklog.prepare.adapters import files

CONTENT = "words of the file that must never show"
# The plan's bound on transcripts.
TRANSCRIPTS = 20_000
NOT_UTF8 = b"* Emacs \xff\xfe " + CONTENT.encode()


def write(root: Path, relative: str, data: str | bytes = "* Heading\n") -> Path:
    """Write a file under ``root``, with its folders."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, "utf-8")
    return path


def paths(listing: files.OrgFiles) -> list[str]:
    """Return the paths listed, as text."""
    return [str(path) for path in listing.paths]


@pytest.fixture
def worklog(tmp_path: Path) -> Path:
    """Return a work log with each kind of file, and names to pass over."""
    root = tmp_path / "todo"
    for relative in (
        "todo.org",
        "todo.org_archive",
        "transcripts/current/2026-10-20 Tue/1.org",
        "transcripts/archive/2026/2026-09/2026-09-15 Tue/1.org",
        "transcripts/misc/a.org",
        "meetings/2026-10-27 Tue/1.org",
        "meetings/archive/2026/2026-10/2026-10-26 Mon/1.org",
        "notes.org",  # not a file of the work log
        "transcripts/todo.org_archive",  # nor an archive file below the root
        "transcripts/x/todo.org_archive",
        "transcripts/current/2026-10-20 Tue/audio.m4a",
    ):
        write(root, relative)
    write(root, "transcripts/current/2026-10-20 Tue/2.html", "<p>" + CONTENT)
    write(root, "meetings/2026-10-27 Tue/2.html", "<p>" + CONTENT)
    for relative in (
        "transcripts/current/2026-10-20 Tue/.#1.org",
        "transcripts/current/2026-10-20 Tue/#1.org#",
        "transcripts/current/2026-10-20 Tue/1.org~",
        "transcripts/.hidden/x.org",
        "transcripts/#saved#/x.org",
        "transcripts/old~/x.org",
        "meetings/2026-10-27 Tue/.#1.org",
        "meetings/2026-10-27 Tue/1.org~",
        ".#todo.org",
    ):
        write(root, relative, NOT_UTF8)
    return root


def test_the_work_log_files_are_listed_in_path_order(worklog: Path) -> None:
    """The two files, then every .org under meetings/ and transcripts/; the HTML counted."""
    listing = files.listed(worklog, archives=True)
    assert paths(listing) == [
        "todo.org",
        "todo.org_archive",
        "meetings/2026-10-27 Tue/1.org",
        "meetings/archive/2026/2026-10/2026-10-26 Mon/1.org",
        "transcripts/archive/2026/2026-09/2026-09-15 Tue/1.org",
        "transcripts/current/2026-10-20 Tue/1.org",
        "transcripts/misc/a.org",
    ]
    html = ["transcripts/current/2026-10-20 Tue/2.html", "meetings/2026-10-27 Tue/2.html"]
    assert (listing.html, listing.problems, listing.root) == (len(html), (), worklog.resolve())


def test_without_archives_the_archive_file_and_folder_are_not_listed(worklog: Path) -> None:
    """todo.org_archive, transcripts/archive/ and meetings/archive/ are left out."""
    assert paths(files.listed(worklog, archives=False)) == [
        "todo.org",
        "meetings/2026-10-27 Tue/1.org",
        "transcripts/current/2026-10-20 Tue/1.org",
        "transcripts/misc/a.org",
    ]


@pytest.mark.parametrize(
    ("link", "target", "own"),
    [
        (
            "transcripts/archive/latest",
            "../current/2026-10-20 Tue",
            "transcripts/current/2026-10-20 Tue/1.org",
        ),
        ("transcripts/a/link", "../misc", "transcripts/misc/a.org"),
        ("meetings/a/link", "../../transcripts/misc", "transcripts/misc/a.org"),
    ],
)
def test_a_folder_is_read_by_its_own_path_before_any_link(
    worklog: Path, link: str, target: str, own: str
) -> None:
    """A link in a folder that sorts first takes nothing from the folder it names."""
    (worklog / link).parent.mkdir(parents=True, exist_ok=True)
    (worklog / link).symlink_to(target)
    listing = files.listed(worklog, archives=True)
    assert own in paths(listing)
    assert not [path for path in paths(listing) if path.startswith(f"{link}/")]


@pytest.mark.parametrize("backwards", [False, True])
def test_the_order_of_a_folder_s_listing_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, backwards: bool
) -> None:
    """Whatever order the file system lists entries in, the own path wins over a link."""
    root = tmp_path / "todo"
    write(root, "transcripts/z/d/1.org")
    (root / "transcripts/a").mkdir()
    (root / "transcripts/a/link").symlink_to("../z/d")
    listing = Path.iterdir
    monkeypatch.setattr(
        Path, "iterdir", lambda path: iter(sorted(listing(path), reverse=backwards))
    )
    assert paths(files.listed(root, archives=True)) == ["transcripts/z/d/1.org"]


def test_without_archives_a_link_to_an_archived_folder_is_left_out(worklog: Path) -> None:
    """Archived by what it links to, too: an archived day is not read as a current one."""
    shortcut = worklog / "transcripts/current/shortcut"
    shortcut.symlink_to("../archive/2026/2026-09/2026-09-15 Tue")
    (worklog / "transcripts/current/plan.org").symlink_to("../../todo.org_archive")
    (worklog / "meetings/latest").symlink_to("archive/2026/2026-10/2026-10-26 Mon")
    assert paths(files.listed(worklog, archives=False)) == [
        "todo.org",
        "meetings/2026-10-27 Tue/1.org",
        "transcripts/current/2026-10-20 Tue/1.org",
        "transcripts/misc/a.org",
    ]


def test_links_are_followed_inside_the_work_log_alone(tmp_path: Path, worklog: Path) -> None:
    """A link to a file or a folder inside is read; one out is named; a loop ends."""
    outside = write(tmp_path, "elsewhere/secret.org", CONTENT)
    transcripts = worklog / "transcripts"
    (transcripts / "linked.org").symlink_to(transcripts / "misc/a.org")
    (transcripts / "linked folder").symlink_to(transcripts / "misc")
    (transcripts / "out.org").symlink_to(outside)
    (transcripts / "out folder").symlink_to(outside.parent)
    (transcripts / "misc/loop").symlink_to(transcripts)
    listing = files.listed(worklog, archives=True)
    assert "transcripts/linked.org" in paths(listing)
    assert "transcripts/misc/a.org" in paths(listing)  # the folder itself, before its link
    assert "transcripts/linked folder/a.org" not in paths(listing)
    assert sorted(listing.problems, key=lambda problem: problem.path) == [
        files.UnreadFile(path="transcripts/out folder", reason="links outside the work log"),
        files.UnreadFile(path="transcripts/out.org", reason="links outside the work log"),
    ]
    assert all(CONTENT not in problem.reason for problem in listing.problems)


def test_a_linked_todo_file_outside_is_named_and_not_listed(tmp_path: Path) -> None:
    """todo.org itself may not lead out of the folder."""
    root = tmp_path / "todo"
    root.mkdir()
    (root / "todo.org").symlink_to(write(tmp_path, "elsewhere/todo.org"))
    listing = files.listed(root, archives=True)
    assert (paths(listing), listing.problems) == (
        [],
        (files.UnreadFile(path="todo.org", reason="links outside the work log"),),
    )


def test_past_the_bound_the_first_transcripts_are_kept(
    worklog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bound for both folders: the first in path order, and a problem naming them.

    Three: neither folder holds more, both together do.
    """
    assert files.TRANSCRIPT_COUNT == TRANSCRIPTS
    monkeypatch.setattr(files, "TRANSCRIPT_COUNT", 3)
    listing = files.listed(worklog, archives=True)
    assert paths(listing) == [
        "todo.org",
        "todo.org_archive",
        "meetings/2026-10-27 Tue/1.org",
        "meetings/archive/2026/2026-10/2026-10-26 Mon/1.org",
        "transcripts/archive/2026/2026-09/2026-09-15 Tue/1.org",
    ]
    assert listing.problems == (
        files.UnreadFile(path="transcripts, meetings", reason="over 3 transcripts"),
    )


def test_a_folder_that_is_not_there_is_a_problem(tmp_path: Path) -> None:
    """So that a run removes nothing when the work log is out of reach."""
    listing = files.listed(tmp_path / "absent", archives=True)
    assert (listing.paths, listing.problems) == (
        (),
        (files.UnreadFile(path=".", reason="not a folder"),),
    )


def test_a_file_is_read_with_its_time_of_change(worklog: Path) -> None:
    """Its text, and its modification time in the local zone, the same instant."""
    moment = datetime(2026, 10, 22, 12, 0, 5, tzinfo=UTC)
    os.utime(worklog / "todo.org", (moment.timestamp(), moment.timestamp()))
    read = files.org_text(worklog, PurePosixPath("todo.org"))
    assert (read.path, read.text, read.modified) == (
        PurePosixPath("todo.org"),
        "* Heading\n",
        moment,
    )
    local = datetime.fromtimestamp(moment.timestamp()).astimezone()
    assert read.modified.utcoffset() == local.utcoffset()


@pytest.mark.parametrize(
    ("data", "reason"),
    [(NOT_UTF8, "not UTF-8"), (None, "not a file of at most 32 MiB")],
)
def test_a_file_off_the_rules_is_named_without_its_content(
    worklog: Path, data: bytes | None, reason: str
) -> None:
    """Not UTF-8, or over 32 MiB (a sparse file, never read): the reason alone."""
    path = worklog / "todo.org"
    if data is None:
        with path.open("ab") as file:
            file.truncate(files.FILE_BYTES + 1)
    else:
        path.write_bytes(data)
    with pytest.raises(files.UnreadableError) as raised:
        files.org_text(worklog, PurePosixPath("todo.org"))
    assert str(raised.value) == reason
    assert CONTENT not in str(raised.value)


@pytest.mark.parametrize("error", [ValueError, OverflowError])
def test_a_time_of_change_out_of_range_is_a_reason(
    worklog: Path, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    """A modification time that no datetime holds is named, not a crash.

    Python raises ValueError for a year past 9999 here, OverflowError past the C time;
    a file system may not store such a time, so the refusal is simulated.
    """

    class Far(datetime):
        """A datetime whose times of change are all out of range."""

        @classmethod
        def fromtimestamp(cls, timestamp: float, tz: object = None) -> Far:
            """Refuse every time, as for a year past 9999."""
            message = f"year out of range: {timestamp} {tz}"
            raise error(message)

    monkeypatch.setattr(files, "datetime", Far)
    with pytest.raises(files.UnreadableError, match=rf"^not read \({error.__name__}\)$"):
        files.org_text(worklog, PurePosixPath("todo.org"))


def test_a_file_of_exactly_32_mib_is_read(worklog: Path) -> None:
    """The bound is inclusive."""
    (worklog / "todo.org").write_bytes(b"x" * files.FILE_BYTES)
    assert len(files.org_text(worklog, PurePosixPath("todo.org")).text) == files.FILE_BYTES
