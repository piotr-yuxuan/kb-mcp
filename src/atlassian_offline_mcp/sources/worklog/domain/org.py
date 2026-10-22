"""Org's syntax, as the work log needs it: no other module knows it.

It reads a file's settings (the keywords it declares, ``#+TITLE``, ``#+FILETAGS``), its
headings (stars, keyword, priority, ``COMMENT``, title, statistics cookies, tags), a
heading's property drawer and planning line, and timestamps; and it writes what pandoc
reads for one document. It reads leniently: a line that matches no rule is text, and a
timestamp that names no real day or time is none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
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
# An active or inactive timestamp: a date, a day's name in any language, a time or a
# range of times within the day, then repeaters and warnings.
TIMESTAMP = re.compile(
    r"[<\[]([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[ \t]+[^\s\d<>\[\]+-]+)?"
    r"(?:[ \t]+([0-9]{1,2}):([0-9]{2})(?:-[0-9]{1,2}:[0-9]{2})?)?"
    r"(?:[ \t]+[.+]?[+-][0-9]+[hdwmy](?:/[0-9]+[hdwmy])?)*[ \t]*[>\]]"
)
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
    """A top-level heading and the lines below it, up to the next top-level heading."""

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
