"""The work log's documents: what each is, and its id, title, dates and revision.

An entry is a top-level heading of ``todo.org`` or ``todo.org_archive`` with its subtree;
a transcript is an org file under ``transcripts/``. The rules are those of plan 017's
"Documents and their identity" and "Front matter and conversion"; org's syntax is read
by ``org``.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.content import WORKLOG_ID
from atlassian_offline_mcp.sources.worklog.domain import org

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import PurePosixPath

TODO = "todo.org"
TODO_ARCHIVE = "todo.org_archive"
TRANSCRIPTS = "transcripts"
# The folder of transcripts/ that holds archived transcripts.
ARCHIVED = "archive"
ORG = ".org"
ENTRY = "entry"
TRANSCRIPT = "transcript"
CURRENT = "current"
DIGITS = 16
# The date that begins a folder's or a file's name.
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


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
    """One document of the work log: what the mirror says of it, and what pandoc converts."""

    type: str  # entry or transcript
    id: str
    title: str
    status: str
    labels: tuple[str, ...]
    breadcrumb: tuple[str, ...]
    text: str  # pandoc's input
    events: tuple[datetime, ...]
    day: datetime | None  # a transcript's day, at midnight UTC
    source: Source

    def dates(self, created: datetime | None) -> tuple[datetime, datetime]:
        """Return when it was created and last updated.

        A transcript's day, else its earliest and latest events; without any, its file's
        modification time, created being ``created``, the existing file's, when given.
        """
        if self.day is not None:
            return self.day, self.day
        if self.events:
            return min(self.events), max(self.events)
        return created or self.source.fetched_at, self.source.fetched_at


def digest(text: str) -> str:
    """Return the first 16 hex digits of the text's SHA-256."""
    return hashlib.sha256(text.encode()).hexdigest()[:DIGITS]


def revision(converter: str, text: str) -> str:
    """Name what pandoc makes of a document: its input, with pandoc's version and options."""
    return digest(f"{converter}\0{text}")


def entries(todo: Source | None, archive: Source | None, *, archives: bool) -> list[Document]:
    """Return the entries of ``todo.org``, then of ``todo.org_archive``, in reading order.

    An entry's id is the digest of its ``:ID:``; else of its title and ``:CREATED:``; else
    of its title, numbered from the second entry of one digest. The archive file takes
    ``todo.org``'s keywords when it declares none. Without ``archives``, the archive
    file's entries and those tagged ARCHIVE are left out.
    """
    files: list[tuple[Source, org.OrgFile]] = []
    first = None
    if todo is not None:
        first = org.read(todo.text)
        files.append((todo, first))
    if archive is not None and archives:
        files.append((archive, org.read(archive.text, first)))
    found: list[Document] = []
    taken: Counter[str] = Counter()
    for source, parsed in files:
        for subtree in parsed.subtrees:
            archived = source.path.name == TODO_ARCHIVE or org.ARCHIVE in subtree.heading.tags
            if archived and not archives:
                continue
            title, properties = subtree.heading.title, subtree.properties
            created = properties.get("CREATED")
            base = digest(properties.get("ID") or (f"{title}\n{created}" if created else title))
            taken[base] += 1
            labels = [
                *subtree.heading.tags,
                *parsed.filetags,
                *([org.ARCHIVE] if archived else []),
            ]
            found.append(
                Document(
                    type=ENTRY,
                    id=f"e-{base}" if taken[base] == 1 else f"e-{base}-{taken[base]}",
                    title=title,
                    status=subtree.heading.keyword or CURRENT,
                    labels=tuple(dict.fromkeys(labels)),
                    breadcrumb=(source.path.name,),
                    text=org.pandoc_input(
                        parsed.declarations, subtree.lines, parsed.keywords, archives=archives
                    ),
                    events=source.events(subtree.lines),
                    day=None,
                    source=source,
                )
            )
    return found


def transcripts(sources: Iterable[Source], *, archives: bool) -> tuple[list[Document], list[str]]:
    """Return the transcripts in path order, and a warning for each id found twice.

    A transcript's id is ``t-``, the day that begins its folder's name (or its own) and
    its name less ``.org``; without a day, or when that is off the id's rule, the digest
    of its path below ``transcripts/<first folder>/``. Of two files of one id, the first
    in path order keeps it and the other takes the digest of its whole path, written
    from the work log's root (``/transcripts/...``): no path below a first folder begins
    with ``/``, so no other file's digest is the same. Without ``archives``, those under
    ``transcripts/archive/`` are left out.
    """
    found: list[Document] = []
    warnings: list[str] = []
    keepers: dict[str, PurePosixPath] = {}
    for source in sorted(sources, key=lambda each: each.path.as_posix()):
        folders = source.path.parts[1:-1]
        archived = folders[:1] == (ARCHIVED,)
        if archived and not archives:
            continue
        stem = source.path.name.removesuffix(ORG)
        folder = folders[-1] if folders else ""
        named: list[tuple[str, datetime]] = []  # the name that begins with a day, and the day
        for name in (folder, stem):
            match = DAY.match(name)
            if match is None:
                continue
            with contextlib.suppress(ValueError):  # 2026-13-40 begins no day
                named.append((name, datetime.fromisoformat(match[0]).replace(tzinfo=UTC)))
        dated = f"t-{named[0][1]:%Y%m%d}-{stem}" if named else ""
        below = "/".join(source.path.parts[2:] or source.path.parts[-1:])
        identifier = dated if WORKLOG_ID.fullmatch(dated) else f"t-{digest(below)}"
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
                text=org.pandoc_input(
                    parsed.declarations, parsed.lines, parsed.keywords, archives=archives
                ),
                events=source.events(parsed.lines),
                day=named[0][1] if named else None,
                source=source,
            )
        )
    return found, warnings
