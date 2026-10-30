"""What the mirror holds, named once, whatever response or HTML it was read from.

Adapters build these types from one representation each
(``sources.atlassian.fetch.adapters.confluence_v2``, ``sources.atlassian.fetch.adapters.jira_v3``),
and every other layer sees only these types. When the site changes a response, the
adapter for that representation changes, and nothing else.
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import ClassVar, Self

from pydantic import model_validator

from kb_mcp.kernel.names import (
    IDENTIFIER,
    ISSUE_KEY,
    PROJECT_KEY,
    REVISION,
    SITE_PATH,
    SPACE_KEY,
    require,
    time_revision,
    version_revision,
)
from kb_mcp.kernel.record import Record


class Person(Record):
    """Someone named in content: the account id is stable; the name, when given, is not."""

    account_id: str
    display_name: str | None = None


class Space(Record):
    """A Confluence space."""

    id: str
    key: str
    name: str

    @model_validator(mode="after")
    def check_space(self) -> Self:
        """Refuse an id or a key that could not name a folder."""
        require(IDENTIFIER, self.id, "id")
        require(SPACE_KEY, self.key, "key")
        return self


class Folder(Record):
    """A Confluence folder: a node of the space's tree, with a title and no body."""

    id: str
    title: str
    parent_id: str | None = None
    parent_type: str | None = None  # a page or a folder, as for a page

    @model_validator(mode="after")
    def check_folder(self) -> Self:
        """Refuse an id that could not name a node."""
        require(IDENTIFIER, self.id, "id")
        return self


class Attachment(Record):
    """A file attached to a page, a blog post or an issue."""

    id: str
    filename: str
    media_type: str
    size: int  # bytes
    download: str  # the site-relative path whose GET returns the file

    @model_validator(mode="after")
    def check_attachment(self) -> Self:
        """Refuse an id that could not name a file, and a download off the site."""
        require(IDENTIFIER, self.id, "id")
        require(SITE_PATH, self.download, "download")
        return self


class Comment(Record):
    """A comment, with its body as the site renders it."""

    id: str
    author: Person | None
    created: datetime
    html: str


class Document(Record):
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

    @model_validator(mode="after")
    def check_document(self) -> Self:
        """Refuse an id that could not name a folder, and a web page off the site."""
        require(IDENTIFIER, self.id, "id")
        require(SITE_PATH, self.url, "url")
        return self

    @property
    def revision(self) -> str:
        """Name this state by when it was last updated."""
        return time_revision(self.updated)


class ConfluenceDocument(Document):
    """A page or a blog post, versioned within its space."""

    source: ClassVar[str] = "confluence"

    space_id: str
    version: int
    status: str  # current, archived, trashed, and so on

    @model_validator(mode="after")
    def check_confluence_document(self) -> Self:
        """Refuse an id or a space id that could not name a folder."""
        require(IDENTIFIER, self.space_id, "space_id")
        return self

    @property
    def revision(self) -> str:
        """Name this state by its version."""
        return version_revision(self.version)


class BlogPost(ConfluenceDocument):
    """A Confluence blog post."""

    kind: ClassVar[str] = "blogposts"


class Page(ConfluenceDocument):
    """A Confluence page, with its place in the space's tree.

    Its parent is a page or a folder, as ``parent_type`` says, or none at the top of the
    space.
    """

    kind: ClassVar[str] = "pages"

    parent_id: str | None = None
    parent_type: str | None = None


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

    @model_validator(mode="after")
    def check_issue(self) -> Self:
        """Refuse an id, a key or a project key that could not name a file."""
        require(ISSUE_KEY, self.key, "key")
        require(PROJECT_KEY, self.project, "project")
        return self


class Listed(Record):
    """What a listing says of a document: enough to decide whether to fetch it, and how.

    An adapter reads it from a listing's entry leniently, apart from the rest of the
    entry, so that an entry whose other fields have changed still lets the document be
    fetched. It names its stored snapshot as the document would.
    """

    # The builtin, which the field's own name hides in the class's body.
    type: builtins.type[Document]
    id: str
    revision: str
    updated: datetime
    version: int | None = None  # a Confluence document's GETs are pinned to its version

    @model_validator(mode="after")
    def check_listed(self) -> Self:
        """Refuse an id or a revision that could not name a folder."""
        require(IDENTIFIER, self.id, "id")
        require(REVISION, self.revision, "revision")
        return self

    @property
    def source(self) -> str:
        """Name the source, as the document's type does."""
        return self.type.source

    @property
    def kind(self) -> str:
        """Name the kind, as the document's type does."""
        return self.type.kind


class Snapshot(Record):
    """A document at one revision, with what the mirror shows of it."""

    document: Document
    html: str  # the body as the site renders it
    attachments: tuple[Attachment, ...] = ()
    comments: tuple[Comment, ...] = ()
