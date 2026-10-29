"""Org's syntax, as the work log needs it: no other module knows it.

It reads a file's settings (the keywords it declares, ``#+TITLE``, ``#+FILETAGS``), its
headings (stars, keyword, priority, ``COMMENT``, title, statistics cookies, tags), its
outline (a heading's own lines, then its children), a heading's property drawer and
planning line, timestamps, a day's title, a link to a file and the lines of quote
blocks; and it writes what pandoc reads for one document, its headings moved to another
level. It reads leniently: a line that matches no rule is text, and a timestamp that
names no real day or time is none.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence

# The keywords of a file that declares none, as org and pandoc have them.
DEFAULT_KEYWORDS = frozenset({"TODO", "DONE"})
ARCHIVE = "ARCHIVE"
# A heading: stars, then blanks and its text, which may be empty.
HEADING = re.compile(r"(\*+)[ \t]+(.*?)[ \t]*")
PRIORITY = re.compile(r"(\[#[A-Za-z0-9]+\])(?:[ \t]+|$)")
COMMENT = re.compile(r"COMMENT(?:[ \t]+|$)")
# Tags end a heading: names between colons, after a blank or alone.
TAGS = re.compile(r"(?:^|[ \t]+):((?:[\w@#%]+:)+)$")
# Statistics cookies: [1/3], [33%], and the empty [/] and [%].
COOKIE = re.compile(r"\[[0-9]*(?:/[0-9]*|%)\]")
# The cookies that org leaves out of a title in an outline path: filled ones alone.
FILLED_COOKIE = re.compile(r"\[[0-9]+(?:/[0-9]+|%)\]")
# A link in brackets within a text: its target, then its description, if any.
TEXT_LINK = re.compile(r"\[\[([^\[\]]+)\](?:\[(.+?)\])?\]")
# A setting of the file, such as #+TODO: or #+FILETAGS:; its name in any case.
SETTING = re.compile(r"#\+([A-Za-z_]+):(?:[ \t]+(.*?))?[ \t]*")
DECLARING = frozenset({"TODO", "SEQ_TODO", "TYP_TODO"})
# Settings of a file that would override those given to pandoc before it.
OVERRIDING = frozenset({"OPTIONS", "EXCLUDE_TAGS", "SELECT_TAGS"})
# A keyword's fast-access key and logging, as in WAIT(w@/!); | ends the open keywords.
FAST_ACCESS = re.compile(r"\(.*\)$")
DONE_MARK = "|"
PLANNING = re.compile(r"[ \t]*(?:SCHEDULED|DEADLINE|CLOSED):")
DRAWER_START = ":PROPERTIES:"
DRAWER_END = ":END:"
PROPERTY = re.compile(r"[ \t]*:([^:\s]+):(?:[ \t]+(.*?))?[ \t]*")
# A timestamp's date, then a day's name in any language, which org does not check.
DATE = r"([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[ \t]+[^\s\d<>\[\]+-]+)?"
# An active or inactive timestamp: a date, a time or a range of times within the day,
# then repeaters and warnings.
TIMESTAMP = re.compile(
    rf"[<\[]{DATE}"
    r"(?:[ \t]+([0-9]{1,2}):([0-9]{2})(?:-[0-9]{1,2}:[0-9]{2})?)?"
    r"(?:[ \t]+[.+]?[+-][0-9]+[hdwmy](?:/[0-9]+[hdwmy])?)*[ \t]*[>\]]"
)
# A day's title: one active timestamp of a date alone, such as <2026-10-28 Wed>.
DAY_TITLE = re.compile(rf"<{DATE}>")
# A link in brackets, its description optional: its target, which holds no bracket.
BRACKET_LINK = re.compile(r"\[\[([^\[\]]+)\](?:\[.*\])?\]")
# A link's type, before its path, such as https: or file:; then those of a link to a file.
LINK_TYPE = re.compile(r"([a-z][a-z0-9+-]*):")
FILE_TYPES = frozenset({"file", "file+sys", "file+emacs"})
# How an untyped target in brackets begins when org reads it as a file; any other target
# is a search for a heading.
FILE_TARGETS = ("./", "../", "/", "~")
# What follows a file link's path when it holds a search within the file, as ::*Heading.
SEARCH = "::"
# The lines that open and close a quote block, in any case, its options after a blank.
QUOTE_START = re.compile(r"[ \t]*#\+begin_quote(?:[ \t].*)?", re.IGNORECASE)
QUOTE_END = re.compile(r"[ \t]*#\+end_quote[ \t]*", re.IGNORECASE)
# What pandoc reads before a document: subtrees tagged noexport kept, drawers and planning
# lines kept, headings to level 6, _, ^ and -- as written, archived subtrees as asked.
EXCLUDE_TAGS = "#+EXCLUDE_TAGS:"
OPTIONS = "#+OPTIONS: arch:{} d:t p:t H:6 ^:nil -:nil"


@dataclass(frozen=True)
class Heading:
    """A heading's parts.

    ``text`` is what follows its keyword, priority and ``COMMENT``, without its tags;
    ``priority`` is its cookie as written, such as ``[#A]``.
    """

    level: int
    keyword: str | None
    priority: str | None
    comment: bool
    text: str
    tags: tuple[str, ...]

    @property
    def title(self) -> str:
        """Its words without statistics cookies, single-spaced."""
        return " ".join(COOKIE.sub(" ", self.text).split())

    @property
    def outline_title(self) -> str:
        """Its text as org writes it in an outline path, such as ``:ARCHIVE_OLPATH:``.

        Filled statistics cookies are left out, ``[1/3]`` or ``[33%]`` but not ``[/]``;
        then each link is its description, else its target; then it is trimmed. Blanks
        within stay as written, and a ``/`` within is not escaped.
        """
        text = FILLED_COOKIE.sub("", self.text)
        return TEXT_LINK.sub(lambda link: link[2] or link[1], text).strip()

    @property
    def line(self) -> str:
        """Write it back as one line, without ``COMMENT``; a blank always follows the stars."""
        tags = f":{':'.join(self.tags)}:" if self.tags else None
        words = [self.keyword, self.priority, self.text, tags]
        return f"{'*' * self.level} {' '.join(word for word in words if word)}"


def heading(line: str, keywords: Collection[str]) -> Heading | None:
    """Read a line as a heading, or return None when it is not one.

    Its keyword is one of ``keywords``; ``COMMENT`` follows the keyword and the priority.
    """
    match = HEADING.fullmatch(line)
    if match is None:
        return None
    rest = match[2]
    first = rest.split(maxsplit=1)[0] if rest else ""
    keyword = first if first in keywords else None
    if keyword is not None:
        rest = rest[len(keyword) :].lstrip(" \t")
    priority = PRIORITY.match(rest)
    rest = rest[priority.end() :] if priority else rest
    comment = COMMENT.match(rest)
    rest = rest[comment.end() :] if comment else rest
    tags = TAGS.search(rest)
    return Heading(
        level=len(match[1]),
        keyword=keyword,
        priority=priority[1] if priority else None,
        comment=comment is not None,
        text=rest[: tags.start()] if tags else rest,
        tags=tuple(tags[1].strip(":").split(":")) if tags else (),
    )


@dataclass(frozen=True)
class Subtree:
    """A heading and the lines below it, up to the next heading of its level or higher.

    ``read`` gives a file's top-level subtrees, and ``children`` the subtrees below one.
    """

    heading: Heading
    lines: tuple[str, ...]  # its heading's line first

    @property
    def properties(self) -> dict[str, str]:
        """Return the properties of its heading's drawer, by name in upper case.

        The drawer follows the heading, or its planning line; one never closed is text.
        """
        start = 2 if len(self.lines) > 1 and PLANNING.match(self.lines[1]) else 1
        if len(self.lines) <= start or self.lines[start].strip() != DRAWER_START:
            return {}
        found: dict[str, str] = {}
        for line in self.lines[start + 1 :]:
            if line.strip() == DRAWER_END:
                return found
            match = PROPERTY.fullmatch(line)
            if match:
                found[match[1].upper()] = match[2] or ""
        return {}

    @property
    def own(self) -> tuple[str, ...]:
        """Return its heading's line and the lines that follow it, up to its first child."""
        first_child = next(
            (index for index, line in enumerate(self.lines[1:], 1) if HEADING.fullmatch(line)),
            len(self.lines),
        )
        return self.lines[:first_child]

    def children(self, keywords: Collection[str]) -> tuple[Subtree, ...]:
        """Return its children in order: the subtrees of the headings below its own lines.

        As org reads an outline, a child holds the lines up to the next heading of its
        level or higher, so that a grandchild stays in its child, and a heading two levels
        down with none between is a child. ``keywords`` are the file's.
        """
        found: list[tuple[Heading, list[str]]] = []
        for line in self.lines[1:]:
            child = heading(line, keywords)
            if child is not None and (not found or child.level <= found[-1][0].level):
                found.append((child, [line]))
            elif found:
                found[-1][1].append(line)
        return tuple(Subtree(first, tuple(rest)) for first, rest in found)


@dataclass(frozen=True)
class OrgFile:
    """An org file's settings, keywords, headings and top-level subtrees."""

    lines: tuple[str, ...]
    declarations: tuple[str, ...]  # the lines declaring its keywords, as written
    keywords: frozenset[str]
    title: str | None
    filetags: tuple[str, ...]
    headings: tuple[Heading, ...]
    subtrees: tuple[Subtree, ...]


def read(text: str, inherited: OrgFile | None = None) -> OrgFile:
    """Read an org file.

    Its keywords are those it declares, else those of the ``inherited`` file, else TODO
    and DONE; the text before its first heading belongs to no subtree.
    """
    # Org's lines end at a line feed alone, not at the other breaks Python knows.
    lines = tuple(line.removesuffix("\r") for line in text.removesuffix("\n").split("\n"))
    settings = [
        (match[1].upper(), match[2] or "", line)
        for line in lines
        if (match := SETTING.fullmatch(line))
    ]
    declared = [(value, line) for name, value, line in settings if name in DECLARING]
    declarations = tuple(line for _, line in declared)
    words = {
        FAST_ACCESS.sub("", word)
        for value, _ in declared
        for word in value.split()
        if word != DONE_MARK
    }
    if not declared and inherited is not None:
        declarations, words = inherited.declarations, set(inherited.keywords)
    keywords = frozenset(words) or DEFAULT_KEYWORDS
    subtrees: list[tuple[Heading, list[str]]] = []
    headings: list[Heading] = []
    for line in lines:
        found = heading(line, keywords)
        if found is not None:
            headings.append(found)
        if found is not None and found.level == 1:
            subtrees.append((found, [line]))
        elif subtrees:
            subtrees[-1][1].append(line)
    return OrgFile(
        lines=lines,
        declarations=declarations,
        keywords=keywords,
        title=" ".join(value for name, value, _ in settings if name == "TITLE" and value) or None,
        filetags=tuple(
            tag
            for name, value, _ in settings
            if name == "FILETAGS"
            for tag in value.replace(":", " ").split()
        ),
        headings=tuple(headings),
        subtrees=tuple(Subtree(first, tuple(rest)) for first, rest in subtrees),
    )


def shifted(lines: Sequence[str], level: int = 1) -> list[str]:
    """Return a subtree's lines, its headings moved so that its first is at ``level``.

    Each heading moves by as many levels as the first, so that a subtree, or a heading's
    own lines and some of its children, keep their shape; no heading may be above the
    first. Only the stars change: a heading keeps its keyword, priority, ``COMMENT``,
    title and tags as written, and the other lines are left alone.
    """
    found = [HEADING.fullmatch(line) for line in lines]
    first = next((stars.end(1) for stars in found if stars), level)
    return [
        line if stars is None else "*" * (stars.end(1) - first + level) + line[stars.end(1) :]
        for line, stars in zip(lines, found, strict=True)
    ]


def timestamps(lines: Iterable[str]) -> list[datetime]:
    """Return the moment of each timestamp in the lines, read as UTC, as written.

    A range's start stands for it; a timestamp naming no real day or time is left out.
    """
    found: list[datetime] = []
    for line in lines:
        for match in TIMESTAMP.finditer(line):
            year, month, day, hour, minute = (int(part or 0) for part in match.groups())
            try:
                found.append(datetime(year, month, day, hour, minute, tzinfo=UTC))
            except ValueError:
                continue
    return found


def date_title(title: str) -> datetime | None:
    """Return the day that a title names, at midnight UTC, or None when it names none.

    A day's title is one active timestamp of a date alone, its day's name optional, such
    as ``<2026-10-28 Wed>``: a heading's ``title``, or a part of the ``:ARCHIVE_OLPATH:``
    that org writes when it archives a subtree. A time, a repeater, an inactive
    timestamp, other words, or a date that is no real day make none.
    """
    match = DAY_TITLE.fullmatch(title)
    if match is not None:
        with contextlib.suppress(ValueError):  # <2026-02-30 Mon> names no day
            return datetime(int(match[1]), int(match[2]), int(match[3]), tzinfo=UTC)
    return None


def link_target(value: str) -> PurePosixPath | None:
    """Return the file that a link names, relative to the folder of the file that holds it.

    The link is as org writes one to a file, ``[[./path]]`` or ``[[file:path][text]]``,
    or a path alone, after ``file:`` or not; a search after ``::`` is not part of the
    path. None for a link of another type, such as ``https:``; for an untyped target in
    brackets that org reads as a search for a heading, ``[[path]]``; and for a path that
    is absolute, from a home folder (``~``), through ``..``, or empty.
    """
    bracket = BRACKET_LINK.fullmatch(value)
    target = bracket[1] if bracket else value
    kind = LINK_TYPE.match(target)
    if kind is not None and kind[1] not in FILE_TYPES:
        return None
    if bracket and kind is None and not target.startswith(FILE_TARGETS):
        return None
    path = PurePosixPath((target[kind.end() :] if kind else target).partition(SEARCH)[0])
    if not path.parts or path.is_absolute() or path.parts[0].startswith("~") or ".." in path.parts:
        return None
    return path


def quoted(lines: Iterable[str]) -> list[str] | None:
    """Return the lines inside the quote blocks, in order, or None when there is none.

    A block runs from a line ``#+begin_quote`` to the next ``#+end_quote``, in any case
    and indented or not; one never closed is no block, and its lines are text, as org
    reads them. A block inside a block ends at the first ``#+end_quote``.
    """
    found: list[str] | None = None
    block: list[str] | None = None  # the lines of the block open, if any
    for line in lines:
        if block is None:
            if QUOTE_START.fullmatch(line):
                block = []
        elif QUOTE_END.fullmatch(line):
            found, block = [*(found or []), *block], None
        else:
            block.append(line)
    return found


def pandoc_input(
    declarations: Sequence[str], lines: Iterable[str], keywords: Collection[str], *, archives: bool
) -> str:
    """Write what pandoc reads for one document: its settings, then its lines.

    The settings are the keywords' ``declarations``, an empty ``#+EXCLUDE_TAGS:`` and the
    options, archived subtrees kept or left out as ``archives`` says. A line of the
    document that would override them is left out, and ``COMMENT`` is taken out of each
    heading, so that pandoc drops neither.
    """
    body: list[str] = []
    for line in lines:
        setting = SETTING.fullmatch(line)
        if setting is not None and setting[1].upper() in OVERRIDING:
            continue
        found = heading(line, keywords)
        body.append(found.line if found is not None and found.comment else line)
    options = OPTIONS.format("t" if archives else "nil")
    return "\n".join([*declarations, EXCLUDE_TAGS, options, *body, ""])
