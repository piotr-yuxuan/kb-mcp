"""Confluence Cloud REST v2 responses, read into the domain's types.

What this code knows of the shape of Confluence's JSON is here and nowhere else. When
the site changes a response, the fix is in this module, and the raw store can be read
again without fetching anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.domain.content import (
    Attachment,
    BlogPost,
    ConfluenceDocument,
    Page,
    Person,
    Snapshot,
    Space,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# The responses that a snapshot of a page or a blog post keeps, by file name.
# GET /wiki/api/v2/{pages|blogposts}/{id}?body-format=storage&include-labels=true
DOCUMENT = "document.json"
# The same GET with body-format=view.
VIEW = "view.json"
# The results of every page of GET /wiki/api/v2/{pages|blogposts}/{id}/attachments.
ATTACHMENTS = "attachments.json"

# The prefix under which the site serves Confluence; v2 links are relative to it.
WIKI = "/wiki"


def space(fields: Fields) -> Space:
    """Read a space from a listing or a GET."""
    return Space(fields.text("id"), fields.text("key"), fields.text("name"))


def document(fields: Fields, kind: str) -> ConfluenceDocument:
    """Read a page or a blog post (``kind`` names which) from a listing or a GET."""
    if kind not in {Page.kind, BlogPost.kind}:
        message = f"not a kind of Confluence document: {kind}"
        raise ValueError(message)
    version = fields.object("version")
    labels = fields.optional_object("labels")
    author = fields.optional_text("authorId")
    common = {
        "id": fields.text("id"),
        "title": fields.text("title"),
        "author": None if author is None else Person(author),
        "created": fields.time("createdAt"),
        "updated": version.time("createdAt"),
        "url": WIKI + fields.object("_links").text("webui"),
        "labels": tuple(
            label.text("name") for label in (labels.objects("results") if labels else [])
        ),
        "space_id": fields.text("spaceId"),
        "version": version.integer("number"),
        "status": fields.text("status"),
    }
    if kind == Page.kind:
        return Page(**common, parent_id=fields.optional_text("parentId"))
    return BlogPost(**common)


def attachment(fields: Fields) -> Attachment:
    """Read an attachment from a v2 listing; its file comes through the v1 download."""
    link = fields.text("downloadLink")
    if not link.startswith("/"):
        message = "attachment.downloadLink: expected a path relative to the site's /wiki"
        raise RepresentationError(message)
    return Attachment(
        fields.text("id"),
        fields.text("title"),
        fields.text("mediaType"),
        fields.integer("fileSize"),
        WIKI + link,
    )


def snapshot(kind: str, responses: Mapping[str, object]) -> Snapshot:
    """Read a page or a blog post from the responses that its snapshot keeps."""
    return Snapshot(
        document(Fields(responses.get(DOCUMENT), DOCUMENT), kind),
        Fields(responses.get(VIEW), VIEW).object("body").object("view").text("value"),
        tuple(attachment(item) for item in Fields.each(responses.get(ATTACHMENTS), ATTACHMENTS)),
    )
