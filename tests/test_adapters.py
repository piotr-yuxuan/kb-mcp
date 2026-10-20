"""Reading Confluence v2 and Jira v3 responses, shaped as the REST documentation shows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from atlassian_offline_mcp.adapters import confluence_v2, jira_v3
from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.domain.content import BlogPost, Page, Person

PAGE_VERSION = 3
ATTACHMENT_SIZE = 7153


def v2_page(**changes: object) -> dict[str, object]:
    """Return a v2 page as GET /wiki/api/v2/pages/{id}?include-labels=true returns it."""
    page: dict[str, object] = {
        "id": "196845",
        "status": "current",
        "title": "Probe complex",
        "spaceId": "196613",
        "parentId": "196725",
        "parentType": "page",
        "authorId": "account-1",
        "createdAt": "2026-10-20T21:27:34.188Z",
        "version": {"number": PAGE_VERSION, "createdAt": "2026-10-20T21:52:41.371Z"},
        "labels": {"results": [{"id": "1", "name": "probe", "prefix": "global"}]},
        "body": {"storage": {"value": "<p>Hello</p>", "representation": "storage"}},
        "_links": {"webui": "/spaces/MFS/pages/196845/Probe+complex"},
    }
    return {**page, **changes}


def v2_attachment() -> dict[str, object]:
    """Return one result of GET /wiki/api/v2/pages/{id}/attachments."""
    return {
        "id": "att196895",
        "title": "probe-complex.png",
        "mediaType": "image/png",
        "fileSize": ATTACHMENT_SIZE,
        "pageId": "196845",
        "downloadLink": "/rest/api/content/196845/child/attachment/att196895/download",
    }


def v3_issue() -> dict[str, object]:
    """Return GET /rest/api/3/issue/{id}?expand=renderedFields, trimmed to what is read."""
    return {
        "id": "10000",
        "key": "PRB-1",
        "fields": {
            "summary": "What are archived ideas?",
            "status": {"name": "Parking lot"},
            "issuetype": {"name": "Idea"},
            "project": {"id": "10000", "key": "PRB"},
            "labels": ["probe"],
            "created": "2026-10-20T22:33:32.949+0100",
            "updated": "2026-10-20T22:37:58.027+0100",
            "reporter": {
                "accountId": "account-1",
                "displayName": "A Person",
                "emailAddress": "someone@example.invalid",
            },
            "assignee": None,
            "parent": {"id": "10002", "key": "PRB-3"},
            "attachment": [
                {
                    "id": "10000",
                    "filename": "probe-issue.png",
                    "mimeType": "image/png",
                    "size": 4956,
                    "content": "https://site.example.invalid/rest/api/3/attachment/content/10000",
                }
            ],
        },
        "renderedFields": {"description": "<p>An image for the probe.</p>"},
    }


def test_a_page_is_read_with_its_version_labels_and_place() -> None:
    """Every field the mirror needs comes from where the v2 documentation puts it."""
    page = confluence_v2.document(Fields(v2_page(), "page"), "pages")
    assert isinstance(page, Page)
    assert (page.id, page.title, page.space_id, page.parent_id) == (
        "196845",
        "Probe complex",
        "196613",
        "196725",
    )
    assert page.version == PAGE_VERSION
    assert page.updated == datetime(2026, 10, 20, 21, 52, 41, 371000, tzinfo=UTC)
    assert page.labels == ("probe",)
    assert page.author == Person("account-1")
    assert page.url == "/wiki/spaces/MFS/pages/196845/Probe+complex"


def test_a_listed_page_without_labels_has_none() -> None:
    """A listing does not include labels; that is no labels, not an error."""
    page = confluence_v2.document(Fields(v2_page(labels=None), "page"), "pages")
    assert page.labels == ()


def test_a_blog_post_is_its_own_kind() -> None:
    """A blog post is stored and mirrored apart from pages."""
    post = confluence_v2.document(Fields(v2_page(parentId=None), "post"), "blogposts")
    assert isinstance(post, BlogPost)
    assert not isinstance(post, Page)


def test_revisions_order_as_text_in_the_order_of_versions() -> None:
    """Version 10 comes after version 9 when folders are sorted by name."""

    def revision(number: int) -> str:
        changed = v2_page(version={"number": number, "createdAt": "2026-10-20T21:52:41Z"})
        return confluence_v2.document(Fields(changed, "page"), "pages").revision

    assert sorted([revision(10), revision(9), revision(100)]) == [
        revision(9),
        revision(10),
        revision(100),
    ]


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"version": {"createdAt": "2026-10-20T21:52:41Z"}}, "page.version.number"),
        ({"version": {"number": True, "createdAt": "2026-10-20T21:52:41Z"}}, "page.version.number"),
        ({"title": None}, "page.title"),
        ({"createdAt": "2026-10-20T21:27:34"}, "page.createdAt"),
        ({"labels": {"results": "probe"}}, "page.labels.results"),
    ],
)
def test_a_changed_response_is_refused_naming_the_field(
    changes: dict[str, object], path: str
) -> None:
    """A missing field, a wrong type or a time without offset fails at its path."""
    with pytest.raises(RepresentationError, match=f"^{path}: "):
        confluence_v2.document(Fields(v2_page(**changes), "page"), "pages")


def test_an_id_that_could_leave_its_folder_is_refused() -> None:
    """An id from the site names a folder, so it cannot hold a path."""
    with pytest.raises(ValueError, match="not an id"):
        confluence_v2.document(Fields(v2_page(id="../196845"), "page"), "pages")


def test_an_attachment_downloads_from_under_the_wiki() -> None:
    """The v2 download link is relative to /wiki, and the file keeps its name and type."""
    attachment = confluence_v2.attachment(Fields(v2_attachment(), "attachment"))
    assert (
        attachment.download == "/wiki/rest/api/content/196845/child/attachment/att196895/download"
    )
    assert (attachment.filename, attachment.media_type, attachment.size) == (
        "probe-complex.png",
        "image/png",
        ATTACHMENT_SIZE,
    )


def test_a_page_snapshot_joins_its_view_and_attachments() -> None:
    """The mirror shows the view body, with the attachments listed beside it."""
    view = v2_page(body={"view": {"value": "<p>Hello, rendered</p>", "representation": "view"}})
    snapshot = confluence_v2.snapshot(
        "pages",
        {
            confluence_v2.DOCUMENT: v2_page(),
            confluence_v2.VIEW: view,
            confluence_v2.ATTACHMENTS: [v2_attachment()],
        },
    )
    assert snapshot.html == "<p>Hello, rendered</p>"
    assert [attachment.id for attachment in snapshot.attachments] == ["att196895"]


def test_a_snapshot_without_its_view_is_refused() -> None:
    """A snapshot missing a response fails naming that response's file."""
    with pytest.raises(RepresentationError, match=r"^view\.json: "):
        confluence_v2.snapshot("pages", {confluence_v2.DOCUMENT: v2_page()})


def test_an_issue_is_read_with_its_offset_times_and_people() -> None:
    """Jira times keep their offset; people keep their id and name, not their email."""
    issue = jira_v3.issue(Fields(v3_issue(), "issue"))
    assert (issue.id, issue.key, issue.project, issue.parent) == ("10000", "PRB-1", "PRB", "PRB-3")
    assert (issue.issue_type, issue.status, issue.labels) == ("Idea", "Parking lot", ("probe",))
    assert issue.updated == datetime(
        2026, 10, 20, 22, 37, 58, 27000, tzinfo=timezone(timedelta(hours=1))
    )
    assert issue.author == Person("account-1", "A Person")
    assert issue.assignee is None
    assert issue.url == "/browse/PRB-1"


def test_an_issue_revision_is_its_update_time_in_utc() -> None:
    """An issue's revision is its update time, so a later update sorts later."""
    assert jira_v3.issue(Fields(v3_issue(), "issue")).revision == "20261020T213758.027000Z"


def test_an_issue_snapshot_has_its_rendered_body_attachments_and_comments() -> None:
    """Attachments download by the path of their content address, on the site."""
    comment = {
        "id": "10100",
        "author": {"accountId": "account-2"},
        "created": "2026-10-21T08:00:00.000+0000",
        "renderedBody": "<p>Seen.</p>",
    }
    snapshot = jira_v3.snapshot({jira_v3.ISSUE: v3_issue(), jira_v3.COMMENTS: [comment]})
    assert snapshot.html == "<p>An image for the probe.</p>"
    assert [attachment.download for attachment in snapshot.attachments] == [
        "/rest/api/3/attachment/content/10000"
    ]
    assert [(item.id, item.author, item.html) for item in snapshot.comments] == [
        ("10100", Person("account-2"), "<p>Seen.</p>")
    ]
