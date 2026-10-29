"""Org's syntax and the work log's documents, as plan 017 defines them.

The expectations come from the plan's "Documents and their identity" and "Front matter
and conversion", and from org's own syntax: a title is a heading without its keyword,
priority, tags and statistics cookies; ids are digests of what the plan names, kept when
an entry is closed, retagged, ticked or archived. Generated cases are enumerated.

Plan 042's outline, days' titles and links to files are expected as org's own parser
reads the same made-up lines (Emacs 31.1, ``org-element``), and its archiving writes
``:ARCHIVE_OLPATH:``; its journal's days and meetings, their ids and participants, as its
"Days and meetings: the rule", "What archiving does", "Ids" and "Participants" say, its
question 1's sample first.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import PurePosixPath

import pytest

from atlassian_offline_mcp.kernel.content import WORKLOG_ID, WORKLOG_REVISION
from atlassian_offline_mcp.mirror.domain.mirror import RELATIONS
from atlassian_offline_mcp.sources.worklog.domain import org
from atlassian_offline_mcp.sources.worklog.domain.worklog import (
    SUMMARY,
    TRANSCRIBED,
    Document,
    Source,
    journal,
    linked_back,
    meeting_ids,
    participants,
    revision,
    speakers,
    start,
    transcripts,
    turns,
    writable,
)

KEYWORDS = frozenset({"TODO", "WAITING", "DONE"})
DECLARED = "#+TODO: TODO WAITING | DONE\n"
MODIFIED = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
ENTRY_ID = re.compile(r"e-[0-9a-f]{16}")
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
    return {
        each.title: each.id
        for each in journal(todo(DECLARED + text), None, archives=True, transcripts=())[0]
    }


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
        ("** ", (2, None, None, False, "", ())),
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


@pytest.mark.parametrize(
    "line", ["*bold* text", " * indented", "*", "**", "Text", "#+TITLE: x", ""]
)
def test_other_lines_are_not_headings(line: str) -> None:
    """A star must begin the line and be followed by a blank, as org and pandoc read it."""
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
        again = org.heading(found.line, KEYWORDS)
        assert again == found, line  # written back, it reads the same


@pytest.mark.parametrize("line", ["* COMMENT", "** COMMENT :x:", "*** TODO [#A] COMMENT Title"])
def test_a_heading_without_comment_is_still_a_heading(line: str) -> None:
    """Written back without COMMENT, even with nothing else, it reads as the same heading."""
    found = org.heading(line, KEYWORDS)
    assert found is not None
    again = org.heading(found.line, KEYWORDS)
    assert again is not None
    assert (again.level, again.keyword, again.title, again.tags, again.comment) == (
        found.level,
        found.keyword,
        found.title,
        found.tags,
        False,
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("*** A/B review", "A/B review"),
        ("*** Sync on [[https://example.invalid/PRB-1][PRB-1]]", "Sync on PRB-1"),
        ("*** Link no desc [[./x.org]]", "Link no desc ./x.org"),
        ("*** Ledger review [/]", "Ledger review [/]"),
        ("*** Plan [1/2] review", "Plan  review"),
        ("*** Ratio [50%] done [3/4]", "Ratio  done"),
        ("*** COMMENT Hidden one", "Hidden one"),
        ("*** TODO [#A] Keyed one :tag:", "Keyed one"),
        ("*** Two  spaces  inside", "Two  spaces  inside"),
    ],
)
def test_an_outline_title_is_the_heading_as_org_writes_it_in_a_path(
    line: str, expected: str
) -> None:
    """As Emacs 31.1's archiving wrote each of these made-up headings in :ARCHIVE_OLPATH:.

    A link is its description, else its target; a filled cookie goes, an empty one stays;
    blanks within and a / stay as written.
    """
    found = org.heading(line, KEYWORDS)
    assert found is not None
    assert found.outline_title == expected


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


def test_lines_end_at_a_line_feed_alone() -> None:
    """A carriage return before it goes; other breaks, as U+2028 or a form feed, are text."""
    parsed = org.read(
        "* A :work:\r\n:PROPERTIES:\r\n:ID: abc\r\n:END:\r\nx\u2028* B\x0c* C\x85* D\r\n* E\n"
    )
    assert [subtree.heading.title for subtree in parsed.subtrees] == ["A", "E"]
    assert (parsed.subtrees[0].heading.tags, parsed.subtrees[0].properties) == (
        ("work",),
        {"ID": "abc"},
    )


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
        ("* x\n:PROPERTIES:\n:ID: a\n:END:\ntext\n", (":PROPERTIES:", ":ID: a", ":END:")),
        (
            "* x\nSCHEDULED: <2026-10-01 Thu>\n  :PROPERTIES:\n  :ID: b\n  :END:\ntext\n",
            ("SCHEDULED: <2026-10-01 Thu>", "  :PROPERTIES:", "  :ID: b", "  :END:"),
        ),
        ("* x\nDEADLINE: <2026-10-01 Thu>\ntext\n", ("DEADLINE: <2026-10-01 Thu>",)),
        ("* x\n:PROPERTIES:\n:ID: c\n", ()),
        ("* x\ntext\n:PROPERTIES:\n:ID: d\n:END:\n", ()),
        ("* x\n", ()),
    ],
)
def test_a_preamble_is_the_planning_line_then_the_drawer(
    text: str, expected: tuple[str, ...]
) -> None:
    """Each as org reads it right after the heading: a drawer never closed is text."""
    assert org.read(text).subtrees[0].preamble == expected


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


# A journal as the work log holds one, made up: a day with a note, a meeting with its
# sections and their task, a task of the day, then a condensed range.
JOURNAL = (
    "* Entries\n"
    "The journal's own line.\n"
    "** <2026-10-27 Tue>\n"
    "A note of the day.\n"
    "*** Payments stand-up\n"
    ":PROPERTIES:\n"
    ":MEETING: [[./meetings/2026-10-27 Tue/1.org]]\n"
    ":END:\n"
    "**** Summary\n"
    "**** Actions\n"
    "***** TODO Send the rollback figures\n"
    "*** WAITING Book a room\n"
    "** From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)\n"
    "Condensed.\n"
)
MEETING = (
    "*** Payments stand-up",
    ":PROPERTIES:",
    ":MEETING: [[./meetings/2026-10-27 Tue/1.org]]",
    ":END:",
    "**** Summary",
    "**** Actions",
    "***** TODO Send the rollback figures",
)


def test_children_split_at_the_next_level_only() -> None:
    """The journal's are a day and a range, the day's a meeting and a task; sections stay."""
    parsed = org.read(DECLARED + JOURNAL)
    (journal,) = parsed.subtrees
    assert journal.own == ("* Entries", "The journal's own line.")
    day, condensed = journal.children(parsed.keywords)
    assert (day.heading.level, day.own) == (2, ("** <2026-10-27 Tue>", "A note of the day."))
    assert condensed.own == condensed.lines
    assert condensed.lines[1:] == ("Condensed.",)
    assert condensed.children(parsed.keywords) == ()
    meeting, task = day.children(parsed.keywords)
    assert meeting.lines == MEETING
    assert meeting.properties == {"MEETING": "[[./meetings/2026-10-27 Tue/1.org]]"}
    assert [each.heading.title for each in meeting.children(parsed.keywords)] == [
        "Summary",
        "Actions",
    ]
    assert (task.heading.level, task.heading.keyword, task.lines) == (
        3,
        "WAITING",
        ("*** WAITING Book a room",),
    )


def test_a_child_ends_at_the_next_heading_of_its_level_or_higher() -> None:
    """As org's parser has it: *** B under * A is a child of A, and so is the ** C after it."""
    (top,) = org.read("* A\nown\n*** B\n**** B1\n** C\n*** C1\n").subtrees
    assert [child.lines for child in top.children(KEYWORDS)] == [
        ("*** B", "**** B1"),
        ("** C", "*** C1"),
    ]


def test_generated_outlines_split_into_own_lines_then_children() -> None:
    """Each child holds deeper headings alone, and is no deeper than the one before it."""
    for levels in itertools.chain.from_iterable(
        itertools.product((2, 3, 4), repeat=count) for count in range(6)
    ):
        written = [line for level in levels for line in (f"{'*' * level} Heading", "text")]
        (top,) = org.read("\n".join(["* Top", "text", *written])).subtrees
        children = top.children(KEYWORDS)
        assert top.own == ("* Top", "text"), levels
        assert (*top.own, *(line for child in children for line in child.lines)) == top.lines
        for child in children:
            inner = [org.heading(line, KEYWORDS) for line in child.lines[1:]]
            assert all(each.level > child.heading.level for each in inner if each), levels
        for before, after in itertools.pairwise(children):
            assert after.heading.level <= before.heading.level, levels


def test_shifting_moves_the_stars_alone() -> None:
    """Up or down, a heading keeps its keyword, priority, COMMENT, title and tags as written."""
    for depth, gap, keyword, priority, comment, tags, level in itertools.product(
        (1, 3, 5),
        (" ", " \t"),
        (None, "WAITING"),
        (None, "[#A]"),
        (False, True),
        TAG_SETS,
        (1, 2, 4),
    ):
        words = [keyword, priority, "COMMENT" if comment else None, "Review  [1/3]"]
        line = f"{'*' * depth}{gap}{' '.join(word for word in words if word)}"
        line += f"   :{':'.join(tags)}: " if tags else " "
        lines = [line, ":PROPERTIES:", "*bold* text", " * indented", f"{'*' * (depth + 2)} Child"]
        moved = org.shifted(lines, level)
        assert moved == [
            f"{'*' * level}{line.lstrip('*')}",
            ":PROPERTIES:",
            "*bold* text",
            " * indented",
            f"{'*' * (level + 2)} Child",
        ], line
        before, after = org.heading(line, KEYWORDS), org.heading(moved[0], KEYWORDS)
        assert before is not None
        assert after == dataclasses.replace(before, level=level), line


def test_a_meeting_shifted_begins_at_level_one() -> None:
    """Its sections then at level 2, and their task at level 3."""
    assert org.shifted(MEETING) == [
        "* Payments stand-up",
        ":PROPERTIES:",
        ":MEETING: [[./meetings/2026-10-27 Tue/1.org]]",
        ":END:",
        "** Summary",
        "** Actions",
        "*** TODO Send the rollback figures",
    ]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("<2026-10-28 Wed>", datetime(2026, 10, 28, tzinfo=UTC)),
        ("<2026-10-28>", datetime(2026, 10, 28, tzinfo=UTC)),
        ("<2026-10-28 mer.>", datetime(2026, 10, 28, tzinfo=UTC)),
        ("<2026-10-28 Mon>", datetime(2026, 10, 28, tzinfo=UTC)),
        ("<2026-10-28 Wed 10:00>", None),
        ("[2026-10-28 Wed]", None),
        ("<2026-02-30 Mon>", None),
        ("<2026-10-28 Wed +1w>", None),
        ("<2026-10-27 Tue>--<2026-10-28 Wed>", None),
        ("<2026-10-28 Wed> Retro", None),
        ("From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)", None),
        ("Entries", None),
    ],
)
def test_a_day_is_one_active_timestamp_of_a_date_alone(
    title: str, expected: datetime | None
) -> None:
    """Its day's name optional and unchecked, as org has it; a time or repeater is no day."""
    assert org.date_title(title) == expected


def test_a_day_is_read_from_a_heading_or_an_archived_outline_path() -> None:
    """A heading's title; a part of the :ARCHIVE_OLPATH: that org writes, cookies left out."""
    day = datetime(2026, 10, 27, tzinfo=UTC)
    found = org.heading("** <2026-10-27 Tue> [1/2] :day:", KEYWORDS)
    assert found is not None
    assert org.date_title(found.title) == day
    path = "Entries/<2026-10-27 Tue>/Payments stand-up/Actions"
    assert [org.date_title(part) for part in path.split("/")] == [None, day, None, None]


def test_generated_days_read_back_as_written() -> None:
    """Any date, written as org writes a day's heading, reads back at midnight UTC."""
    start = datetime(1990, 1, 1, tzinfo=UTC)
    for number in range(500):
        day = start + timedelta(days=number * 61)  # a prime, so that months and days vary
        name = DAY_NAMES[number % len(DAY_NAMES)]
        assert org.date_title(f"<{day:%Y-%m-%d} {name}>") == day, day


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("[[./meetings/2026-10-27 Tue/1.org]]", "meetings/2026-10-27 Tue/1.org"),
        ("[[./meetings/2026-10-27 Tue/1.org][Transcript]]", "meetings/2026-10-27 Tue/1.org"),
        ("[[file:transcripts/current/1.org][Transcript]]", "transcripts/current/1.org"),
        ("[[file:./meetings/1.org]]", "meetings/1.org"),
        ("[[file+sys:meetings/1.org]]", "meetings/1.org"),
        ("[[file:meetings/1.org::*Notes]]", "meetings/1.org"),
        ("[[./meetings/1.org::12]]", "meetings/1.org"),
        ("file:meetings/1.org", "meetings/1.org"),
        ("./meetings/2026-10-27 Tue/1.org", "meetings/2026-10-27 Tue/1.org"),
        ("meetings/2026-10-27 Tue/1.org", "meetings/2026-10-27 Tue/1.org"),
    ],
)
def test_a_link_to_a_file_gives_its_path(value: str, expected: str) -> None:
    """In brackets, typed file: or from ./, or alone; its description and search left out."""
    assert org.link_target(value) == PurePosixPath(expected)


@pytest.mark.parametrize(
    "value",
    [
        "[[../meetings/1.org]]",
        "[[./meetings/../1.org]]",
        "[[file:../1.org]]",
        "../meetings/1.org",
        "[[/srv/meetings/1.org]]",
        "[[file:/srv/meetings/1.org]]",
        "/srv/meetings/1.org",
        "[[~/meetings/1.org]]",
        "~/meetings/1.org",
        "[[meetings/1.org]]",
        "[[https://meet.example.invalid/abc][Recording]]",
        "https://meet.example.invalid/abc",
        "[[id:6f1c]]",
        "[[./]]",
        "",
    ],
)
def test_a_link_through_dot_dot_absolute_or_to_no_file_gives_none(value: str) -> None:
    """Up a folder, from the root or a home folder; another type, or a search for a heading."""
    assert org.link_target(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("[[./meetings/1.org]]", "meetings/1.org"),
        ("[[file:meetings/1.org][Transcript]]", "meetings/1.org"),
        ("file:meetings/1.org", "meetings/1.org"),
        ("./meetings/1.org", "meetings/1.org"),
        ("meetings/1.org", None),
        ("HTTPS://meet.example.invalid/j/123?pwd=s3cr3tPass", None),
        ("meet.example.invalid/j/123?pwd=s3cr3tPass", None),
        ("Zoom 123 456 7890, passcode s3cr3tPass", None),
        ("<https://meet.example.invalid/j/123?pwd=s3cr3tPass>", None),
        ("[[https://meet.example.invalid/j/1?pwd=s3cr3tPass][Join]] at nine", None),
    ],
)
def test_without_bare_paths_only_a_link_in_org_s_file_forms_names_a_file(
    value: str, expected: str | None
) -> None:
    """In brackets, after file: or from ./; a path alone may be any text, so names none."""
    found = org.link_target(value, bare=False)
    assert found == (None if expected is None else PurePosixPath(expected))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Alex: x\n", None),
        ("a\n#+begin_quote\nb\n#+end_quote\nc\n#+BEGIN_QUOTE\nd\n#+END_QUOTE\n", ["b", "d"]),
        ("  #+Begin_Quote :x y\nb\n  #+end_quote  \n", ["b"]),
        ("#+begin_quote\n#+end_quote\n", []),
        ("#+begin_quote\nb\n", None),
        ("#+begin_quote\nb\n#+end_quote\n#+begin_quote\nc\n", ["b"]),
        ("#+begin_quotes\nb\n#+end_quote\n", None),
        ("#+begin_quote\n#+begin_quote\nb\n#+end_quote\nc\n#+end_quote\n", ["#+begin_quote", "b"]),
    ],
)
def test_quote_blocks_are_the_lines_between_their_begin_and_end(
    text: str, expected: list[str] | None
) -> None:
    """None without a block; in any case, indented; one never closed, or inside one, is text."""
    assert org.quoted(org.read(text).lines) == expected


# Blocks of one line, about 6 MB, as a file of 32 MiB may hold, and the seconds they
# take at most: a pass over them, not the many that copying the lines gathered at each
# block's end took.
BLOCKS, BLOCKS_S = 200_000, 5


def test_many_quote_blocks_are_read_in_time_that_grows_with_them() -> None:
    """Each block's lines in order, within seconds."""
    lines = [
        line for number in range(BLOCKS) for line in ("#+begin_quote", f"{number}", "#+end_quote")
    ]
    began = time.perf_counter()
    assert org.quoted(lines) == [f"{number}" for number in range(BLOCKS)]
    assert time.perf_counter() - began < BLOCKS_S


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
    # The title and :CREATED:, one line each, joined by a line feed: names files for good.
    assert ids["Created"] == f"e-{sha('Created\n[2026-10-13 Tue]')}"
    assert ids["Same created"] == f"e-{sha('Same created\n[2026-10-13 Tue]')}"
    assert all(WORKLOG_ID.fullmatch(identifier) for identifier in ids.values())


def test_same_titled_entries_are_numbered_in_reading_order() -> None:
    """The second and third of one title take -2 and -3; distinct :CREATED: tell apart."""
    found, _ = journal(
        todo("* Retro\none\n* Retro\ntwo\n* Retro\nthree\n"),
        Source(PurePosixPath("todo.org_archive"), "* Retro\nfour\n", MODIFIED),
        archives=True,
        transcripts=(),
    )
    base = f"e-{sha('Retro')}"
    assert [each.id for each in found] == [base, f"{base}-2", f"{base}-3", f"{base}-4"]
    dated, _ = journal(
        todo(
            "* Retro\n:PROPERTIES:\n:CREATED: [2026-10-02 Fri]\n:END:\n"
            "* Retro\n:PROPERTIES:\n:CREATED: [2026-10-09 Fri]\n:END:\n"
        ),
        None,
        archives=True,
        transcripts=(),
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
    found, _ = journal(
        todo(parent + "* WAITING [#A] Review [1/3] :review:work:\n* Old :ARCHIVE:\n* Plain\n"),
        Source(PurePosixPath("todo.org_archive"), "* WAITING Vendor :vendor:\n", MODIFIED),
        archives=True,
        transcripts=(),
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
    found, _ = journal(
        todo("* Old :ARCHIVE:\n* Kept\n** Gone :ARCHIVE:\n"),
        Source(PurePosixPath("todo.org_archive"), "* Vendor\n", MODIFIED),
        archives=False,
        transcripts=(),
    )
    assert [each.title for each in found] == ["Kept"]
    assert "#+OPTIONS: arch:nil " in found[0].text


def test_entry_events_stop_at_the_file_time_in_its_own_zone() -> None:
    """A timestamp after the file's time is a plan; org writes the local time."""
    london = timezone(timedelta(hours=1))
    modified = datetime(2026, 10, 22, 18, 0, tzinfo=london)  # 17:00 in UTC
    (found,), _ = journal(
        todo("* x\n[2026-10-01 Thu]\n[2026-10-22 Thu 17:30]\n<2026-10-22 Thu 18:30>\n", modified),
        None,
        archives=True,
        transcripts=(),
    )
    assert found.dates(None) == (
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 22, 17, 30, tzinfo=UTC),
    )


def test_an_undated_entry_dates_from_its_file_and_its_earlier_creation() -> None:
    """Updated is the file's time; created the existing file's, else that time too."""
    (found,), _ = journal(todo("* Undated\n"), None, archives=True, transcripts=())
    earlier = datetime(2026, 10, 1, tzinfo=UTC)
    assert found.dates(None) == (MODIFIED, MODIFIED)
    assert found.dates(earlier) == (earlier, MODIFIED)


# Names of 56 and 57 letters: with meeting- before them, at the id's 64 and past them.
FITTING, PAST = "a" * 56, "a" * 57


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("transcripts/current/2026-10-20 Tue/1.org", "t-20261020-1"),
        ("transcripts/archive/2026/2026-10/2026-10-20 Tue/1.org", "t-20261020-1"),
        ("transcripts/current/2026-10-20-standup.org", "t-20261020-2026-10-20-standup"),
        ("transcripts/current/2026-10-20 Tue/Standup_A.org", "t-20261020-Standup_A"),
        ("transcripts/current/2026-10-21 Wed/notes on x.org", "t-20261021-notes-on-x"),
        ("transcripts/archive/2026/2026-10/2026-10-21 Wed/notes on x.org", "t-20261021-notes-on-x"),
        (f"transcripts/current/2026-10-20 Tue/{LONG}.org", f"t-20261020-{'a' * 60}"),
        ("transcripts/current/2026-10-20 Tue/会議.org", f"t-20261020-{sha('会議.org')}"),
        ("transcripts/misc/a.org", f"t-{sha('a.org')}"),
        ("transcripts/misc/deeper/a.org", f"t-{sha('a.org')}"),
        ("transcripts/current/2026-13-40 Xxx/1.org", f"t-{sha('1.org')}"),
        ("meetings/2026-10-27 Tue/1.org", "t-20261027-meeting-1"),
        ("meetings/archive/2026/2026-10/2026-10-27 Tue/1.org", "t-20261027-meeting-1"),
        ("meetings/2026-10-27 Tue/notes on x.org", "t-20261027-meeting-notes-on-x"),
        (f"meetings/2026-10-27 Tue/{FITTING}.org", f"t-20261027-meeting-{FITTING}"),
        (f"meetings/2026-10-27 Tue/{PAST}.org", f"t-20261027-meeting-{sha(f'{PAST}.org')}"),
        ("meetings/2026-10-27 Tue/会議.org", f"t-20261027-meeting-{sha('会議.org')}"),
        ("meetings/a.org", f"t-{sha('meeting-a.org')}"),
    ],
)
def test_transcript_ids_name_the_day_and_the_name_else_a_slug_else_a_digest(
    path: str, expected: str
) -> None:
    """t-YYYYMMDD-, meeting- under meetings/, then the name, its slug, or its digest.

    Without a day, the digest of the name alone, meeting- before it under meetings/: no
    folder, so a move under archive/ keeps every id.
    """
    (found,), warnings = transcripts([Source(PurePosixPath(path), "", MODIFIED)], archives=True)
    assert (found.id, warnings) == (expected, [])
    assert WORKLOG_ID.fullmatch(found.id)


def test_one_day_s_first_file_in_both_folders_takes_two_ids() -> None:
    """meetings/<day>/1.org and transcripts/current/<day>/1.org: distinct, no warning."""
    found, warnings = transcripts(
        [
            Source(PurePosixPath("meetings/2026-10-27 Tue/1.org"), "", MODIFIED),
            Source(PurePosixPath("transcripts/current/2026-10-27 Tue/1.org"), "", MODIFIED),
        ],
        archives=True,
    )
    assert ([each.id for each in found], warnings) == (
        ["t-20261027-meeting-1", "t-20261027-1"],
        [],
    )


def test_a_copy_keeps_the_id_and_the_other_takes_its_whole_path() -> None:
    """The first in path order keeps it; one warning names both files."""
    copy = "archive/2026/2026-10/2026-10-20 Tue/1.org"
    original = "current/2026-10-20 Tue/1.org"
    found, warnings = transcripts([transcript(original), transcript(copy)], archives=True)
    assert [(str(each.source.path), each.id) for each in found] == [
        (f"transcripts/{copy}", "t-20261020-1"),
        (f"transcripts/{original}", f"t-{sha(f'/transcripts/{original}')}"),
    ]
    assert len(warnings) == 1
    assert f"transcripts/{copy}" in warnings[0]
    assert f"transcripts/{original}" in warnings[0]


def test_a_whole_path_digest_is_never_another_file_s_digest() -> None:
    """Written from the root, /transcripts/..., with a / that no name holds."""
    found, warnings = transcripts(
        [
            transcript("aa/a.org"),
            transcript("misc/a.org"),
            transcript("F/transcripts/misc/a.org"),
        ],
        archives=True,
    )
    assert {str(each.source.path): each.id for each in found} == {
        "transcripts/aa/a.org": f"t-{sha('a.org')}",
        "transcripts/F/transcripts/misc/a.org": f"t-{sha('/transcripts/F/transcripts/misc/a.org')}",
        "transcripts/misc/a.org": f"t-{sha('/transcripts/misc/a.org')}",
    }
    keeper = "transcripts/aa/a.org"
    assert warnings == [
        f"transcripts/F/transcripts/misc/a.org: same id as {keeper}; named by its whole path",
        f"transcripts/misc/a.org: same id as {keeper}; named by its whole path",
    ]


def test_archiving_one_of_two_files_of_one_id_never_hands_it_the_other_s() -> None:
    """The file of the first folder by name keeps it, wherever under its folder it is."""
    vendor_a, vendor_b = "current/vendor-a/notes.org", "current/vendor-b/notes.org"
    archived = "archive/2026/2026-10/vendor-b/notes.org"
    for other in (vendor_b, archived):
        for paths in ([vendor_a, other], [other, vendor_a]):
            found, warnings = transcripts([transcript(path) for path in paths], archives=True)
            ids = {each.source.path.parts[-2]: each.id for each in found}
            assert ids == {
                "vendor-a": f"t-{sha('notes.org')}",
                "vendor-b": f"t-{sha(f'/transcripts/{other}')}",
            }, paths
            assert len(warnings) == 1


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


# Plan 042's meetings: who they name, and their ids.
TUESDAY = datetime(2026, 10, 27, tzinfo=UTC)
# Seconds that 40,000 names take at most: a pass over them, not the minutes that a look
# ahead from each comma to the end of the value took.
SPLIT_S = 5


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "Alex Example, Sam Sample, Kim (not in the header)",
            ("Alex Example", "Sam Sample", "Kim (not in the header)"),
        ),
        ("Robin (payments, ops),Jo [lead, ops]", ("Robin (payments, ops)", "Jo [lead, ops]")),
        ("  Sam ,, Sam, sam ,", ("Sam", "sam")),
        ("Kim (a [b, c] d, e), Sam", ("Kim (a [b, c] d, e)", "Sam")),
        ("Alex :), Sam", ("Alex :)", "Sam")),
        ("", ()),
    ],
)
def test_participants_are_the_names_between_commas_outside_brackets(
    value: str, expected: tuple[str, ...]
) -> None:
    """Stripped, in order, each once, written as given, an annotation included."""
    assert participants(value) == expected


def test_a_long_participants_value_is_split_in_time_that_grows_with_it() -> None:
    """40,000 names, about 460 kB, as a file of 32 MiB may hold: within seconds."""
    names = tuple(f"Name {number}" for number in range(40_000))
    began = time.perf_counter()
    assert participants(", ".join(names)) == names
    assert time.perf_counter() - began < SPLIT_S


def test_meeting_ids_name_the_day_and_the_title_numbered_by_start_then_order() -> None:
    """The later start takes --2; equal starts, the order given; no slug, the title's digest."""
    early, late = TUESDAY.replace(hour=9), TUESDAY.replace(hour=14)
    assert meeting_ids(
        TUESDAY,
        [("Payments stand-up", late), ("Payments stand-up", early), ("Café: 1/1", TUESDAY)],
    ) == ["m-20261027-payments-stand-up--2", "m-20261027-payments-stand-up", "m-20261027-cafe-1-1"]
    assert meeting_ids(TUESDAY, [("Retro", late)] * 3) == [
        "m-20261027-retro",
        "m-20261027-retro--2",
        "m-20261027-retro--3",
    ]
    assert meeting_ids(TUESDAY, [("会議", TUESDAY), ("", TUESDAY)]) == [
        f"m-20261027-{sha('会議')}",
        f"m-20261027-{sha('')}",
    ]
    long = meeting_ids(TUESDAY, [(LONG, TUESDAY), (LONG, TUESDAY)])
    assert long == [f"m-20261027-{'a' * 60}", f"m-20261027-{'a' * 60}--2"]
    assert all(WORKLOG_ID.fullmatch(each) for each in long)


def test_one_slug_s_ids_never_depend_on_another_s_meetings() -> None:
    """Stand-up 2 keeps stand-up-2 beside two Stand-ups, in whichever order they come.

    In the order that archiving the first Stand-up alone leaves, the two Stand-ups swap,
    the cost that the plan's "Ids" states; titles of one slug are numbered as one title.
    """
    first, second, other = ("Stand-up", TUESDAY), ("Stand-up", TUESDAY), ("Stand-up 2", TUESDAY)
    assert meeting_ids(TUESDAY, [first, second, other]) == [
        "m-20261027-stand-up",
        "m-20261027-stand-up--2",
        "m-20261027-stand-up-2",
    ]
    assert meeting_ids(TUESDAY, [second, other, first]) == [
        "m-20261027-stand-up",
        "m-20261027-stand-up-2",
        "m-20261027-stand-up--2",
    ]
    assert meeting_ids(
        TUESDAY, [("Réunion d'équipe", TUESDAY), ("Reunion d\u2019equipe", TUESDAY)]
    ) == [
        "m-20261027-reunion-d-equipe",
        "m-20261027-reunion-d-equipe--2",
    ]


# Plan 042's transcripts: who speaks, as the caption cleaner writes turns, and when.
QUOTED = (
    "#+TITLE: Stand-up\n"
    "XQ: ask about the budget.\n"
    "[08:00] Note: outside the quotes.\n"
    "#+begin_quote\n"
    "[09:31] Alex Example: Morning.\n"
    "[09:32] You: Hello.\n"
    "[Capture 2: resumed after the connection dropped]\n"
    "[09:40] Unverified: Can you hear me?\n"
    "[09:41] Alex Example: Yes.\n"
    "#+end_quote\n"
    "XQ: between the captures.\n"
    "#+BEGIN_QUOTE\n"
    "[09:50] Sam Sample: Bye.\n"
    "#+END_QUOTE\n"
)
# Names of 64 and 65 characters, the first at the bound.
AT_BOUND, OVER_BOUND = "N" + "a" * 63, "N" + "a" * 64
BARE = (
    "#+TITLE: Payments: stand-up\n"
    "#+FILETAGS: :standup:\n"
    "* Agenda: x\n"
    "- Owner: x\n"
    "| a: b |\n"
    "DEADLINE: <2026-10-27 Tue>\n"
    "SCHEDULED: <2026-10-27 Tue 10:00>\n"
    "CLOSED: [2026-10-27 Tue 11:00]\n"
    "CLOCK: [2026-10-27 Tue 09:00]--[2026-10-27 Tue 10:00] =>  1:00\n"
    ":PROPERTIES:\n"
    ":END:\n"
    "[Capture 2: resumed]\n"
    "2nd speaker: x\n"
    "See https://example.invalid/a: x\n"
    "Jo [lead]: x\n"
    "Alex: Morning.\n"
    "[09:31] Sam: Hi.\n"
    "  Kim : indented, a blank before the colon.\n"
    "Jo (lead): x\n"
    f"{AT_BOUND}: x\n"
    f"{OVER_BOUND}: x\n"
    "Alex: Again.\n"
)


def lines(text: str) -> tuple[str, ...]:
    """Return an org text's lines, as the work log reads them."""
    return org.read(text).lines


def test_speakers_are_read_inside_the_quote_blocks_when_there_is_any() -> None:
    """In order of first speech, once; not the notes outside, nor a continuity marker."""
    assert speakers(lines(QUOTED)) == ("Alex Example", "You", "Unverified", "Sam Sample")


def test_a_bare_transcript_s_speakers_are_on_any_line_but_org_s_own() -> None:
    """No keyword, heading, list, table, planning, clock or drawer line; no bracket in a name."""
    assert speakers(lines(BARE)) == ("Alex", "Sam", "Kim", "Jo (lead)", AT_BOUND)


def test_a_turn_s_time_is_as_written_or_none() -> None:
    """The bracket before the name, whatever it holds; none without one."""
    assert turns(lines("[9:31] Alex: x\nSam: y\n[01:02:03.5] Kim: z\n")) == [
        ("9:31", "Alex"),
        (None, "Sam"),
        ("01:02:03.5", "Kim"),
    ]


@pytest.mark.parametrize(
    ("text", "began"),
    [
        ("[09:31] Alex: x\n[09:40] Sam: y\n", TUESDAY.replace(hour=9, minute=31)),
        ("[09:31:05] Alex: x\n", TUESDAY.replace(hour=9, minute=31, second=5)),
        ("[00:05] Alex: x\n", TUESDAY.replace(minute=5)),  # an offset, read as a time
        ("Alex: x\n[10:00] Sam: y\nOn <2026-10-27 Tue 14:00>.\n", TUESDAY.replace(hour=14)),
        ("[9:31] Alex: x\nOn [2026-10-27 Tue 14:00].\n", TUESDAY.replace(hour=14)),
        ("[25:00] Alex: x\n", TUESDAY),
        (
            "[09:31 AM] Alex: x\n<2026-10-26 Mon 08:00> <2026-10-27 Tue 16:00> [2026-10-27 15:00]",
            TUESDAY.replace(hour=15),
        ),
        (QUOTED, TUESDAY.replace(hour=9, minute=31)),
        ("", TUESDAY),
    ],
    ids=[
        "turn",
        "seconds",
        "offset",
        "first-untimed",
        "one-digit-hour",
        "no-time-of-day",
        "other-day",
        "quoted",
        "empty",
    ],
)
def test_a_transcript_begins_at_its_first_turn_else_its_day_s_timestamp_else_its_day(
    text: str, began: datetime
) -> None:
    """The first turn's time, strictly HH:MM or HH:MM:SS; else its day's first timestamp.

    Active or inactive, the timestamps of another day left out; else its day at midnight.
    """
    assert start(TUESDAY, lines(text)) == began


def test_a_transcript_names_its_speakers_and_a_dated_one_begins_at_its_first_turn() -> None:
    """Undated, it has no start: its dates are its events'."""
    found, _ = transcripts(
        [
            transcript("current/2026-10-27 Tue/1.org", QUOTED),
            transcript("misc/a.org", "[09:31] Alex: Said on [2026-10-01 Thu 10:00].\n"),
        ],
        archives=True,
    )
    assert [(each.people, each.start) for each in found] == [
        (("Alex Example", "You", "Unverified", "Sam Sample"), TUESDAY.replace(hour=9, minute=31)),
        (("Alex",), None),
    ]
    assert found[1].dates(None) == (datetime(2026, 10, 1, 10, tzinfo=UTC),) * 2


# Plan 042's question 1, the journal's shape on a made-up sample.
SAMPLE = (
    "* Entries\n"
    "** <2026-10-27 Tue>\n"
    "A note of the day.\n"
    "*** Payments stand-up\n"
    ":PROPERTIES:\n"
    ":MEETING: [[./meetings/2026-10-27 Tue/1.org]]\n"
    ":PARTICIPANTS: Alex Example, Sam Sample, Kim (not in the header)\n"
    ":END:\n"
    "**** Summary\n"
    "**** Details\n"
    "**** Actions\n"
    "***** TODO Send the rollback figures\n"
    "** From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)\n"
)
CONDENSED = "From <2026-10-05 Mon> to <2026-10-09 Fri> (summary)"


def archived(text: str) -> Source:
    """Return ``todo.org_archive`` holding ``text``."""
    return Source(PurePosixPath("todo.org_archive"), text, MODIFIED)


def body(document: Document) -> list[str]:
    """Return the lines that pandoc converts for a document, without the settings before them."""
    return [line for line in document.text.splitlines() if not line.startswith("#+")]


def test_the_plan_s_sample_is_a_day_a_meeting_and_a_range() -> None:
    """The day, its note and the meeting's heading line; the meeting whole; the range an entry.

    Each begins at level 1.
    """
    (record,), _ = transcripts(
        [Source(PurePosixPath("meetings/2026-10-27 Tue/1.org"), "Words.\n", MODIFIED)],
        archives=True,
    )
    found, _ = journal(todo(DECLARED + SAMPLE), None, archives=True, transcripts=[record])
    assert [(each.type, each.id, each.title, each.breadcrumb) for each in found] == [
        ("entry", f"e-{sha(CONDENSED)}", CONDENSED, ("todo.org", "Entries")),
        ("day", "d-20261027", "<2026-10-27 Tue>", ("todo.org", "Entries")),
        (
            "meeting",
            "m-20261027-payments-stand-up",
            "Payments stand-up",
            ("todo.org", "Entries", "<2026-10-27 Tue>"),
        ),
    ]
    condensed, day, meeting = found
    assert body(condensed) == [f"* {CONDENSED}"]
    assert body(day) == ["* <2026-10-27 Tue>", "A note of the day.", "** Payments stand-up"]
    assert body(meeting) == [
        "* Payments stand-up",
        ":PROPERTIES:",
        ":MEETING: [[./meetings/2026-10-27 Tue/1.org]]",
        ":PARTICIPANTS: Alex Example, Sam Sample, Kim (not in the header)",
        ":END:",
        "** Summary",
        "** Details",
        "** Actions",
        "*** TODO Send the rollback figures",
    ]
    assert meeting.people == ("Alex Example", "Sam Sample", "Kim (not in the header)")
    assert meeting.links == (("transcript", record.id),)
    assert day.dates(None) == meeting.dates(None) == (TUESDAY, TUESDAY)
    assert (day.people, day.links) == ((), ())


@pytest.mark.parametrize(
    ("own", "entries"),
    [
        ("", []),
        ("Kept for the week.\n", ["Notes"]),
        (":PROPERTIES:\n:ID: abc\n:VISIBILITY: children\n:END:\n", []),
        ("SCHEDULED: <2026-10-26 Mon>\n:PROPERTIES:\n:CATEGORY: log\n:END:\n", []),
        (":PROPERTIES:\n:ID: abc\n:END:\nKept for the week.\n", ["Notes"]),
    ],
)
def test_the_journal_s_own_lines_are_an_entry_only_when_they_hold_text(
    own: str, entries: list[str]
) -> None:
    """Whatever the journal's title; blank lines, a planning line and a drawer make none."""
    found, _ = journal(
        todo(f"* Notes\n{own}\n** <2026-10-27 Tue>\n"), None, archives=True, transcripts=()
    )
    assert [each.title for each in found if each.type == "entry"] == entries
    assert [each.id for each in found if each.type == "day"] == ["d-20261027"]


def test_a_day_is_a_date_alone_at_level_one_or_two() -> None:
    """A date at level 1 is a day; a timestamp with a time, or inactive, makes no journal."""
    found, _ = journal(
        todo(
            "* <2026-10-26 Mon>\nAlone.\n* Notes\n** <2026-10-27 Tue 10:00>\n** [2026-10-28 Wed]\n"
        ),
        None,
        archives=True,
        transcripts=(),
    )
    assert [(each.type, each.title, each.breadcrumb) for each in found] == [
        ("entry", "Notes", ("todo.org",)),
        ("day", "<2026-10-26 Mon>", ("todo.org",)),
    ]


def test_a_meeting_is_a_child_of_a_day_with_a_meeting_s_property() -> None:
    """:MEETING: or :PARTICIPANTS: alone; another drawer, or a grandchild, stays in the day.

    So does an archived heading with a meeting's property whose path runs below the day.
    """
    found, _ = journal(
        todo(
            DECLARED + "* Entries\n** <2026-10-27 Tue>\n"
            "*** Linked\n:PROPERTIES:\n:MEETING: [[./x.org]]\n:END:\n"
            "*** Named\n:PROPERTIES:\n:PARTICIPANTS: Sam\n:END:\n"
            "*** TODO Task\n:PROPERTIES:\n:ID: 6f1c\n:END:\n"
            "**** Deeper\n:PROPERTIES:\n:PARTICIPANTS: Kim\n:END:\n"
        ),
        archived(
            "* Call\n:PROPERTIES:\n:PARTICIPANTS: Kim\n"
            ":ARCHIVE_OLPATH: Entries/<2026-10-27 Tue>/Notes\n:END:\n"
        ),
        archives=True,
        transcripts=(),
    )
    assert [each.title for each in found] == ["<2026-10-27 Tue>", "Linked", "Named"]
    assert [line for line in body(found[0]) if line.startswith("*")] == [
        "* <2026-10-27 Tue>",
        "** Linked",
        "** Named",
        "** TODO Task",
        "*** Deeper",
        "** Call",
    ]


def test_days_meetings_and_entries_take_the_tags_of_the_headings_above_them() -> None:
    """As org inherits tags: the journal's, then the day's, then its own; not a child's."""
    found, _ = journal(
        todo(
            "* Entries :work:\n** <2026-10-28 Wed> :offsite:\n"
            "*** Weekly sync :sync:\n:PROPERTIES:\n:PARTICIPANTS: Sam\n:END:\n"
            "**** Notes :private:\n"
            f"** {CONDENSED} :condensed:\n"
        ),
        None,
        archives=True,
        transcripts=(),
    )
    assert [(each.type, each.labels) for each in found] == [
        ("entry", ("work", "condensed")),
        ("day", ("work", "offsite")),
        ("meeting", ("work", "offsite", "sync")),
    ]


def test_a_day_takes_the_labels_of_each_of_its_headings_each_from_its_file() -> None:
    """Each heading's tags and its file's #+FILETAGS, todo.org first, ARCHIVE once archived.

    A meeting archived alone takes the archive file's, as org gives a heading its file's.
    """
    found, _ = journal(
        todo("#+FILETAGS: :work:\n* Entries\n** <2026-10-28 Wed> :offsite:\n"),
        archived(
            "#+FILETAGS: :old:\n* <2026-10-28 Wed> :late:\n"
            ":PROPERTIES:\n:ARCHIVE_OLPATH: Entries\n:END:\n"
            "* Weekly sync\n"
            ":PROPERTIES:\n:PARTICIPANTS: Sam\n:ARCHIVE_OLPATH: Entries/<2026-10-28 Wed>\n:END:\n"
        ),
        archives=True,
        transcripts=(),
    )
    assert [(each.type, each.labels) for each in found] == [
        ("day", ("offsite", "work", "late", "old", "ARCHIVE")),
        ("meeting", ("old", "ARCHIVE")),
    ]


def test_same_titled_meetings_are_numbered_by_their_transcripts_starts() -> None:
    """The meeting without a transcript starts at its day, first; then by each transcript's."""
    lines = ["* Entries", "** <2026-10-27 Tue>"]
    for value in (
        ":MEETING: [[./transcripts/2026-10-27 Tue/late.org]]",
        ":MEETING: [[file:transcripts/2026-10-27 Tue/early.org][Record]]",
        ":PARTICIPANTS: Sam Sample",
    ):
        lines += ["*** Stand-up", ":PROPERTIES:", value, ":END:"]
    read, _ = transcripts(
        [transcript("2026-10-27 Tue/early.org"), transcript("2026-10-27 Tue/late.org")],
        archives=True,
    )
    early, late = (
        dataclasses.replace(each, start=TUESDAY.replace(hour=hour))
        for each, hour in zip(read, (9, 14), strict=True)
    )
    found, _ = journal(todo("\n".join(lines)), None, archives=True, transcripts=[late, early])
    assert [(each.id, each.start, each.links) for each in found if each.type == "meeting"] == [
        ("m-20261027-stand-up--3", late.start, (("transcript", late.id),)),
        ("m-20261027-stand-up--2", early.start, (("transcript", early.id),)),
        ("m-20261027-stand-up", TUESDAY, ()),
    ]


@pytest.mark.parametrize(
    ("value", "unlinked"),
    [
        ("[[./transcripts/2026-10-27 Tue/1.org]]", None),
        ("[[file:transcripts/2026-10-27 Tue/1.org][Transcript]]", None),
        ("transcripts/2026-10-27 Tue/1.org", None),
        ("[[./transcripts/2026-10-27 Tue/2.org]]", "transcripts/2026-10-27 Tue/2.org"),
        ("file:transcripts/2026-10-27 Tue/2.org", "transcripts/2026-10-27 Tue/2.org"),
        ("./transcripts/2026-10-27 Tue/2.org", "transcripts/2026-10-27 Tue/2.org"),
        ("transcripts/2026-10-27 Tue/2.org", "m-20261027-stand-up"),
        ("[[../todo/transcripts/2026-10-27 Tue/1.org]]", "m-20261027-stand-up"),
        ("[[/srv/todo/transcripts/2026-10-27 Tue/1.org]]", "m-20261027-stand-up"),
        ("[[transcripts/2026-10-27 Tue/1.org]]", "m-20261027-stand-up"),
        ("https://meet.example.invalid/abc", "m-20261027-stand-up"),
        ("[[https://meet.example.invalid/j/123?pwd=s3cr3tPass][Join]]", "m-20261027-stand-up"),
        ("HTTPS://meet.example.invalid/j/123?pwd=s3cr3tPass", "m-20261027-stand-up"),
        ("meet.example.invalid/j/123?pwd=s3cr3tPass", "m-20261027-stand-up"),
        ("Zoom 123 456 7890, passcode s3cr3tPass", "m-20261027-stand-up"),
        ("Teams: https://teams.example.invalid/l/1?p=s3cr3tPass", "m-20261027-stand-up"),
        ("<https://meet.example.invalid/j/123?pwd=s3cr3tPass>", "m-20261027-stand-up"),
    ],
)
def test_a_meeting_links_to_the_transcript_read_that_its_property_names(
    value: str, unlinked: str | None
) -> None:
    """From the folder of its file, and starts with it; a file not read, up, or none: no link.

    A link that reaches no transcript read is named, for the run's warning, by the file
    that it names in brackets or after file: or ./, else by the meeting's id: never as
    written, which may hold a passcode, whatever case its scheme takes.
    """
    (record,), _ = transcripts([transcript("2026-10-27 Tue/1.org")], archives=True)
    record = dataclasses.replace(record, start=TUESDAY.replace(hour=9, minute=31))
    found, named = journal(
        todo(
            "* Entries\n** <2026-10-27 Tue>\n*** Stand-up\n"
            f":PROPERTIES:\n:MEETING: {value}\n:END:\n"
        ),
        None,
        archives=True,
        transcripts=[record],
    )
    (meeting,) = [each for each in found if each.type == "meeting"]
    if unlinked is None:
        assert (meeting.links, meeting.start, named) == (
            (("transcript", record.id),),
            record.start,
            [],
        )
    else:
        assert (meeting.links, meeting.start, named) == ((), TUESDAY, [unlinked])


@pytest.mark.parametrize(
    ("value", "unlinked"),
    [
        ("[[./transcripts/current/2026-10-27 Tue/1.org]]", None),
        ("[[file:transcripts/2026-10-27 Tue/1.org][Transcript]]", None),
        ("[[./meetings/2026-10-27 Tue/1.org]]", "meetings/2026-10-27 Tue/1.org"),
        ("[[./notes/2026-10-27 Tue/1.org]]", "notes/2026-10-27 Tue/1.org"),
        (
            "[[./transcripts/current/2026-10-27 Tue/2.org]]",
            "transcripts/current/2026-10-27 Tue/2.org",
        ),
    ],
)
def test_a_link_to_a_transcript_moved_under_archive_reaches_it_by_its_id(
    value: str, unlinked: str | None
) -> None:
    """Org rewrites no link when a file moves, and the move keeps its id.

    Under transcripts/ or meetings/, a link that reaches no file read reaches the
    transcript of the id that its path gives; elsewhere, or of another id, none.
    """
    (record,), _ = transcripts(
        [transcript("archive/2026/2026-10/2026-10-27 Tue/1.org")], archives=True
    )
    record = dataclasses.replace(record, start=TUESDAY.replace(hour=9, minute=31))
    found, named = journal(
        todo(
            "* Entries\n** <2026-10-27 Tue>\n*** Stand-up\n"
            f":PROPERTIES:\n:MEETING: {value}\n:END:\n"
        ),
        None,
        archives=True,
        transcripts=[record],
    )
    (meeting,) = [each for each in found if each.type == "meeting"]
    if unlinked is None:
        assert (meeting.links, meeting.start, named) == (
            (("transcript", record.id),),
            record.start,
            [],
        )
    else:
        assert (meeting.links, meeting.start, named) == ((), TUESDAY, [unlinked])


def test_a_meeting_linking_another_day_s_transcript_starts_at_its_own_day() -> None:
    """A recurring meeting's heading copied with its link: the link kept, the date its day's."""
    (record,), _ = transcripts([transcript("2026-10-21 Wed/1.org")], archives=True)
    record = dataclasses.replace(record, start=datetime(2026, 10, 21, 9, tzinfo=UTC))
    text = "".join(
        f"** {day}\n*** Weekly sync\n:PROPERTIES:\n"
        ":MEETING: [[./transcripts/2026-10-21 Wed/1.org]]\n:END:\n"
        for day in ("<2026-10-21 Wed>", "<2026-10-28 Wed>")
    )
    found, _ = journal(todo(f"* Entries\n{text}"), None, archives=True, transcripts=[record])
    linked = (("transcript", record.id),)
    assert [(each.id, each.start, each.links) for each in found if each.type == "meeting"] == [
        ("m-20261021-weekly-sync", record.start, linked),
        ("m-20261028-weekly-sync", datetime(2026, 10, 28, tzinfo=UTC), linked),
    ]


def test_only_a_meeting_s_link_that_reaches_nothing_is_returned_in_meetings_order() -> None:
    """Not a meeting without :MEETING:, nor one archived and left out; days in their order."""
    text = (
        "* Entries\n** <2026-10-26 Mon>\n"
        "*** Named\n:PROPERTIES:\n:PARTICIPANTS: Sam\n:END:\n"
        "*** Gone :ARCHIVE:\n:PROPERTIES:\n:MEETING: [[./gone.org]]\n:END:\n"
        "*** First\n:PROPERTIES:\n:MEETING: [[./first.org]]\n:END:\n"
        "** <2026-10-27 Tue>\n*** Second\n:PROPERTIES:\n:MEETING: [[../second.org]]\n:END:\n"
    )
    _, unlinked = journal(todo(text), None, archives=False, transcripts=())
    assert unlinked == ["first.org", "m-20261027-second"]


@pytest.mark.parametrize(
    ("unread", "kinds"),
    [
        (set(), ["entry", "day", "meeting", "transcript", "transcript"]),
        ({"todo.org"}, []),
        ({"todo.org_archive"}, []),
        ({"transcripts/misc/x.org"}, ["entry", "day", "transcript"]),
        ({"transcripts, meetings"}, ["entry", "day", "transcript"]),
    ],
)
def test_a_file_not_read_holds_back_each_document_that_draws_on_it(
    unread: set[str], kinds: list[str]
) -> None:
    """The journal's files: every one; another: the meetings and what links one."""
    read, _ = transcripts(
        [
            Source(PurePosixPath("meetings/2026-10-27 Tue/1.org"), "Words.\n", MODIFIED),
            transcript("misc/alone.org"),
        ],
        archives=True,
    )
    found, _ = journal(todo(DECLARED + SAMPLE), None, archives=True, transcripts=read)
    documents = [*found, *linked_back(read, found)]
    written = writable(documents, unread)
    assert [each.type for each in written] == kinds
    assert all(each.links == () for each in written if unread)


def test_the_work_log_s_relations_are_among_the_front_matter_s() -> None:
    """The two layers name each relation apart; a rename on one side alone fails here."""
    assert {TRANSCRIBED, SUMMARY} <= set(RELATIONS)


def test_a_transcript_links_back_to_each_meeting_that_links_to_it() -> None:
    """By summary, in the meetings' order; a transcript that no meeting names, to none."""
    read, _ = transcripts(
        [transcript("2026-10-27 Tue/1.org"), transcript("2026-10-27 Tue/2.org")], archives=True
    )
    lines = ["* Entries", "** <2026-10-27 Tue>"]
    for title in ("Stand-up", "Retro"):
        value = "[[./transcripts/2026-10-27 Tue/1.org]]"
        lines += [f"*** {title}", ":PROPERTIES:", f":MEETING: {value}", ":END:"]
    found, _ = journal(todo("\n".join(lines)), None, archives=True, transcripts=read)
    assert [(each.id, each.links) for each in linked_back(read, found)] == [
        ("t-20261027-1", (("summary", "m-20261027-stand-up"), ("summary", "m-20261027-retro"))),
        ("t-20261027-2", ()),
    ]


# A meeting with a section, then archived headings, as org writes them: a task archived
# from a meeting met later in the file, a meeting archived alone, a task of the day, and
# a task of a meeting that no longer is.
JOINED = (
    "* Entries\n** <2026-10-27 Tue>\nThe day.\n"
    "*** Stand-up\n:PROPERTIES:\n:PARTICIPANTS: Sam\n:END:\n**** Actions\n"
)
ARCHIVED = (
    "* DONE Retro task\n:PROPERTIES:\n:ARCHIVE_OLPATH: Entries/<2026-10-27 Tue>/Retro\n:END:\n"
    "Retro task words.\n"
    "* Retro :ops:\n:PROPERTIES:\n:PARTICIPANTS: Kim\n"
    ":ARCHIVE_OLPATH: Entries/<2026-10-27 Tue>\n:END:\nRetro words.\n"
    "* DONE Pay\n:PROPERTIES:\n:ARCHIVE_OLPATH: Entries/<2026-10-27 Tue>\n:END:\nPaid.\n"
    "* DONE Close it\n:PROPERTIES:\n"
    ":ARCHIVE_OLPATH: Entries/<2026-10-27 Tue>/Stand-up/Actions\n:END:\nClosed.\n"
    "* DONE Lost\n:PROPERTIES:\n:ARCHIVE_OLPATH: Entries/<2026-10-27 Tue>/Gone/Actions\n:END:\n"
)


def test_archived_headings_join_their_day_or_the_meeting_their_path_names() -> None:
    """A meeting alone is one of its day; else the meeting named next, else the day, at level 2."""
    found, _ = journal(todo(DECLARED + JOINED), archived(ARCHIVED), archives=True, transcripts=())
    assert [(each.type, each.id, each.labels) for each in found] == [
        ("day", "d-20261027", ()),
        ("meeting", "m-20261027-stand-up", ()),
        ("meeting", "m-20261027-retro", ("ops", "ARCHIVE")),
    ]
    day, standup, retro = found
    assert [line for line in body(day) if not line.startswith(":")] == [
        "* <2026-10-27 Tue>",
        "The day.",
        "** Stand-up",
        "** Retro :ops:",
        "** DONE Pay",
        "Paid.",
        "** DONE Lost",
    ]
    assert [line for line in body(standup) if not line.startswith(":")] == [
        "* Stand-up",
        "** Actions",
        "** DONE Close it",
        "Closed.",
    ]
    assert [line for line in body(retro) if not line.startswith(":")] == [
        "* Retro :ops:",
        "Retro words.",
        "** DONE Retro task",
        "Retro task words.",
    ]
    assert retro.breadcrumb == ("todo.org_archive", "Entries", "<2026-10-27 Tue>")
    assert retro.people == ("Kim",)


# Meetings whose titles hold a /, a link or an empty cookie, and the tasks archived from
# them, each :ARCHIVE_OLPATH: as Emacs 31.1 wrote it for these made-up headings; the last
# names a part of a title alone.
SLASHED = "".join(
    f"*** {title}\n:PROPERTIES:\n:PARTICIPANTS: Sam\n:END:\n"
    for title in (
        "1/1 with Robin",
        "1",
        "A/B review",
        "Sync on [[https://example.invalid/PRB-1][PRB-1]]",
        "Ledger review [/]",
    )
)
FROM_SLASHED = "".join(
    f"* DONE {task}\n:PROPERTIES:\n:ARCHIVE_OLPATH: Entries/<2026-10-27 Tue>/{path}\n:END:\n"
    for task, path in (
        ("Fourth", "1/1 with Robin/Actions"),
        ("Fifth", "1/Actions"),
        ("Decide", "A/B review/Actions"),
        ("Close it", "Sync on PRB-1/Actions"),
        ("Third", "Ledger review [/]/Actions"),
        ("Sixth", "1/1 with Robin"),
        ("Seventh", "A/B"),
    )
)


def test_an_archived_task_joins_the_meeting_whose_title_its_path_holds_as_org_writes_it() -> None:
    """Across the / that org writes unescaped, the longest title of the day that begins it."""
    found, _ = journal(
        todo(f"* Entries\n** <2026-10-27 Tue>\n{SLASHED}"),
        archived(FROM_SLASHED),
        archives=True,
        transcripts=(),
    )
    held = {
        each.title: [line for line in body(each) if not line.startswith(":")][1:] for each in found
    }
    assert held == {
        "<2026-10-27 Tue>": [
            "** 1/1 with Robin",
            "** 1",
            "** A/B review",
            "** Sync on [[https://example.invalid/PRB-1][PRB-1]]",
            "** Ledger review [/]",
            "** DONE Seventh",
        ],
        "1/1 with Robin": ["** DONE Fourth", "** DONE Sixth"],
        "1": ["** DONE Fifth"],
        "A/B review": ["** DONE Decide"],
        "Sync on [[https://example.invalid/PRB-1][PRB-1]]": ["** DONE Close it"],
        "Ledger review": ["** DONE Third"],
    }


def test_a_day_that_archived_headings_alone_name_takes_its_title_from_their_path() -> None:
    """Archived, from the archive file, its journal the path's part before it."""
    found, _ = journal(todo(""), archived(ARCHIVED), archives=True, transcripts=())
    day = found[0]
    assert (day.id, day.title, day.breadcrumb, day.labels) == (
        "d-20261027",
        "<2026-10-27 Tue>",
        ("todo.org_archive", "Entries"),
        ("ARCHIVE",),
    )
    assert [each.id for each in found[1:]] == ["m-20261027-retro"]


def test_without_archives_archived_days_and_meetings_are_left_out() -> None:
    """The archive file, a day tagged ARCHIVE with its meetings, a meeting tagged ARCHIVE."""
    text = (
        "* Entries\n** <2026-10-26 Mon> :ARCHIVE:\n"
        "*** Old\n:PROPERTIES:\n:PARTICIPANTS: Sam\n:END:\n"
        "** <2026-10-27 Tue>\n*** Kept\n:PROPERTIES:\n:PARTICIPANTS: Sam\n:END:\n"
        "*** Gone :ARCHIVE:\n:PROPERTIES:\n:PARTICIPANTS: Kim\n:END:\n"
    )
    kept, _ = journal(todo(text), archived(ARCHIVED), archives=False, transcripts=())
    assert [each.id for each in kept] == ["d-20261027", "m-20261027-kept"]
    assert "#+OPTIONS: arch:nil " in kept[0].text
    every, _ = journal(todo(text), archived(ARCHIVED), archives=True, transcripts=())
    assert [(each.id, each.labels) for each in every] == [
        ("d-20261026", ("ARCHIVE",)),
        ("m-20261026-old", ("ARCHIVE",)),
        ("d-20261027", ()),
        ("m-20261027-kept", ()),
        ("m-20261027-gone", ("ARCHIVE",)),
        ("m-20261027-retro", ("ops", "ARCHIVE")),
    ]
