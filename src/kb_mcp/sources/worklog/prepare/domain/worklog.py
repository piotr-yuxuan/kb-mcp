"""The work log's documents: what each is, and its id, title, dates and revision.

The journal of ``todo.org`` and ``todo.org_archive`` makes a document of each day and of
each meeting, and the other top-level headings are entries; a transcript is an org file
under ``transcripts/`` or ``meetings/``. The rules are those of plan 017's "Documents and
their identity" and "Front matter and conversion", and plan 042's "Days and meetings:
the rule", "Ids", "Participants" and "Links"; org's syntax is read by ``org``.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Self

from pydantic import ConfigDict, Field, model_validator

from kb_mcp.kernel.names import (
    DAY_TYPE,
    ENTRY_TYPE,
    MEETING_TYPE,
    TRANSCRIPT_TYPE,
    WORKLOG_TYPES,
    RefusedError,
    require,
)
from kb_mcp.kernel.record import Record
from kb_mcp.kernel.slug import slug
from kb_mcp.mirror.domain.mirror import PARTICIPANT, FrontMatter
from kb_mcp.sources.worklog.prepare.domain import org

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

TODO = "todo.org"
TODO_ARCHIVE = "todo.org_archive"
# What every document draws on: the work log's folder itself, and the journal's two
# files, whence every day, meeting and entry, and every transcript's links back.
SHARED = frozenset({".", TODO, TODO_ARCHIVE})
# What a problem of reading holds back, besides a transcript's id: every document, or
# the transcripts under a folder or past the bound, which the run cannot name.
EVERY_DOCUMENT = "every document"
UNDER_IT = "the transcripts not read under it"
# The folders of transcripts: those saved, and the meeting files that a meeting's
# :MEETING: links, as the user's meeting notes save them.
MEETINGS_FOLDER = "meetings"
TRANSCRIPT_FOLDERS = ("transcripts", MEETINGS_FOLDER)
# What a file under meetings/ takes before its name in its id, so that one day's 1.org
# in both folders never shares an id.
MEETING_FILE = "meeting-"
# The folder of each that holds archived transcripts.
ARCHIVED = "archive"
ORG = ".org"
# The work log's name as a source, in its documents' front matter.
SOURCE = "worklog"
# A document's revision: a digest of what pandoc converts, and how.
WORKLOG_REVISION = re.compile(r"[0-9a-f]{16}")
# The roles of the work log's documents, which hold no other: a meeting's participants
# and a transcript's speakers.
WORKLOG_ROLES = frozenset({PARTICIPANT})
# The keys of the front matter that Confluence or Jira fills, and the work log never.
NOT_FILLED = ("key", "space", "project", "issue_type", "version")
# The relations of a meeting to its transcript, and of a transcript to each meeting
# that links to it, as the mirror's front matter names them.
TRANSCRIBED = "transcript"
SUMMARY = "summary"
CURRENT = "current"
DIGITS = 16
# What comes between a meeting's id and its number: two dashes, which no slug holds, so
# that a numbered id is never another title's, as Stand-up 2's is stand-up-2.
NUMBERED = "--"
# The date that begins a folder's or a file's name.
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# The deepest level of a day's heading: 1, or 2 below the journal.
DAY_LEVEL = 2
# The level of what joins a day's or a meeting's document, which begins at level 1: one
# below it, whatever level its day's heading had.
JOINED_LEVEL = 2
# The properties of a meeting's drawer: the file of its transcript, and its people. A
# child of a day with either is a meeting.
LINKED = "MEETING"
NAMED = "PARTICIPANTS"
# Where org's archiving writes the titles above a subtree, joined by /.
OUTLINE_PATH = "ARCHIVE_OLPATH"
# The brackets within which a comma is a name's, as in Kim (payments, ops).
OPENING = "(["
CLOSING = ")]"
# A turn of a transcript: an optional [time], which dates nothing, and a blank, then its
# speaker's name, of at most 64 characters, beginning with a letter and holding no colon
# or bracket, then ": ".
TURN = re.compile(r"[ \t]*(?:\[[^\[\]]*\][ \t]+)?([^\W\d_][^:\[\]]{0,63}?)[ \t]*: ")
# Org's planning and clock lines, which read as turns.
NOT_SPEAKERS = frozenset({"SCHEDULED", "DEADLINE", "CLOSED", "CLOCK"})


class OrgText(Record):
    """An org file of the work log, as read.

    ``modified`` is aware, in the time zone of the machine that read it: org writes the
    time of that zone, so its timestamps are compared with that time as written.
    """

    path: PurePosixPath  # relative to the work log's folder
    text: str
    modified: datetime

    @property
    def fetched_at(self) -> datetime:
        """Its modification time, in UTC."""
        return self.modified.astimezone(UTC)

    def events(self, lines: Iterable[str]) -> tuple[datetime, ...]:
        """Return the timestamps of its lines up to its modification time; a later one is a plan."""
        limit = self.modified.replace(tzinfo=UTC)
        return tuple(moment for moment in org.timestamps(lines) if moment <= limit)


class WorklogDocument(Record):
    """One document of the work log: what the mirror says of it, and what pandoc converts.

    ``people`` names its participants as written; ``links`` holds each relation to another
    document of the work log and that document's id, such as a meeting's ``transcript``
    and that transcript's ``summary``.
    """

    type: str  # entry, day, meeting or transcript
    id: str
    title: str
    status: str
    labels: tuple[str, ...]
    breadcrumb: tuple[str, ...]
    people: tuple[str, ...]
    links: tuple[tuple[str, str], ...]
    text: str  # pandoc's input
    events: tuple[datetime, ...]
    day: datetime | None  # a day's, a meeting's or a dated transcript's, at midnight UTC
    file: OrgText

    def dates(self, created: datetime | None) -> tuple[datetime, datetime]:
        """Return when it was created and last updated.

        Its day, else its earliest and latest events; without any, its file's
        modification time, created being ``created``, the existing file's, when given.
        """
        if self.day is not None:
            return self.day, self.day
        if self.events:
            return min(self.events), max(self.events)
        return created or self.file.fetched_at, self.file.fetched_at


class WorklogFrontMatter(FrontMatter):
    """The front matter of a document of the work log: every source's rules, and its own."""

    @model_validator(mode="after")
    def check_worklog(self) -> Self:
        """Refuse what the layout's table rules out for the work log.

        A source or type not the work log's, a key that it never fills, an id off its
        type's rule, so that a day never bears a meeting's, a revision off
        ``WORKLOG_REVISION``, and a role of another source.
        """
        if self.source != SOURCE or self.type not in WORKLOG_TYPES:
            message = "type: not one of the source's types"
            raise RefusedError(message)
        filled = [name for name in NOT_FILLED if getattr(self, name) is not None]
        if filled:
            message = f"{', '.join(filled)}: never the work log's"
            raise RefusedError(message)
        require(WORKLOG_TYPES[self.type].id_rule, self.id, "id")
        require(WORKLOG_REVISION, self.revision, "revision")
        if any(person.role not in WORKLOG_ROLES for person in self.people):
            message = "people: a role of another source"
            raise RefusedError(message)
        return self


class PlacedHeading(Record):
    """A heading of ``todo.org`` or its archive, and the titles above it: org's outline.

    Below the journal, the outline is the journal's title, then for a meeting its day's; at
    the top of a file, it is what org wrote in ``:ARCHIVE_OLPATH:`` when it archived the
    heading, else empty. It is ``archived`` when its file is the archive or it, or a
    heading above it, is tagged ARCHIVE; ``inherited`` are the tags of the headings above
    it in its file, which org gives it too.
    """

    subtree: org.Subtree
    outline: tuple[str, ...]
    file: OrgText
    parsed: org.OrgFile
    archived: bool
    inherited: tuple[str, ...]

    @property
    def day(self) -> datetime | None:
        """Return its date when it is a day: at level 1 or 2, titled by a date alone."""
        heading = self.subtree.heading
        return org.date_title(heading.title) if heading.level <= DAY_LEVEL else None

    @property
    def within(self) -> tuple[int, datetime] | None:
        """Return the place in its path of the first day's title, and that day, or None."""
        return next(
            (
                (place, date)
                for place, title in enumerate(self.outline)
                if (date := org.date_title(title)) is not None
            ),
            None,
        )

    @property
    def meeting(self) -> bool:
        """Say whether it is a meeting: a child of a day, with a meeting's property."""
        within, properties = self.within, self.subtree.properties
        return (
            within is not None
            and within[0] == len(self.outline) - 1
            and (LINKED in properties or NAMED in properties)
        )

    @property
    def labels(self) -> list[str]:
        """Return its labels: the tags above it, its own, its file's, then ARCHIVE if archived.

        As org gives a heading the tags of the headings above it and of ``#+FILETAGS``.
        """
        return [
            *self.inherited,
            *self.subtree.heading.tags,
            *self.parsed.filetags,
            *([org.ARCHIVE] if self.archived else []),
        ]

    @property
    def children(self) -> list[PlacedHeading]:
        """Return its children, below its path and title, archived when it is, given its tags."""
        return [
            PlacedHeading(
                subtree=child,
                outline=(*self.outline, self.subtree.heading.title),
                file=self.file,
                parsed=self.parsed,
                archived=self.archived or org.ARCHIVE in child.heading.tags,
                inherited=(*self.inherited, *self.subtree.heading.tags),
            )
            for child in self.subtree.children(self.parsed.keywords)
        ]


def digest(text: str) -> str:
    """Return the first 16 hex digits of the text's SHA-256."""
    return hashlib.sha256(text.encode()).hexdigest()[:DIGITS]


def revision(converter: str, text: str) -> str:
    """Name what pandoc makes of a document: its input, with pandoc's version and options."""
    return digest(f"{converter}\0{text}")


def participants(value: str) -> tuple[str, ...]:
    """Return the names that a ``:PARTICIPANTS:`` value gives, in order, each once.

    Names are separated by commas outside brackets, ``()`` or ``[]``, a closing one
    without its opening one being text, and stripped; each is kept as written, an
    annotation included, such as ``Kim (not in the header)``. One pass, so that the time
    grows with the value's length alone.
    """
    names: list[str] = []
    depth, begun = 0, 0  # the brackets open, and where the name being read begins
    for place, char in enumerate(value):
        if char in OPENING:
            depth += 1
        elif char in CLOSING:
            depth = max(depth - 1, 0)
        elif char == "," and not depth:
            names.append(value[begun:place])
            begun = place + 1
    names.append(value[begun:])
    return tuple(dict.fromkeys(name for each in names if (name := each.strip())))


def meeting_ids(day: datetime, titles: Iterable[str]) -> list[str]:
    """Return the ids of one day's meetings, given by their titles in the journal's order.

    An id is ``m-``, the day as ``%Y%m%d``, ``-`` and the title's slug, else the first 16
    hex digits of the title's SHA-256. Of one id, the meetings are numbered from the
    second, ``--2``, ``--3``, in the order given, never by a time or a file's name. No
    slug or digest holds ``--``, so that the ids are distinct, and one title's never
    depend on another's.
    """
    taken: Counter[str] = Counter()
    found: list[str] = []
    for title in titles:
        base = f"m-{day:%Y%m%d}-{slug(title) or digest(title)}"
        taken[base] += 1
        found.append(base if taken[base] == 1 else f"{base}{NUMBERED}{taken[base]}")
    return found


class Meeting(Record):
    """A meeting of a day, and the transcript that it links, as ``read`` finds them.

    ``link`` is its ``:MEETING:`` as written; ``file``, the file that it names, from the
    work log's folder, or None; ``transcript``, the id of that file when found, read or
    not, else the id that its path gives, as ``read`` says. ``added`` are the lines of
    the archived headings that join it.
    """

    part: PlacedHeading
    link: str
    file: PurePosixPath | None
    transcript: str | None
    added: list[str] = Field(default_factory=list)

    @classmethod
    def read(
        cls, part: PlacedHeading, ids: Mapping[PurePosixPath, str], known: Collection[str]
    ) -> Meeting:
        """Read a meeting, its link resolved from the folder of its file.

        ``ids`` are the transcripts found, read or not, by their path from the work log's
        folder, as ``transcript_ids`` gives them; ``known``, those ids. A link to a file
        under ``transcripts/`` or ``meetings/`` that no transcript found has reaches the
        id that its path gives, ``transcript_id``'s, when a transcript found has it: a
        file moved under ``archive/`` keeps its id, and org rewrites no link to it.
        """
        link = part.subtree.properties.get(LINKED, "")
        target = org.link_target(link)
        file = None if target is None else part.file.path.parent / target
        transcript: str | None = None
        if file is not None:
            transcript = ids.get(file)
            if transcript is None and file.parts[0] in TRANSCRIPT_FOLDERS:
                moved = transcript_id(file)
                transcript = moved if moved in known else None
        return cls(part=part, link=link, file=file, transcript=transcript)


class Day(Record):
    """What one date of the journal gathers, in reading order, ``todo.org`` first.

    ``title``, ``breadcrumb`` and ``first`` (its file and settings) come from its first
    part, a day's heading or an archived heading that names the day. ``lines`` are what
    pandoc converts, before the settings; ``meetings``, its meetings.
    """

    model_config = ConfigDict(frozen=False)

    title: str
    breadcrumb: tuple[str, ...]
    first: PlacedHeading
    headings: list[PlacedHeading] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)
    meetings: list[Meeting] = Field(default_factory=list)


def journal(
    todo: OrgText | None,
    archive: OrgText | None,
    *,
    archives: bool,
    transcripts: Mapping[PurePosixPath, str],
) -> tuple[list[WorklogDocument], list[str]]:
    """Return the entries, then the days and meetings, of ``todo.org`` and its archive.

    The journal is a top-level heading with a day among its children: its days are days,
    its other children entries, and its own lines an entry only when they hold text
    besides its heading's ``preamble``. A top-level heading that is a day, or that
    ``:ARCHIVE_OLPATH:`` places below one, is the day's, as ``days_and_meetings`` says;
    every other is an entry. An entry's id is the digest of its ``:ID:``; else of its
    title and ``:CREATED:``; else of its title, numbered from the second entry of one
    digest, in reading order, ``todo.org`` first. The archive file takes ``todo.org``'s
    keywords when it declares none. Without ``archives``, the archive file and the
    headings tagged ARCHIVE, or below one, are left out. ``transcripts`` are the ids of
    those found, read or not, by path, which a meeting may link to; each meeting whose
    ``:MEETING:`` links none is named too, as ``days_and_meetings`` says.
    """
    files: list[tuple[OrgText, org.OrgFile]] = []
    first = None
    if todo is not None:
        first = org.read(todo.text)
        files.append((todo, first))
    if archive is not None and archives:
        files.append((archive, org.read(archive.text, first)))
    parts: list[PlacedHeading] = []
    for org_text, parsed in files:
        for subtree in parsed.subtrees:
            archived = org_text.path.name == TODO_ARCHIVE or org.ARCHIVE in subtree.heading.tags
            outline = tuple(filter(None, subtree.properties.get(OUTLINE_PATH, "").split("/")))
            top = PlacedHeading(
                subtree=subtree,
                outline=outline,
                file=org_text,
                parsed=parsed,
                archived=archived,
                inherited=(),
            )
            children = top.children
            if not any(child.day is not None for child in children):
                parts.append(top)
                continue
            own = copy.replace(top, subtree=org.Subtree(heading=subtree.heading, lines=subtree.own))
            text = subtree.own[1 + len(subtree.preamble) :]
            parts.extend([own] if any(line.strip() for line in text) else [])
            parts.extend(children)
    kept = [part for part in parts if archives or not part.archived]
    found: list[WorklogDocument] = []
    taken: Counter[str] = Counter()
    for part in kept:
        if part.day is not None or part.within is not None:
            continue
        heading, properties = part.subtree.heading, part.subtree.properties
        created = properties.get("CREATED")
        title = heading.title
        base = digest(properties.get("ID") or (f"{title}\n{created}" if created else title))
        taken[base] += 1
        found.append(
            WorklogDocument(
                type=ENTRY_TYPE,
                id=f"e-{base}" if taken[base] == 1 else f"e-{base}-{taken[base]}",
                title=title,
                status=heading.keyword or CURRENT,
                labels=tuple(dict.fromkeys(part.labels)),
                breadcrumb=(part.file.path.name, *part.outline),
                people=(),
                links=(),
                text=org.pandoc_input(
                    part.parsed.declarations,
                    org.shifted(part.subtree.lines),
                    part.parsed.keywords,
                    archives=archives,
                ),
                events=part.file.events(part.subtree.lines),
                day=None,
                file=part.file,
            )
        )
    dated, unlinked = days_and_meetings(kept, archives=archives, transcripts=transcripts)
    return [*found, *dated], unlinked


def days_and_meetings(
    parts: Sequence[PlacedHeading], *, archives: bool, transcripts: Mapping[PurePosixPath, str]
) -> tuple[list[WorklogDocument], list[str]]:
    """Return each day of the journal's parts, then its meetings, by date of first part.

    ``parts`` are those kept, in reading order. One date makes one day, ``d-`` and the
    date: its headings, each meeting among their children cut to its heading line, then
    what an archived heading brings that ``:ARCHIVE_OLPATH:`` places below it: a meeting
    archived alone, its heading line; anything else that names none of its meetings
    next, or two alike, itself. A meeting is its subtree, then each archived heading
    whose path after its day begins with the meeting's title as org writes it there, the
    longest such title of the day, when no other meeting of the day has it. Each
    document begins at level 1, what joins it at level 2.

    A meeting links to the id of the transcript whose file its ``:MEETING:`` names, from
    the folder of the file that holds it, or that the file's path gives, as
    ``Meeting.read`` says, read or not, ``transcripts`` being the ids of those found by
    path; its id is as ``meeting_ids`` gives it. A day and each of its meetings are
    dated by that day, whatever a transcript holds. Labels: a meeting's, as
    ``PlacedHeading.labels`` gives them; a day's, those of each of its headings, else, when
    it has none, its first heading's file's ``#+FILETAGS`` and ARCHIVE.

    Also returned, in the order of the meetings, each whose ``:MEETING:`` links no
    transcript: by the file that it names, from the work log's folder, when it is a link
    in brackets or a path after ``file:`` or ``./`` and that file was not found; else by
    the meeting's id. Never the link as written, which may hold a meeting room's
    passcode, as any text reads as a path alone. A meeting without ``:MEETING:`` links
    nothing and is not among them.
    """
    known = set(transcripts.values())
    days: dict[datetime, Day] = {}
    joining: list[tuple[Day, str, PlacedHeading]] = []  # its day, its path after the day, it
    for part in parts:
        within = part.within
        if part.day is not None:
            day = days.setdefault(
                part.day,
                Day(
                    title=part.subtree.heading.title,
                    breadcrumb=(part.file.path.name, *part.outline),
                    first=part,
                ),
            )
            day.headings.append(part)
            children = part.children
            day.meetings.extend(
                Meeting.read(child, transcripts, known)
                for child in children
                if child.meeting and (archives or not child.archived)
            )
            cut = [
                line
                for child in children
                for line in (child.subtree.lines[:1] if child.meeting else child.subtree.lines)
            ]
            day.lines.extend(org.shifted([*part.subtree.own, *cut]))
        elif within is not None:
            place, date = within
            day = days.setdefault(
                date,
                Day(
                    title=part.outline[place],
                    breadcrumb=(part.file.path.name, *part.outline[:place]),
                    first=part,
                ),
            )
            if part.meeting:
                day.meetings.append(Meeting.read(part, transcripts, known))
                day.lines.extend(org.shifted(part.subtree.lines[:1], JOINED_LEVEL))
            else:
                joining.append((day, "/".join(part.outline[place + 1 :]), part))
    for day, rest, part in joining:
        # Org joins the titles of a path by a / that it does not escape, so that a title
        # such as 1/1 with Robin spans two parts: the longest title that begins the rest.
        named = [
            (len(title), meeting.added)
            for meeting in day.meetings
            if (title := meeting.part.subtree.heading.outline_title)
            and (rest == title or rest.startswith(f"{title}/"))
        ]
        # The path names two meetings of one title alike: neither is told, the day keeps it.
        longest = max((length for length, _ in named), default=0)
        chosen = [added for length, added in named if length == longest]
        target = chosen[0] if len(chosen) == 1 else day.lines
        target.extend(org.shifted(part.subtree.lines, JOINED_LEVEL))
    found: list[WorklogDocument] = []
    unlinked: list[str] = []
    for date, day in days.items():
        ids = meeting_ids(date, [each.part.subtree.heading.title for each in day.meetings])
        unlinked.extend(
            str(each.file) if org.link_target(each.link, bare=False) else identifier
            for each, identifier in zip(day.meetings, ids, strict=True)
            if each.link and each.transcript is None
        )
        headings = day.headings
        # Each heading's labels; a day of archived pieces alone is archived.
        labels = (
            [label for each in headings for label in each.labels]
            if headings
            else [*day.first.parsed.filetags, org.ARCHIVE]
        )
        found.append(
            WorklogDocument(
                type=DAY_TYPE,
                id=f"d-{date:%Y%m%d}",
                title=day.title,
                status=(headings[0].subtree.heading.keyword if headings else None) or CURRENT,
                labels=tuple(dict.fromkeys(labels)),
                breadcrumb=day.breadcrumb,
                people=(),
                links=(),
                text=org.pandoc_input(
                    day.first.parsed.declarations,
                    day.lines,
                    day.first.parsed.keywords,
                    archives=archives,
                ),
                events=(),
                day=date,
                file=day.first.file,
            )
        )
        for each, identifier in zip(day.meetings, ids, strict=True):
            meeting, transcript = each.part, each.transcript
            heading = meeting.subtree.heading
            found.append(
                WorklogDocument(
                    type=MEETING_TYPE,
                    id=identifier,
                    title=heading.title,
                    status=heading.keyword or CURRENT,
                    labels=tuple(dict.fromkeys(meeting.labels)),
                    breadcrumb=(meeting.file.path.name, *meeting.outline),
                    people=participants(meeting.subtree.properties.get(NAMED, "")),
                    links=() if transcript is None else ((TRANSCRIBED, transcript),),
                    text=org.pandoc_input(
                        meeting.parsed.declarations,
                        [*org.shifted(meeting.subtree.lines), *each.added],
                        meeting.parsed.keywords,
                        archives=archives,
                    ),
                    events=(),
                    day=date,
                    file=meeting.file,
                )
            )
    return found, unlinked


def speakers(lines: Sequence[str]) -> tuple[str, ...]:
    """Return the speakers of a transcript's turns, in order of first speech, each once.

    Turns are read inside the quote blocks when there is any, the notes outside them being
    the user's, else on every line. A turn's line holds an optional ``[time]``, passed
    over, and a blank, then a name of at most 64 characters that begins with a letter and
    holds no colon or bracket, then ``: ``, blanks before the colon not being the name's.
    The name is none of org's planning and clock keywords, such as ``DEADLINE``, and is
    kept as written.
    """
    inside = org.quoted(lines)
    matches = [TURN.match(line) for line in (lines if inside is None else inside)]
    return tuple(dict.fromkeys(each[1] for each in matches if each and each[1] not in NOT_SPEAKERS))


def named_day(path: PurePosixPath) -> tuple[str, datetime] | None:
    """Return the name that begins with a day, and that day at midnight UTC, or None.

    The name of the folder that holds the transcript at ``path``, else its own less
    ``.org``.
    """
    folders = path.parts[1:-1]
    for name in (folders[-1] if folders else "", path.name.removesuffix(ORG)):
        match = DAY.match(name)
        if match is not None:
            with contextlib.suppress(ValueError):  # 2026-13-40 begins no day
                return name, datetime.fromisoformat(match[0]).replace(tzinfo=UTC)
    return None


def transcript_id(path: PurePosixPath) -> str:
    """Return the id that a transcript's path, from the work log's folder, gives it.

    ``t-``, the day that ``named_day`` reads, ``-``, ``meeting-`` for a file under
    ``meetings/``, then its name less ``.org`` when the id holds to its rule so, else
    that name's slug, else the first 16 hex digits of its name's SHA-256. Without a day,
    ``t-`` and the digest of its name, ``meeting-`` before it under ``meetings/``. Of its
    folders, the first alone, by ``meeting-``, and the day that begins the name of the
    one that holds it are in it, so that a move under ``archive/`` keeps it.
    """
    own = path.name
    stem = own.removesuffix(ORG)
    named = named_day(path)
    prefix = MEETING_FILE if path.parts[0] == MEETINGS_FOLDER else ""
    dated = [
        f"t-{named[1]:%Y%m%d}-{prefix}{part}"
        for part in (stem, slug(stem), digest(own))
        if named and part
    ]
    rule = WORKLOG_TYPES[TRANSCRIPT_TYPE].id_rule
    return next((each for each in dated if rule.fullmatch(each)), f"t-{digest(prefix + own)}")


def in_archive(path: PurePosixPath) -> bool:
    """Say whether a transcript, by its path from the work log's folder, is archived.

    So it is under ``archive/`` in its first folder, ``transcripts/`` or ``meetings/``.
    """
    return path.parts[1:-1][:1] == (ARCHIVED,)


def transcript_ids(
    paths: Iterable[PurePosixPath], *, archives: bool
) -> tuple[dict[PurePosixPath, str], list[str]]:
    """Return the id of each transcript among ``paths``, read or not, and the warnings.

    A transcript is an ``.org`` file under ``transcripts/`` or ``meetings/``, its id as
    ``transcript_id`` gives it from its path alone, so that a file not read has one too.
    They come in order of their first folder, the folder that holds them, their name,
    then their path: of two files of one id, the first keeps it and the other takes the
    digest of its whole path, written from the work log's root (``/transcripts/...``),
    and no name holds ``/``, so no other file's digest is the same; a warning names
    both. So a file moved under ``archive/`` with the folder that holds it never hands
    its id to the other file, unless both are in folders of one name. That order decides
    nothing else. Without ``archives``, those under ``transcripts/archive/`` and
    ``meetings/archive/`` are left out.
    """
    ids: dict[PurePosixPath, str] = {}
    warnings: list[str] = []
    keepers: dict[str, PurePosixPath] = {}
    for path in sorted(
        (each for each in paths if each.suffix == ORG and each.parts[0] in TRANSCRIPT_FOLDERS),
        key=lambda each: (each.parts[0], each.parts[1:-1][-1:], each.name, each.as_posix()),
    ):
        if in_archive(path) and not archives:
            continue
        identifier = transcript_id(path)
        if identifier in keepers:
            warnings.append(f"{path}: same id as {keepers[identifier]}; named by its whole path")
            identifier = f"t-{digest(f'/{path.as_posix()}')}"
        keepers[identifier] = path
        ids[path] = identifier
    return ids, warnings


def transcripts(
    org_texts: Iterable[OrgText], ids: Mapping[PurePosixPath, str], *, archives: bool
) -> list[WorklogDocument]:
    """Return the transcripts read, in the order of ``ids``, each of the id given there.

    ``ids`` are ``transcript_ids``'s; an org text of no id there, such as one archived and
    left out, is passed over. Its people are its ``speakers``; a dated one is its day, as
    ``named_day`` reads it, whatever its turns and timestamps hold, and an undated one is
    dated by its events. Without ``archives``, its text is converted without the
    subtrees tagged ARCHIVE.
    """
    read = {each.path: each for each in org_texts}
    found: list[WorklogDocument] = []
    for path, identifier in ids.items():
        org_text = read.get(path)
        if org_text is None:
            continue
        archived = in_archive(path)
        stem = path.name.removesuffix(ORG)
        named = named_day(path)
        parsed = org.read(org_text.text)
        fallback = f"Transcript, {named[0]}, {stem}" if named else f"Transcript, {stem}"
        first = next((each.title for each in parsed.headings if each.title), fallback)
        found.append(
            WorklogDocument(
                type=TRANSCRIPT_TYPE,
                id=identifier,
                title=parsed.title or first,
                status=CURRENT,
                labels=tuple(
                    dict.fromkeys([*parsed.filetags, *([org.ARCHIVE] if archived else [])])
                ),
                breadcrumb=path.parts[:-1],
                people=speakers(parsed.lines),
                links=(),
                text=org.pandoc_input(
                    parsed.declarations, parsed.lines, parsed.keywords, archives=archives
                ),
                events=org_text.events(parsed.lines),
                day=named[1] if named else None,
                file=org_text,
            )
        )
    return found


def linked_back(
    transcripts: Iterable[WorklogDocument], documents: Iterable[WorklogDocument]
) -> list[WorklogDocument]:
    """Return the transcripts, each linked back to the documents that link to it.

    A transcript gains ``summary`` and a document's id for each of ``documents`` whose
    ``transcript`` link names it, in their order, after its own links: the journal's
    meetings, so that each file names the other.
    """
    summaries: dict[str, list[tuple[str, str]]] = {}
    for document in documents:
        for relation, ref in document.links:
            if relation == TRANSCRIBED:
                summaries.setdefault(ref, []).append((SUMMARY, document.id))
    return [
        copy.replace(each, links=(*each.links, *summaries.get(each.id, ()))) for each in transcripts
    ]


def writable(
    documents: Iterable[WorklogDocument], unread: Collection[str]
) -> list[WorklogDocument]:
    """Return the documents whose files a run may write, when ``unread`` were not read.

    ``unread`` names each file or folder of the work log not read, by its path from the
    work log's folder. Every document draws on ``todo.org`` and its archive: without
    either, none is written. Any other file builds its own document alone, which is not
    among ``documents`` and keeps its last copy; it holds back no other. So no file is
    written from a part of what it draws on.
    """
    return [] if SHARED & set(unread) else list(documents)


def held_back(where: str, ids: Mapping[PurePosixPath, str]) -> str:
    """Return what keeps its last copy when ``where`` was not read, as ``writable`` says.

    ``where`` is a file or folder of the work log, by its path from the work log's
    folder; ``ids``, the transcripts found, as ``transcript_ids`` gives them. Every
    document for ``todo.org``, its archive, or the work log's folder itself (``.``); the
    transcript's id for a path that ``ids`` holds, read or not; else the transcripts not
    read under it, as a problem's path and reason do not tell a folder from a file: a
    folder's, the files past the bound for its problem, none for an HTML file. So a
    folder linking out whose name ends in ``.org`` reads as a transcript of its own id.
    """
    return EVERY_DOCUMENT if where in SHARED else ids.get(PurePosixPath(where), UNDER_IT)
