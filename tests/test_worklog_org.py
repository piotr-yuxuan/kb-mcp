"""Org's syntax, as plan 017 reads it.

The expectations come from org's own syntax: a title is a heading without its keyword,
priority, tags and statistics cookies; keywords are those a file declares. Generated
cases are enumerated.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from atlassian_offline_mcp.sources.worklog.domain import org

KEYWORDS = frozenset({"TODO", "WAITING", "DONE"})
DECLARED = "#+TODO: TODO WAITING | DONE\n"
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
# Minutes between generated moments: a prime, so that hours, minutes and days vary.
STRIDE = 7919


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
