"""What the Markdown mirror says of each document, in the front matter of its file."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Self

from pydantic import model_validator

from kb_mcp.kernel.names import (
    DOCUMENT_ID,
    IDENTIFIER,
    IDENTITY,
    ISSUE_KEY,
    REVISION_NAME,
    SCOPE,
    SOURCE_NAME,
    TYPE_NAME,
    RefusedError,
    require,
)
from kb_mcp.kernel.record import Record

# The role of a meeting's participants and a transcript's speakers. A document that names
# a participant names no other role, so that a read's front matter, which is never cut,
# names one kind's people alone, within the read's budget.
PARTICIPANT = "participant"
# The roles that a person can hold in a document, a closed set, in the order that the
# mirror gives a document's people.
ROLES = ("author", "creator", "assignee", "commenter", PARTICIPANT)
# The roles that one person alone holds in a document; each other is held once per person.
SOLE = frozenset({"author", "creator", "assignee"})
# The relations that a document can have to another, a closed set: a meeting's to its
# transcript, and a transcript's to the meeting that summarises it.
RELATIONS = ("transcript", "summary")


class Mention(Record):
    """One role that one document gives to one name, as its source writes the name.

    ``identity`` is the issuer, a colon and the value, such as ``atlassian:5f1a``, None
    where the source gives none; ``at`` holds a commenter's comment times, and no other
    role has it.
    """

    role: str
    name: str
    identity: str | None = None
    at: tuple[datetime, ...] = ()

    @model_validator(mode="after")
    def check_mention(self) -> Self:
        """Refuse a role not in ROLES, an empty text or a line break, a field off its rule.

        An identity follows IDENTITY; ``at`` is a commenter's alone, never empty there, its
        times in UTC and ascending.
        """
        if self.role not in ROLES:
            message = "role: not one of the roles"
            raise RefusedError(message)
        texts = [self.name] if self.identity is None else [self.name, self.identity]
        if any(text.splitlines() != [text] for text in texts):
            message = "name, identity: empty, or with a line break"
            raise RefusedError(message)
        if self.identity is not None:
            require(IDENTITY, self.identity, "identity")
        if bool(self.at) != (self.role == "commenter"):
            message = "at: only and always for a commenter"
            raise RefusedError(message)
        if any(moment.utcoffset() != timedelta(0) for moment in self.at) or (
            list(self.at) != sorted(self.at)
        ):
            message = "at: a time not in UTC, or out of order"
            raise RefusedError(message)
        return self


class SourceFile(Record):
    """What a source's file of the mirror says beside its documents.

    ``roles`` gives each of the source's document types, by name, the roles that its
    documents take, in the order of ROLES, as its connector declares them;
    ``containers`` names those of its types that are containers, whose documents have no
    body and so no section; ``as_of`` each of its scopes whose as-of time is known, as the
    front matter writes a scope, that time.
    """

    roles: Mapping[str, tuple[str, ...]]
    containers: tuple[str, ...] = ()
    as_of: Mapping[str, datetime]

    @model_validator(mode="after")
    def check_source_file(self) -> Self:
        """Refuse a type off TYPE_NAME, and a role not in ROLES, given twice or out of order.

        And a container that is none of the types, a scope off SCOPE, and a time not in
        UTC.
        """
        for name, roles in self.roles.items():
            require(TYPE_NAME, name, "roles")
            if not set(roles) <= set(ROLES) or list(roles) != sorted(set(roles), key=ROLES.index):
                message = "roles: not of the roles, or out of their order"
                raise RefusedError(message)
        if not set(self.containers) <= self.roles.keys():
            message = "containers: not one of the types"
            raise RefusedError(message)
        for scope, moment in self.as_of.items():
            require(SCOPE, scope, "as_of")
            if moment.utcoffset() != timedelta(0):
                message = "as_of: a time not in UTC"
                raise RefusedError(message)
        return self


def document_id(source: str, identifier: str) -> str:
    """Write a document id as a parent and a link name a document: ``<source>:<id>``."""
    return f"{source}:{identifier}"


def scope_name(scope_type: str, key: str) -> str:
    """Write a scope as a document names the one that holds it: ``<scope type>:<key>``."""
    return f"{scope_type}:{key}"


class Link(Record):
    """A link from a document to another of the mirror: the relation, and the other's id."""

    relation: str
    document: str

    @model_validator(mode="after")
    def check_link(self) -> Self:
        """Refuse a relation not in RELATIONS, and a document off DOCUMENT_ID."""
        if self.relation not in RELATIONS:
            message = "relation: not one of the relations"
            raise RefusedError(message)
        require(DOCUMENT_ID, self.document, "document")
        return self


class FrontMatter(Record):
    """The front matter of one document of the mirror, its fields in the order they are written.

    Every text is one line, so that the front matter stays a simple YAML mapping. A key
    that does not apply to a document (``key`` for a page, ``parent`` at the top of its
    scope) is None.
    """

    source: str
    type: str
    id: str
    key: str | None
    title: str
    scope: str
    status: str
    subtype: str | None
    labels: tuple[str, ...]
    people: tuple[Mention, ...]
    parent: str | None
    links: tuple[Link, ...]
    created: datetime
    updated: datetime
    version: int | None
    revision: str
    url: str | None
    breadcrumb: tuple[str, ...]

    @model_validator(mode="after")
    def check_front_matter(self) -> Self:
        """Refuse what the layout's table rules out for every source.

        A source, type, id, scope, parent or revision off its rule, a key off its rule, a
        text with a line break of any kind, a time not in UTC, a second author, creator or
        assignee, a commenter or a participant twice by name and identity, a participant
        beside another role, people out of the order of the roles, a parent or a link
        that is the document itself, and a link given twice. Which source fills which
        key, and its types, scopes, ids and revisions, are the rules of the code that
        builds its front matter.
        """
        require(SOURCE_NAME, self.source, "source")
        require(TYPE_NAME, self.type, "type")
        require(IDENTIFIER, self.id, "id")
        require(SCOPE, self.scope, "scope")
        require(REVISION_NAME, self.revision, "revision")
        if self.key is not None:
            require(ISSUE_KEY, self.key, "key")
        itself = document_id(self.source, self.id)
        if self.parent is not None:
            require(DOCUMENT_ID, self.parent, "parent")
        texts = [self.title, self.status, self.url, self.subtype]
        if any(
            text and text.splitlines() != [text]
            for text in [*texts, *self.labels, *self.breadcrumb]
        ):
            message = "a text holds a line break"
            raise RefusedError(message)
        if any(moment.utcoffset() != timedelta(0) for moment in (self.created, self.updated)):
            message = "a time not in UTC"
            raise RefusedError(message)
        held = [
            (person.role,) if person.role in SOLE else (person.role, person.name, person.identity)
            for person in self.people
        ]
        order = [ROLES.index(person.role) for person in self.people]
        roles = {person.role for person in self.people}
        if (
            len(set(held)) != len(held)
            or (PARTICIPANT in roles and len(roles) > 1)
            or order != sorted(order)
        ):
            message = (
                "people: a second author, creator or assignee, a commenter or a participant"
                " twice, a participant beside another role, or out of the order of the roles"
            )
            raise RefusedError(message)
        links = [(link.relation, link.document) for link in self.links]
        if self.parent == itself:
            message = "parent: the document itself"
            raise RefusedError(message)
        if len(set(links)) != len(links) or any(other == itself for _, other in links):
            message = "links: a link to the document itself, or one given twice"
            raise RefusedError(message)
        return self

    @property
    def ref(self) -> str:
        """Name the document as answers cite it: ``<source>:<key>``, else ``<source>:<id>``."""
        return f"{self.source}:{self.key or self.id}"

    @property
    def author(self) -> str | None:
        """Name the person whose role is author, if any: Jira's reporter, Confluence's author."""
        return next((person.name for person in self.people if person.role == "author"), None)

    @property
    def creator(self) -> str | None:
        """Name the person whose role is creator, if any: who created a Jira issue."""
        return next((person.name for person in self.people if person.role == "creator"), None)

    @property
    def assignee(self) -> str | None:
        """Name the person whose role is assignee, if any."""
        return next((person.name for person in self.people if person.role == "assignee"), None)
