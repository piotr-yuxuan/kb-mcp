"""The work log's documents: what each is, and its id, title, dates and revision.

The journal of ``todo.org`` and ``todo.org_archive`` makes a document of each day and of
each meeting, and the other top-level headings are entries; a transcript is an org file
under ``transcripts/`` or ``meetings/``. The rules are those of plan 017's "Documents and
their identity" and "Front matter and conversion", and plan 042's "Days and meetings:
the rule", "Ids", "Participants" and "Links"; org's syntax is read by ``org``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.content import WORKLOG_ID
from atlassian_offline_mcp.kernel.slug import slug
from atlassian_offline_mcp.sources.worklog.domain import org

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import PurePosixPath

TODO = "todo.org"
TODO_ARCHIVE = "todo.org_archive"
# The folders of transcripts: those saved, and the meeting files that a meeting's
# :MEETING: links, as the user's meeting notes save them.
MEETINGS = "meetings"
TRANSCRIPTS = ("transcripts", MEETINGS)
# What a file under meetings/ takes before its name in its id, so that one day's 1.org
# in both folders never shares an id.
MEETING_FILE = "meeting-"
# The folder of each that holds archived transcripts.
ARCHIVED = "archive"
ORG = ".org"
ENTRY = "entry"
DAY_TYPE = "day"
MEETING_TYPE = "meeting"
TRANSCRIPT = "transcript"
# The relations of a meeting to its transcript, and of a transcript to each meeting
# that links to it, as the mirror's front matter names them.
TRANSCRIBED = "transcript"
SUMMARY = "summary"
CURRENT = "current"
DIGITS = 16
# The date that begins a folder's or a file's name.
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# A day is a heading at level 1, or 2 below the journal; what joins it, a level below.
DAY_LEVEL = 2
# The properties of a meeting's drawer: the file of its transcript, and its people. A
# child of a day with either is a meeting.
LINKED = "MEETING"
NAMED = "PARTICIPANTS"
# Where org's archiving writes the titles above a subtree, joined by /.
OUTLINE_PATH = "ARCHIVE_OLPATH"
# A comma between names: outside brackets, so that Kim (payments, ops) stays one name.
SEPARATOR = re.compile(r",(?![^(\[]*[)\]])")
# A turn of a transcript: an optional [time] and a blank, then its speaker's name, of at
# most 64 characters, beginning with a letter and holding no colon or bracket, then ": ".
TURN = re.compile(r"[ \t]*(?:\[([^\[\]]*)\][ \t]+)?([^\W\d_][^:\[\]]{0,63}?)[ \t]*: ")
# Org's planning and clock lines, which read as turns.
NOT_SPEAKERS = frozenset({"SCHEDULED", "DEADLINE", "CLOSED", "CLOCK"})
# A turn's time that dates its transcript: two-digit hours and minutes, seconds or not.
CLOCK_TIME = re.compile(r"([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?")


@dataclass(frozen=True)
class Source:
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


@dataclass(frozen=True)
class Document:
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
    start: datetime | None  # when a day, a meeting or a dated transcript began, in UTC
    source: Source

    def dates(self, created: datetime | None) -> tuple[datetime, datetime]:
        """Return when it was created and last updated.

        Its start, else its earliest and latest events; without any, its file's
        modification time, created being ``created``, the existing file's, when given.
        """
        if self.start is not None:
            return self.start, self.start
        if self.events:
            return min(self.events), max(self.events)
        return created or self.source.fetched_at, self.source.fetched_at


@dataclass(frozen=True)
class Part:
    """A heading of ``todo.org`` or its archive, and the titles above it: org's outline path.

    Below the journal, the path is the journal's title, then for a meeting its day's; at
    the top of a file, it is what org wrote in ``:ARCHIVE_OLPATH:`` when it archived the
    heading, else empty. It is ``archived`` when its file is the archive or it, or a
    heading above it, is tagged ARCHIVE.
    """

    subtree: org.Subtree
    path: tuple[str, ...]
    source: Source
    parsed: org.OrgFile
    archived: bool

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
                for place, title in enumerate(self.path)
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
            and within[0] == len(self.path) - 1
            and (LINKED in properties or NAMED in properties)
        )

    @property
    def children(self) -> list[Part]:
        """Return its children, below its path and its title, archived when it is."""
        return [
            Part(
                child,
                (*self.path, self.subtree.heading.title),
                self.source,
                self.parsed,
                self.archived or org.ARCHIVE in child.heading.tags,
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

    Names are separated by commas outside brackets, and stripped; each is kept as written,
    an annotation included, such as ``Kim (not in the header)``.
    """
    return tuple(dict.fromkeys(name for part in SEPARATOR.split(value) if (name := part.strip())))


def meeting_ids(day: datetime, meetings: Sequence[tuple[str, datetime]]) -> list[str]:
    """Return the ids of one day's meetings, each given by its title and start, in order.

    An id is ``m-``, the day as ``%Y%m%d``, ``-`` and the title's slug, else the first 16
    hex digits of the title's SHA-256. Of one id, the meetings are numbered from the
    second, ``-2``, ``-3``, by start, then in the order given; a number that another
    meeting's id already holds is passed over, so that no two ids are the same.
    """
    bases = [f"m-{day:%Y%m%d}-{slug(title) or digest(title)}" for title, _ in meetings]
    found: dict[int, str] = {}
    for index in sorted(range(len(meetings)), key=lambda index: (meetings[index][1], index)):
        number, identifier = 1, bases[index]
        while identifier in found.values():
            number += 1
            identifier = f"{bases[index]}-{number}"
        found[index] = identifier
    return [found[index] for index in range(len(meetings))]


@dataclass(frozen=True)
class Meeting:
    """A meeting of a day, and the transcript that it links, as ``read`` finds them.

    ``link`` is its ``:MEETING:`` as written; ``file``, the file that it names, from the
    work log's folder, or None; ``transcript``, that file's when read; ``start``, when
    that transcript starts, else the day. ``added`` are the lines of the archived
    headings that join it.
    """

    part: Part
    link: str
    file: PurePosixPath | None
    transcript: Document | None
    start: datetime
    added: list[str] = dataclasses.field(default_factory=list)

    @classmethod
    def read(
        cls, part: Part, day: datetime, transcripts: Mapping[PurePosixPath, Document]
    ) -> Meeting:
        """Read a meeting of ``day``, its link resolved from the folder of its file.

        ``transcripts`` are those read, by their path from the work log's folder.
        """
        link = part.subtree.properties.get(LINKED, "")
        target = org.link_target(link)
        file = None if target is None else part.source.path.parent / target
        transcript = None if file is None else transcripts.get(file)
        start = None if transcript is None else transcript.start
        return cls(part, link, file, transcript, start or day)


@dataclass
class Day:
    """What one date of the journal gathers, in reading order, ``todo.org`` first.

    ``title``, ``breadcrumb`` and ``first`` (its file and settings) come from its first
    part, a day's heading or an archived heading that names the day. ``lines`` are what
    pandoc converts, before the settings; ``meetings``, its meetings.
    """

    title: str
    breadcrumb: tuple[str, ...]
    first: Part
    headings: list[Part] = dataclasses.field(default_factory=list)
    lines: list[str] = dataclasses.field(default_factory=list)
    meetings: list[Meeting] = dataclasses.field(default_factory=list)


def journal(
    todo: Source | None,
    archive: Source | None,
    *,
    archives: bool,
    transcripts: Iterable[Document],
) -> tuple[list[Document], list[str]]:
    """Return the entries, then the days and meetings, of ``todo.org`` and its archive.

    The journal is a top-level heading with a day among its children: its days are days,
    its other children entries, and its own lines an entry only when they hold text
    besides its heading's ``preamble``. A top-level heading that is a day, or that
    ``:ARCHIVE_OLPATH:`` places below one, is the day's, as ``days_and_meetings`` says;
    every other is an entry. An entry's id is the digest of its ``:ID:``; else of its
    title and ``:CREATED:``; else of its title, numbered from the second entry of one
    digest, in reading order, ``todo.org`` first. The archive file takes ``todo.org``'s
    keywords when it declares none. Without ``archives``, the archive file and the
    headings tagged ARCHIVE, or below one, are left out. ``transcripts`` are those read,
    which a meeting may link to; each meeting whose ``:MEETING:`` links none is named
    too, as ``days_and_meetings`` says.
    """
    files: list[tuple[Source, org.OrgFile]] = []
    first = None
    if todo is not None:
        first = org.read(todo.text)
        files.append((todo, first))
    if archive is not None and archives:
        files.append((archive, org.read(archive.text, first)))
    parts: list[Part] = []
    for source, parsed in files:
        for subtree in parsed.subtrees:
            archived = source.path.name == TODO_ARCHIVE or org.ARCHIVE in subtree.heading.tags
            path = tuple(filter(None, subtree.properties.get(OUTLINE_PATH, "").split("/")))
            top = Part(subtree, path, source, parsed, archived)
            children = top.children
            if not any(child.day is not None for child in children):
                parts.append(top)
                continue
            own = dataclasses.replace(top, subtree=org.Subtree(subtree.heading, subtree.own))
            text = subtree.own[1 + len(subtree.preamble) :]
            parts.extend([own] if any(line.strip() for line in text) else [])
            parts.extend(children)
    kept = [part for part in parts if archives or not part.archived]
    found: list[Document] = []
    taken: Counter[str] = Counter()
    for part in kept:
        if part.day is not None or part.within is not None:
            continue
        heading, properties = part.subtree.heading, part.subtree.properties
        created = properties.get("CREATED")
        title = heading.title
        base = digest(properties.get("ID") or (f"{title}\n{created}" if created else title))
        taken[base] += 1
        labels = [*heading.tags, *part.parsed.filetags, *([org.ARCHIVE] if part.archived else [])]
        found.append(
            Document(
                type=ENTRY,
                id=f"e-{base}" if taken[base] == 1 else f"e-{base}-{taken[base]}",
                title=title,
                status=heading.keyword or CURRENT,
                labels=tuple(dict.fromkeys(labels)),
                breadcrumb=(part.source.path.name, *part.path),
                people=(),
                links=(),
                text=org.pandoc_input(
                    part.parsed.declarations,
                    org.shifted(part.subtree.lines),
                    part.parsed.keywords,
                    archives=archives,
                ),
                events=part.source.events(part.subtree.lines),
                start=None,
                source=part.source,
            )
        )
    dated, unlinked = days_and_meetings(kept, archives=archives, transcripts=transcripts)
    return [*found, *dated], unlinked


def days_and_meetings(
    parts: Sequence[Part], *, archives: bool, transcripts: Iterable[Document]
) -> tuple[list[Document], list[str]]:
    """Return each day of the journal's parts, then its meetings, by date of first part.

    ``parts`` are those kept, in reading order. One date makes one day, ``d-`` and the
    date: its headings, each meeting among their children cut to its heading line, then
    what an archived heading brings that ``:ARCHIVE_OLPATH:`` places below it: a meeting
    archived alone, its heading line; anything else that names none of its meetings
    next, itself. A meeting is its subtree, then each archived heading whose path after
    its day begins with the meeting's title as org writes it there, the longest such
    title of the day. Each document begins at level 1, what joins it at level 2.

    A meeting links to the transcript whose file its ``:MEETING:`` names, from the folder
    of the file that holds it, and starts when that transcript starts, else at its day;
    its id is as ``meeting_ids`` gives it. Labels: tags, ``#+FILETAGS`` and ARCHIVE when
    it is archived; a day is archived when one of its headings is, or it has none.

    Also returned, in the order of the meetings, each whose ``:MEETING:`` links no
    transcript: by the file that it names, from the work log's folder, when that file
    was not read; by the meeting's id for a link through ``..``, absolute or of another
    type. Never the link as written, which may hold a meeting room's passcode. A meeting
    without ``:MEETING:`` links nothing and is not among them.
    """
    linked = {each.source.path: each for each in transcripts}
    days: dict[datetime, Day] = {}
    joining: list[tuple[Day, str, Part]] = []  # its day, its path after the day, it
    for part in parts:
        within = part.within
        if part.day is not None:
            day = days.setdefault(
                part.day,
                Day(part.subtree.heading.title, (part.source.path.name, *part.path), part),
            )
            day.headings.append(part)
            children = part.children
            day.meetings.extend(
                Meeting.read(child, part.day, linked)
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
                Day(part.path[place], (part.source.path.name, *part.path[:place]), part),
            )
            if part.meeting:
                day.meetings.append(Meeting.read(part, date, linked))
                day.lines.extend(org.shifted(part.subtree.lines[:1], DAY_LEVEL))
            else:
                joining.append((day, "/".join(part.path[place + 1 :]), part))
    for day, rest, part in joining:
        # Org joins the titles of a path by a / that it does not escape, so that a title
        # such as 1/1 with Robin spans two parts: the longest title that begins the rest.
        named = [
            (len(title), meeting.added)
            for meeting in day.meetings
            if (title := meeting.part.subtree.heading.outline_title)
            and (rest == title or rest.startswith(f"{title}/"))
        ]
        target = max(named, key=lambda each: each[0], default=(0, day.lines))[1]
        target.extend(org.shifted(part.subtree.lines, DAY_LEVEL))
    found: list[Document] = []
    unlinked: list[str] = []
    for date, day in days.items():
        ids = meeting_ids(
            date, [(each.part.subtree.heading.title, each.start) for each in day.meetings]
        )
        unlinked.extend(
            str(each.file) if each.file else identifier
            for each, identifier in zip(day.meetings, ids, strict=True)
            if each.link and each.transcript is None
        )
        headings = day.headings
        archived = not headings or any(each.archived for each in headings)
        tags = [tag for each in headings for tag in each.subtree.heading.tags]
        found.append(
            Document(
                type=DAY_TYPE,
                id=f"d-{date:%Y%m%d}",
                title=day.title,
                status=(headings[0].subtree.heading.keyword if headings else None) or CURRENT,
                labels=tuple(
                    dict.fromkeys(
                        [*tags, *day.first.parsed.filetags, *([org.ARCHIVE] if archived else [])]
                    )
                ),
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
                start=date,
                source=day.first.source,
            )
        )
        for each, identifier in zip(day.meetings, ids, strict=True):
            meeting, transcript = each.part, each.transcript
            heading = meeting.subtree.heading
            labels = [
                *heading.tags,
                *meeting.parsed.filetags,
                *([org.ARCHIVE] if meeting.archived else []),
            ]
            found.append(
                Document(
                    type=MEETING_TYPE,
                    id=identifier,
                    title=heading.title,
                    status=heading.keyword or CURRENT,
                    labels=tuple(dict.fromkeys(labels)),
                    breadcrumb=(meeting.source.path.name, *meeting.path),
                    people=participants(meeting.subtree.properties.get(NAMED, "")),
                    links=() if transcript is None else ((TRANSCRIBED, transcript.id),),
                    text=org.pandoc_input(
                        meeting.parsed.declarations,
                        [*org.shifted(meeting.subtree.lines), *each.added],
                        meeting.parsed.keywords,
                        archives=archives,
                    ),
                    events=(),
                    start=each.start,
                    source=meeting.source,
                )
            )
    return found, unlinked


def turns(lines: Sequence[str]) -> list[tuple[str | None, str]]:
    """Return each turn of a transcript, in order: its time as written, or None, and speaker.

    Turns are read inside the quote blocks when there is any, the notes outside them being
    the user's, else on every line. A turn's line holds an optional ``[time]`` and a blank,
    then a name of at most 64 characters that begins with a letter and holds no colon or
    bracket, then ``: ``, blanks before the colon not being the name's. The name is none
    of org's planning and clock keywords, such as ``DEADLINE``.
    """
    inside = org.quoted(lines)
    matches = [TURN.match(line) for line in (lines if inside is None else inside)]
    return [(each[1], each[2]) for each in matches if each and each[2] not in NOT_SPEAKERS]


def speakers(lines: Sequence[str]) -> tuple[str, ...]:
    """Return the speakers of a transcript's turns, as ``turns`` reads them, each once.

    In order of first speech, each name as written.
    """
    return tuple(dict.fromkeys(name for _, name in turns(lines)))


def start(day: datetime, lines: Sequence[str]) -> datetime:
    """Return when a transcript of ``day``, at midnight UTC, began, read as written in UTC.

    Its first turn's time, when it reads strictly as ``HH:MM`` or ``HH:MM:SS`` and names a
    time of day; else its earliest timestamp on its day; else its day.
    """
    said = turns(lines)
    clock = CLOCK_TIME.fullmatch(said[0][0] or "") if said else None
    if clock is not None:
        with contextlib.suppress(ValueError):  # 24:00 is no time of day
            return day.replace(hour=int(clock[1]), minute=int(clock[2]), second=int(clock[3] or 0))
    return min((each for each in org.timestamps(lines) if each.date() == day.date()), default=day)


def transcripts(sources: Iterable[Source], *, archives: bool) -> tuple[list[Document], list[str]]:
    """Return the transcripts in path order, and a warning for each id found twice.

    A transcript is a file under ``transcripts/`` or ``meetings/``. Its id is ``t-``, the
    day that begins its folder's name (or its own), ``-``, ``meeting-`` for a file under
    ``meetings/``, then its name less ``.org`` when the id holds to its rule so, else
    that name's slug, else the first 16 hex digits of its name's SHA-256. Without a day,
    it is ``t-`` and the digest of its name, ``meeting-`` before it under ``meetings/``.
    Of two files of one id, the first in path order keeps it and the other takes the
    digest of its whole path, written from the work log's root (``/transcripts/...``):
    no name holds ``/``, so no other file's digest is the same.

    Its people are its ``speakers``; a dated one begins as ``start`` says. Without
    ``archives``, those under ``transcripts/archive/`` and ``meetings/archive/`` are left
    out.
    """
    found: list[Document] = []
    warnings: list[str] = []
    keepers: dict[str, PurePosixPath] = {}
    for source in sorted(sources, key=lambda each: each.path.as_posix()):
        folders = source.path.parts[1:-1]
        archived = folders[:1] == (ARCHIVED,)
        if archived and not archives:
            continue
        own = source.path.name
        stem = own.removesuffix(ORG)
        folder = folders[-1] if folders else ""
        named: list[tuple[str, datetime]] = []  # the name that begins with a day, and the day
        for name in (folder, stem):
            match = DAY.match(name)
            if match is None:
                continue
            with contextlib.suppress(ValueError):  # 2026-13-40 begins no day
                named.append((name, datetime.fromisoformat(match[0]).replace(tzinfo=UTC)))
        prefix = MEETING_FILE if source.path.parts[0] == MEETINGS else ""
        dated = [
            f"t-{named[0][1]:%Y%m%d}-{prefix}{part}"
            for part in (stem, slug(stem), digest(own))
            if named and part
        ]
        identifier = next(
            (each for each in dated if WORKLOG_ID.fullmatch(each)), f"t-{digest(prefix + own)}"
        )
        if identifier in keepers:
            keeper = keepers[identifier]
            warnings.append(f"{source.path}: same id as {keeper}; named by its whole path")
            identifier = f"t-{digest(f'/{source.path.as_posix()}')}"
        keepers[identifier] = source.path
        parsed = org.read(source.text)
        fallback = f"Transcript, {named[0][0]}, {stem}" if named else f"Transcript, {stem}"
        first = next((each.title for each in parsed.headings if each.title), fallback)
        found.append(
            Document(
                type=TRANSCRIPT,
                id=identifier,
                title=parsed.title or first,
                status=CURRENT,
                labels=tuple(
                    dict.fromkeys([*parsed.filetags, *([org.ARCHIVE] if archived else [])])
                ),
                breadcrumb=source.path.parts[:-1],
                people=speakers(parsed.lines),
                links=(),
                text=org.pandoc_input(
                    parsed.declarations, parsed.lines, parsed.keywords, archives=archives
                ),
                events=source.events(parsed.lines),
                start=start(named[0][1], parsed.lines) if named else None,
                source=source,
            )
        )
    return found, warnings


def linked_back(transcripts: Iterable[Document], documents: Iterable[Document]) -> list[Document]:
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
        dataclasses.replace(each, links=(*each.links, *summaries.get(each.id, ())))
        for each in transcripts
    ]
