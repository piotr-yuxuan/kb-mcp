"""What the Markdown mirror says of each document, in the front matter of its file."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Self

from pydantic import model_validator

from kb_mcp.kernel.names import (
    IDENTIFIER,
    ISSUE_KEY,
    PROJECT_KEY,
    REVISION,
    SPACE_KEY,
    WORKLOG_IDS,
    WORKLOG_REVISION,
    RefusedError,
    require,
)
from kb_mcp.kernel.record import Record

TYPES = {
    "page": "confluence",
    "blogpost": "confluence",
    "issue": "jira",
    "entry": "worklog",
    "day": "worklog",
    "meeting": "worklog",
    "transcript": "worklog",
}
# Keys that one source alone has, always.
ONLY = {
    "space": "confluence",
    "version": "confluence",
    "key": "jira",
    "project": "jira",
    "issue_type": "jira",
}
# The rules of each type's ids, and of its source's revisions: a work-log document's id
# by its type, so that a day never bears a meeting's.
PATTERNS = {
    "page": (IDENTIFIER, REVISION),
    "blogpost": (IDENTIFIER, REVISION),
    "issue": (IDENTIFIER, REVISION),
    **{kind: (pattern, WORKLOG_REVISION) for kind, pattern in WORKLOG_IDS.items()},
}
# The role of a meeting's participants and a transcript's speakers.
PARTICIPANT = "participant"
# The roles that a person can hold in a document, a closed set, in the order that the
# mirror gives a document's people.
ROLES = ("author", "creator", "assignee", "commenter", PARTICIPANT)
# The roles that one person alone holds in a document; each other is held once per person.
SOLE = frozenset({"author", "creator", "assignee"})
# The roles of the work log's documents, which hold no other: a meeting's participants
# and a transcript's speakers. No document holds both kinds, so that a read's front
# matter, which is never cut, names one kind's people alone, within the read's budget.
WORKLOG_ROLES = frozenset({PARTICIPANT})
# The relations that a document can have to another, a closed set: a meeting's to its
# transcript, and a transcript's to the meeting that summarises it.
RELATIONS = ("transcript", "summary")


class PersonRole(Record):
    """One person in one role of a document, named as the source gives the name.

    ``account`` is the source's account id, None when it has none; ``at`` holds a
    commenter's comment times, and no other role has it.
    """

    role: str
    name: str
    account: str | None = None
    at: tuple[datetime, ...] = ()

    @model_validator(mode="after")
    def check_person_role(self) -> Self:
        """Refuse a role not in ROLES, an empty text or a line break, ``at`` off its rule.

        ``at`` is a commenter's alone, never empty there, its times in UTC and ascending.
        """
        if self.role not in ROLES:
            message = "role: not one of the roles"
            raise RefusedError(message)
        texts = [self.name] if self.account is None else [self.name, self.account]
        if any(text.splitlines() != [text] for text in texts):
            message = "name, account: empty, or with a line break"
            raise RefusedError(message)
        if bool(self.at) != (self.role == "commenter"):
            message = "at: only and always for a commenter"
            raise RefusedError(message)
        if any(moment.utcoffset() != timedelta(0) for moment in self.at) or (
            list(self.at) != sorted(self.at)
        ):
            message = "at: a time not in UTC, or out of order"
            raise RefusedError(message)
        return self


class Link(Record):
    """A link from a document to another of the mirror: the relation, and the other's ref."""

    relation: str
    ref: str

    @model_validator(mode="after")
    def check_link(self) -> Self:
        """Refuse a relation not in RELATIONS, and a ref off IDENTIFIER, as ``read`` takes it."""
        if self.relation not in RELATIONS:
            message = "relation: not one of the relations"
            raise RefusedError(message)
        require(IDENTIFIER, self.ref, "ref")
        return self


class FrontMatter(Record):
    """The front matter of one mirrored document, its fields in the order they are written.

    Every text is one line, so that the front matter stays a simple YAML mapping. A key
    that does not apply to a source (``key`` for Confluence, ``space`` for Jira) is None.
    """

    source: str
    type: str
    id: str
    key: str | None
    title: str
    space: str | None
    project: str | None
    status: str
    issue_type: str | None
    labels: tuple[str, ...]
    people: tuple[PersonRole, ...]
    links: tuple[Link, ...]
    created: datetime
    updated: datetime
    version: int | None
    revision: str
    url: str | None
    breadcrumb: tuple[str, ...]
    fetched_at: datetime

    @model_validator(mode="after")
    def check_front_matter(self) -> Self:
        """Refuse what the layout's table rules out.

        A source and type that disagree, a key that only the other source has, an id off
        its type's rule, a key off its rule, a text with a line break of any kind, a time
        not in UTC, a second author, creator or assignee, a commenter or a participant
        twice by name and account, a role of another source, people out of the order of
        the roles, a link to the document itself, by its id or key, and a link given twice.
        """
        if TYPES.get(self.type) != self.source:
            message = "type: not one of the source's types"
            raise RefusedError(message)
        for name, source in ONLY.items():
            if (getattr(self, name) is not None) != (self.source == source):
                message = f"{name}: only and always for {source}"
                raise RefusedError(message)
        identifier, revision = PATTERNS[self.type]
        require(identifier, self.id, "id")
        require(revision, self.revision, "revision")
        for value, pattern, name in (
            (self.key, ISSUE_KEY, "key"),
            (self.space, SPACE_KEY, "space"),
            (self.project, PROJECT_KEY, "project"),
        ):
            if value is not None:
                require(pattern, value, name)
        texts = [self.title, self.status, self.url, self.issue_type]
        if any(
            text and text.splitlines() != [text]
            for text in [*texts, *self.labels, *self.breadcrumb]
        ):
            message = "a text holds a line break"
            raise RefusedError(message)
        if any(
            moment.utcoffset() != timedelta(0)
            for moment in (self.created, self.updated, self.fetched_at)
        ):
            message = "a time not in UTC"
            raise RefusedError(message)
        held = [
            (person.role,) if person.role in SOLE else (person.role, person.name, person.account)
            for person in self.people
        ]
        order = [ROLES.index(person.role) for person in self.people]
        worklog = self.source == "worklog"
        if (
            len(set(held)) != len(held)
            or any((person.role in WORKLOG_ROLES) != worklog for person in self.people)
            or order != sorted(order)
        ):
            message = (
                "people: a second author, creator or assignee, a commenter or a participant"
                " twice, a role of another source, or out of the order of the roles"
            )
            raise RefusedError(message)
        links = [(link.relation, link.ref) for link in self.links]
        if len(set(links)) != len(links) or any(ref in (self.id, self.key) for _, ref in links):
            message = "links: a link to the document itself, or one given twice"
            raise RefusedError(message)
        return self

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
