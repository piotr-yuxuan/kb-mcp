"""Reading Confluence v2 and Jira v3 responses, shaped as the REST documentation shows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from atlassian_offline_mcp.adapters import confluence_v2, jira_v3
from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.domain.content import BlogPost, Page, Person
from tests.samples import (
    ATTACHMENT_SIZE,
    PAGE_VERSION,
    v2_attachment,
    v2_page,
    v2_view,
    v3_comment,
    v3_issue,
)


def test_a_page_is_read_with_its_version_labels_and_place() -> None:
    """Every field the mirror needs comes from where the v2 documentation puts it."""
    page = confluence_v2.document(Fields(v2_page(), "page"), Page)
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


def test_a_page_revision_is_its_version_padded_to_six_digits() -> None:
    """Version 3 is stored as 000003, as the data layout says."""
    assert confluence_v2.document(Fields(v2_page(), "page"), Page).revision == "000003"


def test_a_listed_page_without_labels_has_none() -> None:
    """A listing does not include labels; that is no labels, not an error."""
    page = confluence_v2.document(Fields(v2_page(labels=None), "page"), Page)
    assert page.labels == ()


def test_a_blog_post_is_its_own_kind() -> None:
    """A blog post is stored and mirrored apart from pages."""
    post = confluence_v2.document(Fields(v2_page(parentId=None), "post"), BlogPost)
    assert isinstance(post, BlogPost)
    assert not isinstance(post, Page)


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"version": {"createdAt": "2026-10-20T21:52:41Z"}}, "page.version.number"),
        ({"version": {"number": True, "createdAt": "2026-10-20T21:52:41Z"}}, "page.version.number"),
        ({"title": None}, "page.title"),
        ({"createdAt": "2026-10-20T21:27:34"}, "page.createdAt"),
        ({"labels": {"results": "probe"}}, "page.labels.results"),
        ({"labels": {}}, "page.labels.results"),
    ],
)
def test_a_changed_response_is_refused_naming_the_field(
    changes: dict[str, object], path: str
) -> None:
    """A missing field, a wrong type or a time without offset fails at its path."""
    with pytest.raises(RepresentationError, match=f"^{path}: "):
        confluence_v2.document(Fields(v2_page(**changes), "page"), Page)


@pytest.mark.parametrize(
    ("changes", "field"), [({"id": "../196845"}, "id"), ({"spaceId": "1/2"}, "space_id")]
)
def test_a_page_id_that_could_leave_its_folder_is_refused_without_its_value(
    changes: dict[str, str], field: str
) -> None:
    """An id from the site names a folder; the refusal names the field, not the value."""
    with pytest.raises(RepresentationError, match=f"^page: {field}: does not match") as refused:
        confluence_v2.document(Fields(v2_page(**changes), "page"), Page)
    assert next(iter(changes.values())) not in str(refused.value)


@pytest.mark.parametrize(
    ("changes", "field"),
    [({"id": "../10000"}, "id"), ({"key": "../PRB-1"}, "key"), ({"key": "prb-1"}, "key")],
)
def test_an_issue_id_or_key_that_could_leave_its_folder_is_refused(
    changes: dict[str, str], field: str
) -> None:
    """An issue's id names its folder and its key its file in the mirror."""
    with pytest.raises(RepresentationError, match=f"^issue: {field}: does not match"):
        jira_v3.issue(Fields(v3_issue(**changes), "issue"))


def test_a_space_key_that_is_a_path_is_refused() -> None:
    """A space key names a folder of the mirror."""
    space = {"id": "196613", "key": "../MFS", "name": "A space"}
    with pytest.raises(RepresentationError, match=r"^space: key: does not match"):
        confluence_v2.space(Fields(space, "space"))


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"id": "att/1"}, "id"),
        ({"downloadLink": "//elsewhere.example/file"}, "downloadLink"),
        ({"downloadLink": "https://elsewhere.example/file"}, "downloadLink"),
        ({"downloadLink": "/rest\\file"}, "downloadLink"),
    ],
)
def test_an_attachment_that_could_leave_the_site_or_its_folder_is_refused(
    changes: dict[str, str], field: str
) -> None:
    """An attachment's id names a file, and its download stays on the site."""
    with pytest.raises(RepresentationError, match=f"^attachment: {field}: does not match"):
        confluence_v2.attachment(Fields(v2_attachment(**changes), "attachment"))


def test_an_attachment_downloads_from_under_the_wiki() -> None:
    """The v2 download link is relative to /wiki, and the file keeps its name and type."""
    attachment = confluence_v2.attachment(Fields(v2_attachment(), "attachment"))
    download = "/wiki/rest/api/content/196845/child/attachment/att196895/download"
    assert attachment.download == download
    assert (attachment.filename, attachment.media_type, attachment.size) == (
        "probe-complex.png",
        "image/png",
        ATTACHMENT_SIZE,
    )


def test_a_page_snapshot_joins_its_view_and_attachments() -> None:
    """The mirror shows the view body, with the attachments listed beside it."""
    snapshot = confluence_v2.snapshot(
        Page,
        {
            confluence_v2.DOCUMENT: v2_page(),
            confluence_v2.VIEW: v2_view(),
            confluence_v2.ATTACHMENTS: [v2_attachment()],
        },
    )
    assert snapshot.html == "<p>Hello, rendered</p>"
    assert [attachment.id for attachment in snapshot.attachments] == ["att196895"]


@pytest.mark.parametrize("missing", [confluence_v2.VIEW, confluence_v2.ATTACHMENTS])
def test_a_page_snapshot_missing_a_response_is_refused(missing: str) -> None:
    """A snapshot missing a response fails naming that response's file."""
    responses = {
        confluence_v2.DOCUMENT: v2_page(),
        confluence_v2.VIEW: v2_view(),
        confluence_v2.ATTACHMENTS: [],
    }
    del responses[missing]
    with pytest.raises(RepresentationError, match=f"^{missing}: "):
        confluence_v2.snapshot(Page, responses)


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
    snapshot = jira_v3.snapshot({jira_v3.ISSUE: v3_issue(), jira_v3.COMMENTS: [v3_comment()]})
    assert snapshot.html == "<p>An image for the probe.</p>"
    assert [attachment.download for attachment in snapshot.attachments] == [
        "/rest/api/3/attachment/content/10000"
    ]
    assert [(item.id, item.author, item.html) for item in snapshot.comments] == [
        ("10100", Person("account-2"), "<p>Seen.</p>")
    ]


def test_an_issue_without_a_description_has_an_empty_body() -> None:
    """Jira gives a null description among the rendered fields of an issue without one."""
    issue = v3_issue(renderedFields={"description": None})
    assert jira_v3.snapshot({jira_v3.ISSUE: issue, jira_v3.COMMENTS: []}).html == ""


@pytest.mark.parametrize(
    ("responses", "path"),
    [
        ({jira_v3.ISSUE: v3_issue(renderedFields=None), jira_v3.COMMENTS: []}, "issue.json"),
        ({jira_v3.ISSUE: v3_issue()}, "comments.json"),
        (
            {jira_v3.ISSUE: v3_issue(), jira_v3.COMMENTS: [v3_comment(renderedBody=None)]},
            r"comments\.json\[0\]\.renderedBody",
        ),
    ],
)
def test_an_issue_snapshot_missing_a_rendering_is_refused(
    responses: dict[str, object], path: str
) -> None:
    """A rendering that is not there fails, rather than mirroring an empty body."""
    with pytest.raises(RepresentationError, match=f"^{path}"):
        jira_v3.snapshot(responses)
