"""Org's syntax and the work log's documents, as plan 017 defines them.

The expectations come from the plan's "Documents and their identity" and "Front matter
and conversion", and from org's own syntax: a title is a heading without its keyword,
priority, tags and statistics cookies; ids are digests of what the plan names, kept when
an entry is closed, retagged, ticked or archived. Generated cases are enumerated.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import PurePosixPath

import pytest

from atlassian_offline_mcp.kernel.content import WORKLOG_ID, WORKLOG_REVISION
from atlassian_offline_mcp.sources.worklog.domain import org
from atlassian_offline_mcp.sources.worklog.domain.worklog import (
    Source,
    entries,
    revision,
    transcripts,
)

KEYWORDS = frozenset({"TODO", "WAITING", "DONE"})
DECLARED = "#+TODO: TODO WAITING | DONE\n"
MODIFIED = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
ENTRY_ID = re.compile(r"e-[0-9a-f]{16}")
HASHED_TRANSCRIPT = re.compile(r"t-[0-9a-f]{16}")
# Titles with statistics cookies anywhere, and the words they leave.
TITLES = [
    ("Review the ledger", "Review the ledger"),
    ("[1/3] Review  naïve café", "Review naïve café"),
    ("Q3 [33%] plan x-1 [/]", "Q3 plan x-1"),
    ("Done [%]", "Done"),
    ("Time 10:30 [10/10]", "Time 10:30"),
]
TAG_SETS = [(), ("work",), ("x_y", "a@b"), ("ARCHIVE", "review")]
DAY_NAMES = ["Mon", "Tue", "mar.", "So", "木"]
# A name over the 64 characters an id's name may have.
LONG = "a" * 65
# Minutes between generated moments: a prime, so that hours, minutes and days vary.
STRIDE = 7919


def sha(text: str) -> str:
    """Return the first 16 hex digits of a text's SHA-256, as the plan names digests."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def todo(text: str, modified: datetime = MODIFIED) -> Source:
    """Return ``todo.org`` holding ``text``."""
    return Source(PurePosixPath("todo.org"), text, modified)


def transcript(path: str, text: str = "Words.\n", modified: datetime = MODIFIED) -> Source:
    """Return a transcript at ``transcripts/<path>``."""
    return Source(PurePosixPath("transcripts", path), text, modified)


def one(text: str) -> dict[str, str]:
    """Return each entry's id by title, for a todo.org declaring TODO WAITING | DONE."""
    return {each.title: each.id for each in entries(todo(DECLARED + text), None, archives=True)}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("* Plain", (1, None, None, False, "Plain", ())),
        ("*** TODO Deep", (3, "TODO", None, False, "Deep", ())),
        (
            "* WAITING [#A] COMMENT Review [1/3]   :a:b@c:",
            (1, "WAITING", "[#A]", True, "Review", ("a", "b@c")),
        ),
        ("* LATER Undeclared", (1, None, None, False, "LATER Undeclared", ())),
        ("* COMMENT", (1, None, None, True, "", ())),
        ("* :only:tags:", (1, None, None, False, "", ("only", "tags"))),
        ("*", (1, None, None, False, "", ())),
        ("* Time 10:30 stays", (1, None, None, False, "Time 10:30 stays", ())),
    ],
)
def test_a_heading_is_read_into_its_parts(
    line: str, expected: tuple[int, str | None, str | None, bool, str, tuple[str, ...]]
) -> None:
    """Stars, a declared keyword, the priority, COMMENT, the title and the closing tags."""
    found = org.heading(line, KEYWORDS)
    assert found is not None
    assert (
        found.level,
        found.keyword,
        found.priority,
        found.comment,
        found.title,
        found.tags,
    ) == expected


@pytest.mark.parametrize("line", ["*bold* text", " * indented", "Text", "#+TITLE: x", ""])
def test_other_lines_are_not_headings(line: str) -> None:
    """A star must begin the line and be followed by a blank or nothing."""
    assert org.heading(line, KEYWORDS) is None


def test_generated_headings_give_their_title_without_the_other_parts() -> None:
    """Whatever the keyword, priority, cookies, spacing and tags, the title is its words."""
    for level, keyword, priority, (written, title), tags, gap in itertools.product(
        (1, 3, 6),
        (None, *sorted(KEYWORDS)),
        (None, "[#A]"),
        TITLES,
        TAG_SETS,
        (" ", " " * 30),
    ):
        words = ["*" * level, keyword, priority, written]
        line = " ".join(word for word in words if word)
        line += f"{gap}:{':'.join(tags)}:" if tags else ""
        found = org.heading(line, KEYWORDS)
        assert found is not None
        assert (found.level, found.title, found.keyword, found.priority, found.tags) == (
            level,
            title,
            keyword,
            priority,
            tags,
        ), line


def test_a_file_declares_its_keywords_its_title_and_its_tags() -> None:
    """#+TODO and #+SEQ_TODO in any case, fast-access keys dropped; #+FILETAGS both ways."""
    parsed = org.read(
        "#+todo: TODO(t) WAIT(w@/!) | DONE(d)\n#+SEQ_TODO: NEXT\n"
        "#+TITLE: The title\n#+FILETAGS: :work:ops:\n#+FILETAGS: more\n* NEXT x\n"
    )
    assert parsed.keywords == {"TODO", "WAIT", "DONE", "NEXT"}
    assert parsed.declarations == ("#+todo: TODO(t) WAIT(w@/!) | DONE(d)", "#+SEQ_TODO: NEXT")
    assert (parsed.title, parsed.filetags) == ("The title", ("work", "ops", "more"))
    assert parsed.subtrees[0].heading.keyword == "NEXT"


def test_keywords_come_from_the_file_else_the_inherited_one_else_todo_and_done() -> None:
    """The archive file takes todo.org's keywords when it declares none."""
    parent = org.read(DECLARED)
    assert org.read("* WAITING x\n", parent).subtrees[0].heading.keyword == "WAITING"
    assert org.read("#+TODO: LATER\n* WAITING x\n", parent).keywords == {"LATER"}
    assert org.read("* WAITING x\n").subtrees[0].heading.keyword is None
    assert org.read("* DONE x\n").keywords == {"TODO", "DONE"}


def test_subtrees_are_the_top_level_headings_with_what_follows() -> None:
    """Text before the first heading belongs to none; deeper headings stay inside."""
    parsed = org.read("Preamble\n* One\ntext\n** Two\n*** Three\n* Four\n")
    assert [subtree.lines for subtree in parsed.subtrees] == [
        ("* One", "text", "** Two", "*** Three"),
        ("* Four",),
    ]
    assert [heading.title for heading in parsed.headings] == ["One", "Two", "Three", "Four"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "* x\n:PROPERTIES:\n:ID: a\n:created: [2026-10-01 Thu]\n:END:\n",
            {"ID": "a", "CREATED": "[2026-10-01 Thu]"},
        ),
        ("* x\nSCHEDULED: <2026-10-01 Thu>\n  :PROPERTIES:\n  :ID: b\n  :END:\n", {"ID": "b"}),
        ("* x\n:PROPERTIES:\n:ID: c\n", {}),
        ("* x\ntext\n:PROPERTIES:\n:ID: d\n:END:\n", {}),
        ("* x\n** y\n:PROPERTIES:\n:ID: e\n:END:\n", {}),
    ],
)
def test_properties_are_those_of_the_drawer_after_the_heading(
    text: str, expected: dict[str, str]
) -> None:
    """Right after the heading or its planning line, and closed; names in any case."""
    assert org.read(text).subtrees[0].properties == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("<2026-10-20 Tue>", [datetime(2026, 10, 20, tzinfo=UTC)]),
        ("[2026-10-20 Tue 09:05]", [datetime(2026, 10, 20, 9, 5, tzinfo=UTC)]),
        ("<2026-10-20 mar. 10:00-11:30 +1w -2d>", [datetime(2026, 10, 20, 10, tzinfo=UTC)]),
        (
            "CLOCK: [2026-10-20 Tue 10:00]--[2026-10-20 Tue 11:00] =>  1:00",
            [datetime(2026, 10, 20, 10, tzinfo=UTC), datetime(2026, 10, 20, 11, tzinfo=UTC)],
        ),
        ("<2026-10-20>", [datetime(2026, 10, 20, tzinfo=UTC)]),
        ("[2026-02-30 Mon] [2026-10-20 Tue 25:00] 2026-10-20", []),
        ("<2026-10-20 Tue .+1d/3d>", [datetime(2026, 10, 20, tzinfo=UTC)]),
    ],
)
def test_timestamps_are_read_as_utc_as_written(line: str, expected: list[datetime]) -> None:
    """Active and inactive; a range's start; repeaters; no real day or time is none."""
    assert org.timestamps([line]) == expected


def test_generated_timestamps_read_back_as_written() -> None:
    """Any moment written as org writes it reads back to the minute."""
    start = datetime(1990, 1, 1, tzinfo=UTC)
    for number in range(500):
        moment = start + timedelta(minutes=number * STRIDE * 13)
        timed = number % 2 == 0
        opening, closing = ("<", ">") if number % 3 else ("[", "]")
        name = DAY_NAMES[number % len(DAY_NAMES)]
        time = f" {moment:%H:%M}" if timed else ""
        line = f"text {opening}{moment:%Y-%m-%d} {name}{time}{closing} text"
        expected = moment if timed else moment.replace(hour=0, minute=0)
        assert org.timestamps([line]) == [expected], line


def test_pandoc_reads_the_settings_then_the_document_without_comment() -> None:
    """Keywords, an empty #+EXCLUDE_TAGS and the options lead; the document's own go."""
    lines = ["* TODO [#B] COMMENT Top :x:", "#+OPTIONS: ^:t", "#+exclude_tags: x"]
    lines.append("** COMMENT Sub")
    text = org.pandoc_input(["#+TODO: TODO | DONE"], lines, {"TODO", "DONE"}, archives=False)
    assert text.splitlines() == [
        "#+TODO: TODO | DONE",
        "#+EXCLUDE_TAGS:",
        "#+OPTIONS: arch:nil d:t p:t H:6 ^:nil -:nil",
        "* TODO [#B] Top :x:",
        "** Sub",
    ]
    assert "arch:t " in org.pandoc_input([], [], set(), archives=True)


def test_entry_ids_follow_id_then_created_then_title() -> None:
    """The :ID:'s digest; else one of title and :CREATED:; else of the title alone."""
    ids = one(
        "* Named\n:PROPERTIES:\n:ID: 6f1c\n:END:\n"
        "* Created\n:PROPERTIES:\n:CREATED: [2026-10-13 Tue]\n:END:\n"
        "* Same created\n:PROPERTIES:\n:CREATED: [2026-10-13 Tue]\n:END:\n"
        "* Bare\n"
    )
    assert ids["Named"] == f"e-{sha('6f1c')}"
    assert ids["Bare"] == f"e-{sha('Bare')}"
    assert ENTRY_ID.fullmatch(ids["Created"])
    assert ids["Created"] != f"e-{sha('Created')}"  # :CREATED: counts
    assert ids["Created"] != ids["Same created"]  # and so does the title
    assert all(WORKLOG_ID.fullmatch(identifier) for identifier in ids.values())


def test_same_titled_entries_are_numbered_in_reading_order() -> None:
    """The second and third of one title take -2 and -3; distinct :CREATED: tell apart."""
    found = entries(
        todo("* Retro\none\n* Retro\ntwo\n* Retro\nthree\n"),
        Source(PurePosixPath("todo.org_archive"), "* Retro\nfour\n", MODIFIED),
        archives=True,
    )
    base = f"e-{sha('Retro')}"
    assert [each.id for each in found] == [base, f"{base}-2", f"{base}-3", f"{base}-4"]
    dated = entries(
        todo(
            "* Retro\n:PROPERTIES:\n:CREATED: [2026-10-02 Fri]\n:END:\n"
            "* Retro\n:PROPERTIES:\n:CREATED: [2026-10-09 Fri]\n:END:\n"
        ),
        None,
        archives=True,
    )
    assert all(ENTRY_ID.fullmatch(each.id) for each in dated)  # neither numbered
    assert dated[0].id != dated[1].id


ENTRY = (
    "* {keyword} [#A] Review the ledger {cookie} :{tags}:\n"
    "{planning}"
    ":PROPERTIES:\n:CREATED: [2026-10-13 Tue]\n{archived}:END:\n"
    "{logbook}"
    "{body}\n"
)
UNCHANGED = {
    "keyword": "TODO",
    "cookie": "[0/3]",
    "tags": "review",
    "planning": "",
    "archived": "",
    "logbook": "",
    "body": "Body.",
}


@pytest.mark.parametrize(
    "change",
    [
        {"keyword": "DONE", "planning": "CLOSED: [2026-10-22 Thu 09:00]\n"},
        {"keyword": "WAITING"},
        {"tags": "review:ledger:ARCHIVE"},
        {"cookie": "[3/3]"},
        {"logbook": ':LOGBOOK:\n- State "DONE" from "TODO" [2026-10-22 Thu 09:00]\n:END:\n'},
        {"archived": ":ARCHIVE_TIME: 2026-10-22 Thu 09:00\n:ARCHIVE_TODO: TODO\n"},
        {"body": "Another body, [2026-10-22 Thu]."},
    ],
)
def test_closing_retagging_ticking_and_editing_keep_the_id(change: dict[str, str]) -> None:
    """Planning lines, notes, keyword, tags, cookies and body never enter the id."""
    before = one(ENTRY.format(**UNCHANGED))
    after = one(ENTRY.format(**(UNCHANGED | change)))
    assert list(after.values()) == list(before.values())


def test_a_renamed_entry_keeps_its_id_only_with_an_id_property() -> None:
    """The :ID: alone survives a new title."""
    named = "* {}\n:PROPERTIES:\n:ID: abc\n:END:\n"
    assert list(one(named.format("Old")).values()) == list(one(named.format("New")).values())
    assert list(one("* Old\n").values()) != list(one("* New\n").values())


def test_an_entry_describes_its_title_status_labels_and_file() -> None:
    """Keyword as status, else current; its tags, the file's, ARCHIVE if archived."""
    parent = DECLARED + "#+FILETAGS: :work:\n"
    found = entries(
        todo(parent + "* WAITING [#A] Review [1/3] :review:work:\n* Old :ARCHIVE:\n* Plain\n"),
        Source(PurePosixPath("todo.org_archive"), "* WAITING Vendor :vendor:\n", MODIFIED),
        archives=True,
    )
    assert [
        (each.title, each.status, each.labels, each.breadcrumb, each.type) for each in found
    ] == [
        ("Review", "WAITING", ("review", "work"), ("todo.org",), "entry"),
        ("Old", "current", ("ARCHIVE", "work"), ("todo.org",), "entry"),
        ("Plain", "current", ("work",), ("todo.org",), "entry"),
        ("Vendor", "WAITING", ("vendor", "ARCHIVE"), ("todo.org_archive",), "entry"),
    ]


def test_without_archives_the_archive_file_and_archived_entries_are_left_out() -> None:
    """The archive file's entries and those tagged ARCHIVE; arch:nil for the rest."""
    found = entries(
        todo("* Old :ARCHIVE:\n* Kept\n** Gone :ARCHIVE:\n"),
        Source(PurePosixPath("todo.org_archive"), "* Vendor\n", MODIFIED),
        archives=False,
    )
    assert [each.title for each in found] == ["Kept"]
    assert "#+OPTIONS: arch:nil " in found[0].text


def test_entry_events_stop_at_the_file_time_in_its_own_zone() -> None:
    """A timestamp after the file's time is a plan; org writes the local time."""
    london = timezone(timedelta(hours=1))
    modified = datetime(2026, 10, 22, 18, 0, tzinfo=london)  # 17:00 in UTC
    (found,) = entries(
        todo("* x\n[2026-10-01 Thu]\n[2026-10-22 Thu 17:30]\n<2026-10-22 Thu 18:30>\n", modified),
        None,
        archives=True,
    )
    assert found.dates(None) == (
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 22, 17, 30, tzinfo=UTC),
    )


def test_an_undated_entry_dates_from_its_file_and_its_earlier_creation() -> None:
    """Updated is the file's time; created the existing file's, else that time too."""
    (found,) = entries(todo("* Undated\n"), None, archives=True)
    earlier = datetime(2026, 10, 1, tzinfo=UTC)
    assert found.dates(None) == (MODIFIED, MODIFIED)
    assert found.dates(earlier) == (earlier, MODIFIED)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("current/2026-10-20 Tue/1.org", "t-20261020-1"),
        ("archive/2026/2026-10/2026-10-20 Tue/1.org", "t-20261020-1"),
        ("current/2026-10-20-standup.org", "t-20261020-2026-10-20-standup"),
        ("current/2026-10-20 Tue/notes on x.org", f"t-{sha('2026-10-20 Tue/notes on x.org')}"),
        ("misc/a.org", f"t-{sha('a.org')}"),
        ("current/2026-13-40 Xxx/1.org", f"t-{sha('2026-13-40 Xxx/1.org')}"),
        (f"current/2026-10-20 Tue/{LONG}.org", f"t-{sha(f'2026-10-20 Tue/{LONG}.org')}"),
    ],
)
def test_transcript_ids_name_the_day_and_the_name_else_a_digest(path: str, expected: str) -> None:
    """t-YYYYMMDD-<name>; a name off the id's rule or no day gives its path's digest."""
    (found,), warnings = transcripts([transcript(path)], archives=True)
    assert (found.id, warnings) == (expected, [])
    assert WORKLOG_ID.fullmatch(found.id)


def test_a_copy_keeps_the_id_and_the_other_takes_its_whole_path() -> None:
    """The first in path order keeps it; one warning names both files."""
    copy = "archive/2026/2026-10/2026-10-20 Tue/1.org"
    original = "current/2026-10-20 Tue/1.org"
    found, warnings = transcripts([transcript(original), transcript(copy)], archives=True)
    assert [(str(each.source.path), each.id) for each in found] == [
        (f"transcripts/{copy}", "t-20261020-1"),
        (f"transcripts/{original}", found[1].id),
    ]
    assert HASHED_TRANSCRIPT.fullmatch(found[1].id)
    assert len(warnings) == 1
    assert f"transcripts/{copy}" in warnings[0]
    assert f"transcripts/{original}" in warnings[0]


def test_two_undated_files_of_one_name_get_distinct_ids() -> None:
    """The digest below the first folder is shared; the second takes its whole path's."""
    found, warnings = transcripts(
        [transcript("misc/a.org"), transcript("other/a.org"), transcript("a.org")],
        archives=True,
    )
    assert len({each.id for each in found}) == len(found)
    assert len(warnings) == len(found) - 1


@pytest.mark.parametrize(
    ("path", "text", "title"),
    [
        ("current/2026-10-20 Tue/1.org", "#+TITLE: Stand-up\n* Heading\n", "Stand-up"),
        ("misc/a.org", "Text.\n** WAITING Notes [1/2] :x:\n", "WAITING Notes"),
        ("archive/2026/2026-09/2026-09-15 Tue/1.org", "Bare.\n", "Transcript, 2026-09-15 Tue, 1"),
        ("misc/a.org", "Bare words.\n", "Transcript, a"),
    ],
)
def test_a_transcript_title_is_its_title_else_heading_else_day_and_name(
    path: str, text: str, title: str
) -> None:
    """#+TITLE; else its first heading's title, keywords its own; else Transcript, day, name."""
    (found,), _ = transcripts([transcript(path, text)], archives=True)
    assert found.title == title


def test_a_transcript_describes_its_status_labels_folders_and_day() -> None:
    """Status current; its #+FILETAGS and ARCHIVE when archived; its folders; its day."""
    found, _ = transcripts(
        [
            transcript("archive/2026/2026-09/2026-09-15 Tue/1.org", "#+FILETAGS: :a:\n"),
            transcript("misc/a.org", "Said on [2026-10-01 Thu 10:00], then [2026-10-03 Sat].\n"),
        ],
        archives=True,
    )
    folders = ("transcripts", "archive", "2026", "2026-09", "2026-09-15 Tue")
    assert [(each.status, each.labels, each.breadcrumb) for each in found] == [
        ("current", ("a", "ARCHIVE"), folders),
        ("current", (), ("transcripts", "misc")),
    ]
    day = datetime(2026, 9, 15, tzinfo=UTC)
    assert found[0].dates(None) == (day, day)
    assert found[1].dates(None) == (
        datetime(2026, 10, 1, 10, tzinfo=UTC),
        datetime(2026, 10, 3, tzinfo=UTC),
    )


def test_without_archives_archived_transcripts_are_left_out() -> None:
    """Those under transcripts/archive/ alone."""
    found, _ = transcripts(
        [transcript("archive/2026/x/1.org"), transcript("current/archive/1.org")],
        archives=False,
    )
    assert [str(each.source.path) for each in found] == ["transcripts/current/archive/1.org"]


def test_a_revision_names_the_input_and_the_converter() -> None:
    """16 hex digits; another input or another pandoc, another revision."""
    first = revision("pandoc 3.7", "a")
    assert WORKLOG_REVISION.fullmatch(first)
    assert revision("pandoc 3.7", "a") == first
    assert revision("pandoc 3.8", "a") != first
    assert revision("pandoc 3.7", "b") != first
