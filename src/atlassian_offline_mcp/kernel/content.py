"""What the mirror holds, named once, whatever response or HTML it was read from.

Adapters build these types from one representation each
(``sources.atlassian.adapters.confluence_v2``, ``sources.atlassian.adapters.jira_v3``),
and every other layer sees only these types. When the site changes a response, the
adapter for that representation changes, and nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Literal

# The sources of the mirror, as sync's --include and --exclude name them.
type SourceName = Literal["confluence", "jira", "worklog"]
SOURCE_NAMES: tuple[SourceName, ...] = ("confluence", "jira", "worklog")
# An id names a folder of the raw store, so it must be one safe path part.
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
# A Confluence space key; a personal space's key begins with a tilde.
SPACE_KEY = re.compile(r"~?[A-Za-z0-9]+")
PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]+")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-[0-9]+")
# An embedding model's name, as the endpoint names it: the settings and the command
# line check it alike.
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
# A path on the site, never another host's: one slash, no second one, no backslash, no
# control character.
SITE_PATH = re.compile(r"/(?![/\\])[^\s\\\x00-\x1f\x7f]*")
# A revision's name: a Confluence version, or a Jira update time in UTC.
REVISION = re.compile(r"[0-9]{6}|[0-9]{8}T[0-9]{6}\.[0-9]{6}Z")
# A work-log document's id, by its type: an entry's digest, numbered from the second
# entry of one digest; a transcript's day and name, or its digest; a day's date; a
# meeting's day and title's slug, numbered after -- from the second meeting of one day
# and slug.
WORKLOG_IDS = {
    "entry": re.compile(r"e-[0-9a-f]{16}(?:-[0-9]+)?"),
    "transcript": re.compile(r"t-(?:[0-9]{8}-[A-Za-z0-9_-]{1,64}|[0-9a-f]{16})"),
    "day": re.compile(r"d-[0-9]{8}"),
    "meeting": re.compile(r"m-[0-9]{8}-[a-z0-9-]{1,64}"),
}
# Any work-log document's id, of whichever type.
WORKLOG_ID = re.compile("|".join(f"(?:{each.pattern})" for each in WORKLOG_IDS.values()))
# A work-log document's revision: a digest of what pandoc converts, and how.
WORKLOG_REVISION = re.compile(r"[0-9a-f]{16}")


class RefusedError(ValueError):
    """A value that a domain type refuses; the message names the field, never the value."""


def require(pattern: re.Pattern[str], value: str, name: str) -> None:
    """Refuse a value that does not match its rule, naming the field and the rule."""
    if not pattern.fullmatch(value):
        message = f"{name}: does not match {pattern.pattern}"
        raise RefusedError(message)


def version_revision(version: int) -> str:
    """Name a Confluence version, padded so that names sort as versions do."""
    return f"{version:06d}"


def time_revision(updated: datetime) -> str:
    """Name a state by its update time in UTC, so that names sort as times do."""
    return updated.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


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
        require(IDENTIFIER, self.id, "id")
        require(SPACE_KEY, self.key, "key")


@dataclass(frozen=True)
class Folder:
    """A Confluence folder: a node of the space's tree, with a title and no body."""

    id: str
    title: str
    parent_id: str | None = None
    parent_type: str | None = None  # a page or a folder, as for a page

    def __post_init__(self) -> None:
        """Refuse an id that could not name a node."""
        require(IDENTIFIER, self.id, "id")


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
        require(IDENTIFIER, self.id, "id")
        require(SITE_PATH, self.download, "download")


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
        """Refuse an id that could not name a folder, and a web page off the site."""
        require(IDENTIFIER, self.id, "id")
        require(SITE_PATH, self.url, "url")

    @property
    def revision(self) -> str:
        """Name this state by when it was last updated."""
        return time_revision(self.updated)


@dataclass(frozen=True, kw_only=True)
class ConfluenceDocument(Document):
    """A page or a blog post, versioned within its space."""

    source: ClassVar[str] = "confluence"

    space_id: str
    version: int
    status: str  # current, archived, trashed, and so on

    def __post_init__(self) -> None:
        """Refuse an id or a space id that could not name a folder."""
        super().__post_init__()
        require(IDENTIFIER, self.space_id, "space_id")

    @property
    def revision(self) -> str:
        """Name this state by its version."""
        return version_revision(self.version)


@dataclass(frozen=True, kw_only=True)
class BlogPost(ConfluenceDocument):
    """A Confluence blog post."""

    kind: ClassVar[str] = "blogposts"


@dataclass(frozen=True, kw_only=True)
class Page(ConfluenceDocument):
    """A Confluence page, with its place in the space's tree.

    Its parent is a page or a folder, as ``parent_type`` says, or none at the top of the
    space.
    """

    kind: ClassVar[str] = "pages"

    parent_id: str | None = None
    parent_type: str | None = None


@dataclass(frozen=True, kw_only=True)
class Issue(Document):
    """A Jira issue; its id stays when it moves, its key does not."""

    source: ClassVar[str] = "jira"
    kind: ClassVar[str] = "issues"

    key: str
    project: str  # the project's key
    issue_type: str
    status: str
    creator: Person | None = None  # who created it; its author is its reporter
    assignee: Person | None = None
    parent: str | None = None  # the parent issue's key

    def __post_init__(self) -> None:
        """Refuse an id, a key or a project key that could not name a file."""
        super().__post_init__()
        require(ISSUE_KEY, self.key, "key")
        require(PROJECT_KEY, self.project, "project")


@dataclass(frozen=True)
class Listed:
    """What a listing says of a document: enough to decide whether to fetch it, and how.

    An adapter reads it from a listing's entry leniently, apart from the rest of the
    entry, so that an entry whose other fields have changed still lets the document be
    fetched. It names its stored snapshot as the document would.
    """

    type: type[Document]
    id: str
    revision: str
    updated: datetime
    version: int | None = None  # a Confluence document's GETs are pinned to its version

    def __post_init__(self) -> None:
        """Refuse an id or a revision that could not name a folder."""
        require(IDENTIFIER, self.id, "id")
        require(REVISION, self.revision, "revision")

    @property
    def source(self) -> str:
        """Name the source, as the document's type does."""
        return self.type.source

    @property
    def kind(self) -> str:
        """Name the kind, as the document's type does."""
        return self.type.kind


@dataclass(frozen=True)
class Snapshot:
    """A document at one revision, with what the mirror shows of it."""

    document: Document
    html: str  # the body as the site renders it
    attachments: tuple[Attachment, ...] = ()
    comments: tuple[Comment, ...] = ()
