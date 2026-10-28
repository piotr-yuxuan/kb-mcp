"""What the Markdown mirror says of each document, in the front matter of its file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.content import (
    IDENTIFIER,
    ISSUE_KEY,
    PROJECT_KEY,
    REVISION,
    SPACE_KEY,
    WORKLOG_ID,
    WORKLOG_REVISION,
    RefusedError,
    require,
)

if TYPE_CHECKING:
    from datetime import datetime

TYPES = {
    "page": "confluence",
    "blogpost": "confluence",
    "issue": "jira",
    "entry": "worklog",
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
# The rules of each source's ids and revisions.
PATTERNS = {
    "confluence": (IDENTIFIER, REVISION),
    "jira": (IDENTIFIER, REVISION),
    "worklog": (WORKLOG_ID, WORKLOG_REVISION),
}
# The roles that a person can hold in a document, a closed set, in the order that the
# mirror gives a document's people.
ROLES = ("author", "creator", "assignee", "commenter")
# The roles that one person alone holds in a document; each other is held once per person.
SOLE = {"author", "creator", "assignee"}


@dataclass(frozen=True, kw_only=True)
class PersonRole:
    """One person in one role of a document, named as the source gives the name.

    ``account`` is the source's account id, None when it has none; ``at`` holds a
    commenter's comment times, and no other role has it.
    """

    role: str
    name: str
    account: str | None = None
    at: tuple[datetime, ...] = ()

    def __post_init__(self) -> None:
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


@dataclass(frozen=True, kw_only=True)
class FrontMatter:
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
    people: tuple[PersonRole, ...] = ()
    created: datetime
    updated: datetime
    version: int | None
    revision: str
    url: str | None
    breadcrumb: tuple[str, ...]
    fetched_at: datetime

    def __post_init__(self) -> None:
        """Refuse what the layout's table rules out.

        A source and type that disagree, a key that only the other source has, an id or
        key off its rule, a text with a line break of any kind, a time not in UTC, a
        second author, creator or assignee, a commenter twice by name and account.
        """
        if TYPES.get(self.type) != self.source:
            message = "type: not one of the source's types"
            raise RefusedError(message)
        for name, source in ONLY.items():
            if (getattr(self, name) is not None) != (self.source == source):
                message = f"{name}: only and always for {source}"
                raise RefusedError(message)
        identifier, revision = PATTERNS[self.source]
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
        if len(set(held)) != len(held):
            message = "people: a second author, creator or assignee, or a commenter twice"
            raise RefusedError(message)

    @property
    def author(self) -> str | None:
        """Name the person whose role is author, if any: Jira's reporter, Confluence's author."""
        return next((person.name for person in self.people if person.role == "author"), None)

    @property
    def assignee(self) -> str | None:
        """Name the person whose role is assignee, if any."""
        return next((person.name for person in self.people if person.role == "assignee"), None)
