"""Confluence Cloud REST v2 responses, and the few v1 ones v2 lacks, read into the domain.

What this code knows of the shape of Confluence's JSON is here and nowhere else. When
the site changes a response, the fix is in this module, and the raw store can be read
again without fetching anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.content import (
    IDENTIFIER,
    SITE_PATH,
    Attachment,
    BlogPost,
    Folder,
    Listed,
    Page,
    Person,
    Snapshot,
    Space,
    require,
    version_revision,
)
from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.sources.atlassian.adapters.http import ReadPage, Request

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


# What to GET, and how a listing goes on. A v2 listing's next page is the path that its
# _links.next gives, query included.
LISTING_LIMIT = "250"
LISTED_STATUSES = {Page: "current,archived", BlogPost: "current"}
# How many account ids one GET of users names.
USERS_PER_REQUEST = 50


def space_request(key: str) -> Request:
    """GET the space with this key."""
    return Request(f"{WIKI}/api/v2/spaces", {"keys": key})


def listing_request(space_id: str, kind: type[Page | BlogPost]) -> Request:
    """GET the first page of a space's pages, or blog posts, without bodies."""
    return Request(
        f"{WIKI}/api/v2/spaces/{space_id}/{kind.kind}",
        {"limit": LISTING_LIMIT, "status": LISTED_STATUSES[kind]},
    )


def folder_request(folder_id: str) -> Request:
    """GET a folder, for its title and parent."""
    return Request(f"{WIKI}/api/v2/folders/{folder_id}")


def listed(fields: Fields, kind: type[Page | BlogPost]) -> Listed:
    """Read of a listing's entry only what decides a fetch: id, version, time."""
    version = fields.object("version")
    number = version.integer("number")
    with fields.refusals():
        return Listed(
            kind, fields.text("id"), version_revision(number), version.time("createdAt"), number
        )


def snapshot_requests(document: Listed) -> dict[str, tuple[Request, ReadPage | None]]:
    """Name the GETs whose responses make a snapshot, with the paging of a listing."""
    return {
        DOCUMENT: (document_request(document, "storage"), None),
        VIEW: (document_request(document, "view"), None),
        ATTACHMENTS: (attachments_request(document), listing_page),
    }


def entry_ids(entries: object) -> set[str]:
    """Read only the ids of a listing's entries, whatever else each entry holds.

    An entry without a usable id names nothing; entries that are not a list name none.
    """
    ids: set[str] = set()
    for entry in entries if type(entries) is list else []:
        identifier = entry.get("id") if type(entry) is dict else None
        if type(identifier) is str and IDENTIFIER.fullmatch(identifier):
            ids.add(identifier)
    return ids


def probe_request(kind: str, document_id: str) -> Request:
    """GET a page or a blog post without its body, to learn where it is, if anywhere."""
    return Request(f"{WIKI}/api/v2/{kind}/{document_id}")


def whereabouts(fields: Fields) -> tuple[str, str]:
    """Read where a probed page or blog post is: its space's id, and its status."""
    return fields.text("spaceId"), fields.text("status")


def document_request(document: Listed, body: str) -> Request:
    """GET a page or a blog post at its version, with its body as ``storage`` or ``view``."""
    params = {"body-format": body, "version": str(document.version)}
    if body == "storage":
        params["include-labels"] = "true"
    return Request(f"{WIKI}/api/v2/{document.kind}/{document.id}", params)


def attachments_request(document: Listed) -> Request:
    """GET the first page of a page's, or a blog post's, attachments."""
    return Request(
        f"{WIKI}/api/v2/{document.kind}/{document.id}/attachments", {"limit": LISTING_LIMIT}
    )


def users_request(account_ids: Sequence[str]) -> Request:
    """GET the users with these account ids, at most ``USERS_PER_REQUEST``."""
    return Request(
        f"{WIKI}/rest/api/user/bulk",
        {"accountId": list(account_ids), "limit": str(USERS_PER_REQUEST)},
    )


def current_user_request() -> Request:
    """GET the user whom the session signs in."""
    return Request(f"{WIKI}/rest/api/user/current")


def signed_in(response: Fields) -> bool:
    """Say whether the current user is someone; an expired session reads as anonymous."""
    return response.optional_text("accountId", absent=True) is not None


def listing_page(response: Fields, _: Request) -> tuple[list[Fields], Request | None]:
    """Read one page of a v2 listing: its results, and the request for the next page."""
    links = response.optional_object("_links", absent=True)
    following = links.optional_text("next", absent=True) if links else None
    return response.objects("results"), None if following is None else Request(following)


def users_page(response: Fields, _: Request) -> tuple[list[Fields], Request | None]:
    """Read the users of a bulk GET, which names them all on one page."""
    return response.objects("results"), None
