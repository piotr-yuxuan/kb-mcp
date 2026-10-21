"""Confluence Cloud REST v2 responses, and the few v1 ones v2 lacks, read into the domain.

What this code knows of the shape of Confluence's JSON is here and nowhere else. When
the site changes a response, the fix is in this module, and the raw store can be read
again without fetching anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.domain.content import (
    SITE_PATH,
    Attachment,
    BlogPost,
    Folder,
    Page,
    Person,
    Snapshot,
    Space,
    require,
    version_revision,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# The responses that a snapshot of a page or a blog post keeps, by file name.
# GET /wiki/api/v2/{pages|blogposts}/{id}?version=N&body-format=storage&include-labels=true
DOCUMENT = "document.json"
# GET /wiki/api/v2/{pages|blogposts}/{id}?version=N&body-format=view, the same version.
VIEW = "view.json"
# The results of every page of GET /wiki/api/v2/{pages|blogposts}/{id}/attachments.
ATTACHMENTS = "attachments.json"

# The prefix under which the site serves Confluence; v2 links are relative to it.
WIKI = "/wiki"


def space(fields: Fields) -> Space:
    """Read a space from GET /wiki/api/v2/spaces."""
    with fields.refusals():
        return Space(fields.text("id"), fields.text("key"), fields.text("name"))


def folder(fields: Fields) -> Folder:
    """Read a folder from GET /wiki/api/v2/folders/{id}."""
    with fields.refusals():
        return Folder(
            fields.text("id"),
            fields.text("title"),
            fields.optional_text("parentId"),
            fields.optional_text("parentType"),
        )


def person(fields: Fields) -> Person:
    """Read a user of GET /wiki/rest/api/user/bulk; the email address is left behind."""
    with fields.refusals():
        return Person(fields.text("accountId"), fields.optional_text("displayName"))


def document(fields: Fields, kind: type[Page | BlogPost]) -> Page | BlogPost:
    """Read a page or a blog post, as ``kind`` says, from a listing or a GET.

    A listing carries no labels; a GET with ``include-labels=true`` carries the first
    page of them, which ``snapshot`` requires.
    """
    version = fields.object("version")
    labels = fields.optional_object("labels", absent=True)
    author = fields.optional_text("authorId")
    links = fields.object("_links")
    place = {}
    if kind is Page:
        place = {
            "parent_id": fields.optional_text("parentId"),
            "parent_type": fields.optional_text("parentType"),
        }
    with fields.refusals():
        require(SITE_PATH, links.text("webui"), "_links.webui")
        return kind(
            id=fields.text("id"),
            title=fields.text("title"),
            author=None if author is None else Person(author),
            created=fields.time("createdAt"),
            updated=version.time("createdAt"),
            url=WIKI + links.text("webui"),
            labels=tuple(label.text("name") for label in labels.objects("results"))
            if labels
            else (),
            space_id=fields.text("spaceId"),
            version=version.integer("number"),
            status=fields.text("status"),
            **place,
        )


def attachment(fields: Fields) -> Attachment:
    """Read an attachment from a v2 listing; its file comes through its download link.

    The link is relative to the site's ``/wiki`` and leads to the v1 download.
    """
    link = fields.text("downloadLink")
    with fields.refusals():
        require(SITE_PATH, link, "downloadLink")
        return Attachment(
            fields.text("id"),
            fields.text("title"),
            fields.text("mediaType"),
            fields.integer("fileSize"),
            WIKI + link,
        )


def identity(responses: Mapping[str, object]) -> tuple[str, str]:
    """Read only what names a snapshot's folder: its id and its revision.

    The view must be of the same page at the same version as the document, since the
    two are separate GETs and the page can change between them.
    """
    stored = Fields(responses.get(DOCUMENT), DOCUMENT)
    shown = Fields(responses.get(VIEW), VIEW)
    number = stored.object("version").integer("number")
    if shown.text("id") != stored.text("id"):
        message = f"{VIEW}.id: does not match {DOCUMENT}.id"
        raise RepresentationError(message)
    if shown.object("version").integer("number") != number:
        message = f"{VIEW}.version.number: does not match {DOCUMENT}.version.number"
        raise RepresentationError(message)
    return stored.text("id"), version_revision(number)


def snapshot(kind: type[Page | BlogPost], responses: Mapping[str, object]) -> Snapshot:
    """Read a page or a blog post from the responses that its snapshot keeps."""
    identity(responses)
    stored = Fields(responses.get(DOCUMENT), DOCUMENT)
    stored.object("labels")  # asked for with include-labels, so never absent here
    return Snapshot(
        document(stored, kind),
        Fields(responses.get(VIEW), VIEW).object("body").object("view").text("value"),
        tuple(attachment(item) for item in Fields.each(responses.get(ATTACHMENTS), ATTACHMENTS)),
    )
