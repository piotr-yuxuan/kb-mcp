"""Jira Cloud REST v3 responses, read into the domain's types.

What this code knows of the shape of Jira's JSON is here and nowhere else. When the
site changes a response, the fix is in this module, and the raw store can be read
again without fetching anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from atlassian_offline_mcp.adapters.fields import Fields
from atlassian_offline_mcp.domain.content import Attachment, Comment, Issue, Person, Snapshot

if TYPE_CHECKING:
    from collections.abc import Mapping

# The fields that ``issue`` reads; a search that asks for these yields whole issues.
ISSUE_FIELDS = (
    "summary,status,issuetype,project,labels,created,updated,reporter,assignee,parent,attachment"
)

# The responses that a snapshot of an issue keeps, by file name.
# GET /rest/api/3/issue/{id}?expand=renderedFields
ISSUE = "issue.json"
# The comments of every page of GET /rest/api/3/issue/{id}/comment?expand=renderedBody.
COMMENTS = "comments.json"


def person(fields: Fields) -> Person:
    """Read a user; the email address, when there is one, is left behind."""
    return Person(fields.text("accountId"), fields.optional_text("displayName"))


def attachment(fields: Fields) -> Attachment:
    """Read an attachment; its file is the path of its ``content`` address."""
    return Attachment(
        fields.text("id"),
        fields.text("filename"),
        fields.text("mimeType"),
        fields.integer("size"),
        urlsplit(fields.text("content")).path,
    )


def issue(fields: Fields) -> Issue:
    """Read an issue from a search that asked for ``ISSUE_FIELDS``, or from a GET."""
    values = fields.object("fields")
    reporter = values.optional_object("reporter")
    assignee = values.optional_object("assignee")
    parent = values.optional_object("parent")
    key = fields.text("key")
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
        assignee=None if assignee is None else person(assignee),
        parent=None if parent is None else parent.text("key"),
    )


def comment(fields: Fields) -> Comment:
    """Read a comment fetched with ``expand=renderedBody``."""
    author = fields.optional_object("author")
    return Comment(
        fields.text("id"),
        None if author is None else person(author),
        fields.time("created"),
        fields.optional_text("renderedBody") or "",
    )


def snapshot(responses: Mapping[str, object]) -> Snapshot:
    """Read an issue from the responses that its snapshot keeps."""
    fields = Fields(responses.get(ISSUE), ISSUE)
    rendered = fields.optional_object("renderedFields")
    return Snapshot(
        issue(fields),
        (rendered.optional_text("description") if rendered else None) or "",
        tuple(attachment(item) for item in fields.object("fields").objects("attachment")),
        tuple(comment(item) for item in Fields.each(responses.get(COMMENTS), COMMENTS)),
    )
