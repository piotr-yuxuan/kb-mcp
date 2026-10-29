"""Jira Cloud REST v3 responses, read into the domain's types.

What this code knows of the shape of Jira's JSON is here and nowhere else. When the
site changes a response, the fix is in this module, and the raw store can be read
again without fetching anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from kb_mcp.kernel.content import Attachment, Comment, Issue, Listed, Person, Snapshot
from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.kernel.names import time_revision
from kb_mcp.sources.atlassian.adapters.http import ReadPage, Request

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

# The fields that ``issue`` reads: a search that asks for them lists issues fully
# enough to decide which to fetch, but holds no rendered body.
ISSUE_FIELDS = (
    "summary,status,issuetype,project,labels,created,updated,"
    "reporter,creator,assignee,parent,attachment"
)

# The responses that a snapshot of an issue keeps, by file name.
# GET /rest/api/3/issue/{id}?expand=renderedFields
ISSUE = "issue.json"
# The comments of every page of GET /rest/api/3/issue/{id}/comment?expand=renderedBody.
COMMENTS = "comments.json"

# Where an attachment's file is on the site, as the path of its content address.
CONTENT_PATH = "/rest/api/"


def person(fields: Fields) -> Person:
    """Read a user; the email address, when there is one, is left behind."""
    with fields.refusals():
        return Person(
            account_id=fields.text("accountId"), display_name=fields.optional_text("displayName")
        )


def attachment(fields: Fields) -> Attachment:
    """Read an attachment; its file is at the path of its ``content`` address."""
    try:
        content = urlsplit(fields.text("content"))
    except ValueError:
        content = None
    if content is None or content.scheme != "https" or not content.path.startswith(CONTENT_PATH):
        message = f"{fields.path}.content: expected an https address under {CONTENT_PATH}"
        raise RepresentationError(message)
    with fields.refusals():
        return Attachment(
            id=fields.text("id"),
            filename=fields.text("filename"),
            media_type=fields.text("mimeType"),
            size=fields.integer("size"),
            download=content.path,
        )


def issue(fields: Fields) -> Issue:
    """Read an issue from a search that asked for ``ISSUE_FIELDS``, or from a GET.

    Jira sends a field it was asked for even when it is null, except ``parent``, which
    only an issue with a parent has.
    """
    values = fields.object("fields")
    reporter = values.optional_object("reporter")
    creator = values.optional_object("creator")
    assignee = values.optional_object("assignee")
    parent = values.optional_object("parent", absent=True)
    key = fields.text("key")
    with fields.refusals():
        return Issue(
            id=fields.text("id"),
            title=values.text("summary"),
            author=None if reporter is None else person(reporter),
            created=values.time("created"),
            updated=values.time("updated"),
            url=f"/browse/{key}",
            labels=values.texts("labels"),
            key=key,
            project=values.object("project").text("key"),
            issue_type=values.object("issuetype").text("name"),
            status=values.object("status").text("name"),
            creator=None if creator is None else person(creator),
            assignee=None if assignee is None else person(assignee),
            parent=None if parent is None else parent.text("key"),
        )


def comment(fields: Fields) -> Comment:
    """Read a comment fetched with ``expand=renderedBody``."""
    author = fields.optional_object("author", absent=True)
    with fields.refusals():
        return Comment(
            id=fields.text("id"),
            author=None if author is None else person(author),
            created=fields.time("created"),
            html=fields.text("renderedBody"),
        )


def identity(responses: Mapping[str, object]) -> tuple[str, str]:
    """Read only what names a snapshot's folder: its id and its revision."""
    fields = Fields(responses.get(ISSUE), ISSUE)
    return fields.text("id"), time_revision(fields.object("fields").time("updated"))


def snapshot(responses: Mapping[str, object]) -> Snapshot:
    """Read an issue from the responses that its snapshot keeps.

    An issue without a description has a null one among its rendered fields; the
    rendered fields themselves are always there when they were asked for.
    """
    fields = Fields(responses.get(ISSUE), ISSUE)
    return Snapshot(
        document=issue(fields),
        html=fields.object("renderedFields").optional_text("description") or "",
        attachments=tuple(
            attachment(item) for item in fields.object("fields").objects("attachment")
        ),
        comments=tuple(comment(item) for item in Fields.each(responses.get(COMMENTS), COMMENTS)),
    )


# What to GET, and how a search and a list of comments go on.
PAGE_SIZE = "100"


def search_request(project: str, start: date, end: date) -> Request:
    """GET the issues of a project updated from ``start`` until before ``end``, by date.

    Jira reads these dates in the user's time zone, so a caller widens them and decides
    on each issue's ``updated`` time. The key is quoted, as JQL needs for some keys.
    """
    jql = (
        f'project = "{project}" AND updated >= "{start.isoformat()}"'
        f' AND updated < "{end.isoformat()}" ORDER BY updated DESC'
    )
    return Request(
        path="/rest/api/3/search/jql",
        params={"jql": jql, "fields": ISSUE_FIELDS, "maxResults": PAGE_SIZE},
    )


def search_page(response: Fields, request: Request) -> tuple[list[Fields], Request | None]:
    """Read one page of a search: its issues, and the request for the next page."""
    token = response.optional_text("nextPageToken", absent=True)
    following = None
    if token is not None and not response.flag("isLast"):
        following = Request(path=request.path, params={**request.params, "nextPageToken": token})
    return response.objects("issues"), following


def listed(fields: Fields) -> Listed:
    """Read of a search's entry only what decides a fetch: id and update time."""
    updated = fields.object("fields").time("updated")
    with fields.refusals():
        return Listed(
            type=Issue, id=fields.text("id"), revision=time_revision(updated), updated=updated
        )


def listed_attachments(fields: Fields) -> tuple[Attachment, ...]:
    """Read the attachments that a search's entry names, as ``ISSUE_FIELDS`` asks."""
    return tuple(attachment(item) for item in fields.object("fields").objects("attachment"))


def snapshot_requests(issue: Listed) -> dict[str, tuple[Request, ReadPage | None]]:
    """Name the GETs whose responses make a snapshot, with the paging of comments."""
    return {
        ISSUE: (issue_request(issue.id), None),
        COMMENTS: (comments_request(issue.id), comments_page),
    }


def issue_request(issue_id: str) -> Request:
    """GET an issue with its rendered fields."""
    return Request(path=f"/rest/api/3/issue/{issue_id}", params={"expand": "renderedFields"})


def comments_request(issue_id: str) -> Request:
    """GET the first page of an issue's comments, with their rendered bodies."""
    return Request(
        path=f"/rest/api/3/issue/{issue_id}/comment",
        params={"expand": "renderedBody", "maxResults": PAGE_SIZE, "startAt": "0"},
    )


def comments_page(response: Fields, request: Request) -> tuple[list[Fields], Request | None]:
    """Read one page of comments, and the request for the next page, by ``startAt``."""
    comments = response.objects("comments")
    start = response.integer("startAt") + len(comments)
    following = None
    if comments and start < response.integer("total"):
        following = Request(path=request.path, params={**request.params, "startAt": str(start)})
    return comments, following


def myself_request() -> Request:
    """GET the user whom the session signs in; Jira answers 401 to an expired session."""
    return Request(path="/rest/api/3/myself")


def signed_in(response: Fields) -> bool:
    """Say whether the user answered is someone."""
    return response.optional_text("accountId", absent=True) is not None
