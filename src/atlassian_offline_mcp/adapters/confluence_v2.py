"""Confluence Cloud REST v2 responses, and the few v1 ones v2 lacks, read into the domain.

What this code knows of the shape of Confluence's JSON is here and nowhere else. When
the site changes a response, the fix is in this module, and the raw store can be read
again without fetching anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.fields import Fields
from atlassian_offline_mcp.domain.content import (
    SITE_PATH,
    Attachment,
    BlogPost,
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
    with fields.refusals():
        return Space(fields.text("id"), fields.text("key"), fields.text("name"))


def person(fields: Fields) -> Person:
    """Read a user of GET /wiki/rest/api/user/bulk; the email address is left behind."""
    with fields.refusals():
        return Person(fields.text("accountId"), fields.optional_text("displayName"))


def document(fields: Fields, kind: type[Page | BlogPost]) -> Page | BlogPost:
    """Read a page or a blog post, as ``kind`` says, from a listing or a GET.

    A listing carries no labels; a GET with ``include-labels=true`` carries the first
    page of them.
    """
    version = fields.object("version")
    labels = fields.optional_object("labels")
    author = fields.optional_text("authorId")
    place = {"parent_id": fields.optional_text("parentId")} if kind is Page else {}
    with fields.refusals():
        return kind(
            id=fields.text("id"),
            title=fields.text("title"),
            author=None if author is None else Person(author),
            created=fields.time("createdAt"),
            updated=version.time("createdAt"),
            url=WIKI + fields.object("_links").text("webui"),
            labels=tuple(
                label.text("name") for label in (labels.objects("results") if labels else [])
            ),
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
        if not SITE_PATH.fullmatch(link):
            message = f"downloadLink: does not match {SITE_PATH.pattern}"
            raise ValueError(message)
        return Attachment(
            fields.text("id"),
            fields.text("title"),
            fields.text("mediaType"),
            fields.integer("fileSize"),
            WIKI + link,
        )


def snapshot(kind: type[Page | BlogPost], responses: Mapping[str, object]) -> Snapshot:
    """Read a page or a blog post from the responses that its snapshot keeps."""
    return Snapshot(
        document(Fields(responses.get(DOCUMENT), DOCUMENT), kind),
        Fields(responses.get(VIEW), VIEW).object("body").object("view").text("value"),
        tuple(attachment(item) for item in Fields.each(responses.get(ATTACHMENTS), ATTACHMENTS)),
    )
