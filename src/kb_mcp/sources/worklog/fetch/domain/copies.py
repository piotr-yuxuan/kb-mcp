"""What the work log's copy store holds: each document as its fetch last read it whole.

A fetch reads the work log's folder in place and keeps, for each document, the properties
that the mirror's front matter says of it and the text that pandoc converts, whose digest
alone is its revision. Only the copy store's adapter knows how the store is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Self

from pydantic import model_validator

from kb_mcp.kernel.names import IDENTIFIER, WORKLOG_TYPES, RefusedError, require
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import RELATIONS
from kb_mcp.sources.worklog.fetch.domain.worklog import digest


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


class Copies(Record):
    """What one work log's copy store holds.

    ``documents``, each document as last read whole, by its id, in the order read;
    ``migrated``, by id, the created date that the mirror held of each document that no
    read has taken since the store began, carried over before its first read; ``as_of``,
    the moment of the last read that met no problem, None before any.
    """

    documents: Mapping[str, WorklogCopy]
    migrated: Mapping[str, datetime]
    as_of: datetime | None

    @model_validator(mode="after")
    def check_copies(self) -> Self:
        """Refuse a document kept under an id other than its own."""
        if any(key != each.id for key, each in self.documents.items()):
            message = "documents: a document kept under another id"
            raise RefusedError(message)
        return self
