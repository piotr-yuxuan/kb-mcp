"""What the Markdown mirror says of each document, in the front matter of its file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from atlassian_offline_mcp.domain.content import (
    IDENTIFIER,
    ISSUE_KEY,
    PROJECT_KEY,
    REVISION,
    SPACE_KEY,
    RefusedError,
    require,
)

if TYPE_CHECKING:
    from datetime import datetime

TYPES = {"page": "confluence", "blogpost": "confluence", "issue": "jira"}
# Keys that one source alone has, always.
ONLY = {
    "space": "confluence",
    "version": "confluence",
    "key": "jira",
    "project": "jira",
    "issue_type": "jira",
}


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
    author: str | None
    assignee: str | None
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
        key off its rule, a text with a line break of any kind, a time not in UTC.
        """
        if TYPES.get(self.type) != self.source:
            message = "type: not one of the source's types"
            raise RefusedError(message)
        for name, source in ONLY.items():
            if (getattr(self, name) is not None) != (self.source == source):
                message = f"{name}: only and always for {source}"
                raise RefusedError(message)
        if self.source == "confluence" and self.assignee is not None:
            message = "assignee: only for jira"
            raise RefusedError(message)
        require(IDENTIFIER, self.id, "id")
        require(REVISION, self.revision, "revision")
        for value, pattern, name in (
            (self.key, ISSUE_KEY, "key"),
            (self.space, SPACE_KEY, "space"),
            (self.project, PROJECT_KEY, "project"),
        ):
            if value is not None:
                require(pattern, value, name)
        texts = [self.title, self.status, self.author, self.assignee, self.url, self.issue_type]
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
