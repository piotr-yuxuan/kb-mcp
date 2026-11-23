"""What the work log's copy store holds: each document as its fetch last read it whole.

A fetch reads the work log's folder in place and keeps, for each document, the properties
that the mirror's front matter says of it and the text that pandoc converts, whose digest
alone is its revision; ``fetched`` says what the store holds once a read is done. Only the
copy store's adapter knows how the store is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import model_validator

from kb_mcp.kernel.names import IDENTIFIER, RefusedError, require
from kb_mcp.kernel.records import Record
from kb_mcp.mirror.domain.mirror import RELATIONS
from kb_mcp.sources.worklog import WORKLOG_TYPES
from kb_mcp.sources.worklog.fetch.domain.worklog import digest

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kb_mcp.sources.worklog.fetch.domain.worklog import WorklogDocument


class WorklogCopy(Record):
    """One document of the work log as a fetch last read it whole.

    Its title, status, labels, breadcrumb, people and dates are what the mirror's front
    matter says of it; ``links``, each relation to another document of the work log and
    that document's id; ``file``, the org file that holds it, from the work log's folder;
    ``text``, what pandoc converts.
    """

    type: str
    id: str
    title: str
    status: str
    labels: tuple[str, ...]
    breadcrumb: tuple[str, ...]
    people: tuple[str, ...]
    links: tuple[tuple[str, str], ...]
    created: datetime
    updated: datetime
    file: str
    text: str

    @property
    def revision(self) -> str:
        """Name this state of the document: the digest of its text alone, not of how it converts."""
        return digest(self.text)

    @model_validator(mode="after")
    def check_copy(self) -> Self:
        """Refuse a type not the work log's, an id off its type's rule, and a link off the rules.

        A link's relation is one of RELATIONS, and the id that it names one safe path part.
        """
        if self.type not in WORKLOG_TYPES:
            message = "type: not one of the work log's types"
            raise RefusedError(message)
        require(WORKLOG_TYPES[self.type].id_rule, self.id, "id")
        for relation, other in self.links:
            require(IDENTIFIER, other, "links")
            if relation not in RELATIONS:
                message = "links: a relation not of RELATIONS"
                raise RefusedError(message)
        return self


class Carried(Record):
    """What a store began with of one document: its file of the mirror and that file's dates.

    ``path``, where the migration found the file, from the mirror's folder; ``created`` and
    ``updated``, the dates that its front matter held.
    """

    path: str
    created: datetime
    updated: datetime


class Copies(Record):
    """What one work log's copy store holds.

    ``documents``, each document as last read whole, by its id, in the order read;
    ``migrated``, by id, what the mirror held of each document that no read has taken
    since the store began, carried over before its first read; ``as_of``, the moment of
    the last read that met no problem, None before any.
    """

    documents: Mapping[str, WorklogCopy]
    migrated: Mapping[str, Carried]
    as_of: datetime | None

    @model_validator(mode="after")
    def check_copies(self) -> Self:
        """Refuse a document kept under an id other than its own."""
        if any(key != each.id for key, each in self.documents.items()):
            message = "documents: a document kept under another id"
            raise RefusedError(message)
        return self


def fetched(
    stored: Copies, read: Iterable[WorklogDocument], at: datetime, *, complete: bool
) -> Copies:
    """Say what the store holds once a read that began at ``at`` has taken ``read``.

    Each document read is copied whole. Its dates are its last ones while they hold and it
    has no day, so that an edit elsewhere in its org file moves neither: its stored
    copy's while its revision holds; at its first read, those that the mirror held,
    carried over, its text taken as theirs. Else they are its own, as
    ``WorklogDocument.dates`` gives them from the created date of its last ones, else from
    none. A ``complete`` read, which met no problem, confirms gone at once each document
    that it did not take, which leaves the store with its carried dates, and is the as-of
    time. After any other, every document not read keeps its last copy, and each carried
    date and the as-of time stay.
    """
    copies: dict[str, WorklogCopy] = {}
    for document in read:
        old = stored.documents.get(document.id)
        last = stored.migrated.get(document.id) if old is None else old
        holds = old is None or old.revision == digest(document.text)
        if last is not None and holds and document.day is None:
            created, updated = last.created, last.updated
        else:
            created, updated = document.dates(None if last is None else last.created)
        copies[document.id] = WorklogCopy(
            type=document.type,
            id=document.id,
            title=document.title,
            status=document.status,
            labels=document.labels,
            breadcrumb=document.breadcrumb,
            people=document.people,
            links=document.links,
            created=created,
            updated=updated,
            file=document.file.path.as_posix(),
            text=document.text,
        )
    if complete:
        return Copies(documents=copies, migrated={}, as_of=at)
    return Copies(
        documents={
            **copies,
            **{key: each for key, each in stored.documents.items() if key not in copies},
        },
        migrated={key: moment for key, moment in stored.migrated.items() if key not in copies},
        as_of=stored.as_of,
    )
