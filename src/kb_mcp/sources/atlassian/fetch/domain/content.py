"""What the fetch stores and the prepare reads, named once, whatever response gave it.

Adapters build these types from one representation each
(``sources.atlassian.fetch.adapters.confluence_v2``,
``sources.atlassian.fetch.adapters.jira_v3``), and every other layer sees only these
types. When the site changes a response, the adapter for that representation changes,
and nothing else.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import ClassVar, Self

from pydantic import model_validator

from kb_mcp.kernel.names import IDENTIFIER, ISSUE_KEY, PROJECT_KEY, SPACE_KEY, require
from kb_mcp.kernel.record import Record
from kb_mcp.sources.atlassian.fetch.domain.names import BLOGPOST, ISSUE, PAGE
from kb_mcp.sources.declaration import DocumentType

# A path on the site, never another host's: one slash, no second one, no backslash, no
# control character.
SITE_PATH = re.compile(r"/(?![/\\])[^\s\\\x00-\x1f\x7f]*")
# A revision's name: a Confluence version, or a Jira update time in UTC.
REVISION = re.compile(r"[0-9]{6}|[0-9]{8}T[0-9]{6}\.[0-9]{6}Z")


def version_revision(version: int) -> str:
    """Name a Confluence version, padded so that names sort as versions do."""
    return f"{version:06d}"


def time_revision(updated: datetime) -> str:
    """Name a state by its update time in UTC, so that names sort as times do."""
    return updated.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


class SiteUser(Record):
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
    author: SiteUser | None
    created: datetime
    html: str


class FetchedDocument(Record):
    """A page, a blog post or an issue: what becomes one file of the mirror.

    ``document_type`` names where its source's view of the raw store keeps it; ``revision``
    names this state of it, and orders states as text.
    """

    document_type: ClassVar[DocumentType]

    id: str
    title: str
    author: SiteUser | None
    created: datetime
    updated: datetime
    site_path: str  # the site-relative path of its web page
    labels: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_document(self) -> Self:
        """Refuse an id that could not name a folder, and a web page off the site."""
        require(IDENTIFIER, self.id, "id")
        require(SITE_PATH, self.site_path, "url")
        return self

    @property
    def revision(self) -> str:
        """Name this state by when it was last updated."""
        return time_revision(self.updated)


class ConfluenceDocument(FetchedDocument):
    """A page or a blog post, versioned within its space."""

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

    document_type: ClassVar[DocumentType] = BLOGPOST


class Page(ConfluenceDocument):
    """A Confluence page, with its place in the space's tree.

    Its parent is a page or a folder, as ``parent_type`` says, or none at the top of the
    space.
    """

    document_type: ClassVar[DocumentType] = PAGE

    parent_id: str | None = None
    parent_type: str | None = None


class Issue(FetchedDocument):
    """A Jira issue; its id stays when it moves, its key does not."""

    document_type: ClassVar[DocumentType] = ISSUE

    key: str
    project: str  # the project's key
    issue_type: str
    status: str
    creator: SiteUser | None = None  # who created it; its author is its reporter
    assignee: SiteUser | None = None
    parent: str | None = None  # the parent issue's key

    @model_validator(mode="after")
    def check_issue(self) -> Self:
        """Refuse an id, a key or a project key that could not name a file."""
        require(ISSUE_KEY, self.key, "key")
        require(PROJECT_KEY, self.project, "project")
        return self


# The documents' classes: Confluence's, each listed per space, then every one.
CONFLUENCE_CLASSES: tuple[type[Page | BlogPost], ...] = (Page, BlogPost)
DOCUMENT_CLASSES: tuple[type[Page | BlogPost | Issue], ...] = (*CONFLUENCE_CLASSES, Issue)


class Listed(Record):
    """What a listing says of a document: enough to decide whether to fetch it, and how.

    An adapter reads it from a listing's entry leniently, apart from the rest of the
    entry, so that an entry whose other fields have changed still lets the document be
    fetched. It names its stored snapshot as the document would.
    """

    document_class: type[FetchedDocument]
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
    def document_type(self) -> DocumentType:
        """Give the document type, as the document's class does."""
        return self.document_class.document_type


class Snapshot(Record):
    """A document at one revision, with what the mirror shows of it."""

    document: FetchedDocument
    html: str  # the body as the site renders it
    attachments: tuple[Attachment, ...] = ()
    comments: tuple[Comment, ...] = ()
