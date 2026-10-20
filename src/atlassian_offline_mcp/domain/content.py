"""What the mirror holds, named once, whatever response or HTML it was read from.

Adapters build these types from one representation each (``adapters.confluence_v2``,
``adapters.jira_v3``), and every other layer sees only these types. When the site
changes a response, the adapter for that representation changes, and nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

# An id names a folder of the raw store, so it must be one safe path part.
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
# A Confluence space key; a personal space's key begins with a tilde.
SPACE_KEY = re.compile(r"~?[A-Za-z0-9]+")
PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]+")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-[0-9]+")
# A path on the site, never another host's: one slash, no second one, no backslash.
SITE_PATH = re.compile(r"/(?![/\\])[^\s\\]*")


def _require(pattern: re.Pattern[str], value: str, name: str) -> None:
    # The message names the field and the rule, never the value, which is content.
    if not pattern.fullmatch(value):
        message = f"{name}: does not match {pattern.pattern}"
        raise ValueError(message)


@dataclass(frozen=True)
class Person:
    """Someone named in content: the account id is stable; the name, when given, is not."""

    account_id: str
    display_name: str | None = None


@dataclass(frozen=True)
class Space:
    """A Confluence space."""

    id: str
    key: str
    name: str

    def __post_init__(self) -> None:
        """Refuse an id or a key that could not name a folder."""
        _require(IDENTIFIER, self.id, "id")
        _require(SPACE_KEY, self.key, "key")


@dataclass(frozen=True)
class Attachment:
    """A file attached to a page, a blog post or an issue."""

    id: str
    filename: str
    media_type: str
    size: int  # bytes
    download: str  # the site-relative path whose GET returns the file

    def __post_init__(self) -> None:
        """Refuse an id that could not name a file, and a download off the site."""
        _require(IDENTIFIER, self.id, "id")
        _require(SITE_PATH, self.download, "download")


@dataclass(frozen=True)
class Comment:
    """A comment, with its body as the site renders it."""

    id: str
    author: Person | None
    created: datetime
    html: str


@dataclass(frozen=True, kw_only=True)
class Document:
    """A page, a blog post or an issue: what becomes one file of the mirror.

    ``source`` and ``kind`` name where it is stored; ``revision`` names this state of it,
    and orders states as text.
    """

    source: ClassVar[str]
    kind: ClassVar[str]

    id: str
    title: str
    author: Person | None
    created: datetime
    updated: datetime
    url: str  # the site-relative path of its web page
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse an id that could not name a folder."""
        _require(IDENTIFIER, self.id, "id")

    @property
    def revision(self) -> str:
        """Name this state by when it was last updated, in UTC."""
        return self.updated.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


@dataclass(frozen=True, kw_only=True)
class ConfluenceDocument(Document):
    """A page or a blog post, versioned within its space."""

    source: ClassVar[str] = "confluence"

    space_id: str
    version: int
    status: str  # current, archived, trashed, and so on

    def __post_init__(self) -> None:
        """Refuse an id or a space id that could not name a folder or a listing."""
        super().__post_init__()
        _require(IDENTIFIER, self.space_id, "space_id")

    @property
    def revision(self) -> str:
        """Name this state by its version number, padded so that text order is numeric."""
        return f"{self.version:06d}"


@dataclass(frozen=True, kw_only=True)
class BlogPost(ConfluenceDocument):
    """A Confluence blog post."""

    kind: ClassVar[str] = "blogposts"


@dataclass(frozen=True, kw_only=True)
class Page(ConfluenceDocument):
    """A Confluence page, with its place in the space's tree."""

    kind: ClassVar[str] = "pages"

    parent_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class Issue(Document):
    """A Jira issue; its id stays when it moves, its key does not."""

    source: ClassVar[str] = "jira"
    kind: ClassVar[str] = "issues"

    key: str
    project: str  # the project's key
    issue_type: str
    status: str
    assignee: Person | None = None
    parent: str | None = None  # the parent issue's key

    def __post_init__(self) -> None:
        """Refuse an id, a key or a project key that could not name a file."""
        super().__post_init__()
        _require(ISSUE_KEY, self.key, "key")
        _require(PROJECT_KEY, self.project, "project")


@dataclass(frozen=True)
class Snapshot:
    """A document at one revision, with what the mirror shows of it."""

    document: Document
    html: str  # the body as the site renders it
    attachments: tuple[Attachment, ...] = ()
    comments: tuple[Comment, ...] = ()
