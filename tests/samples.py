"""Responses shaped as the Confluence v2 and Jira v3 REST documentation shows them.

Fields that no adapter reads are left out. Values are made up, except that their shapes
follow what the sandbox site returned on 2026-10-21.
"""

from __future__ import annotations

PAGE_VERSION = 3
ATTACHMENT_SIZE = 7153


def v2_page(**changes: object) -> dict[str, object]:
    """Return GET /wiki/api/v2/pages/{id}?body-format=storage&include-labels=true."""
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


def v2_view(**changes: object) -> dict[str, object]:
    """Return the same GET with body-format=view."""
    view = {"value": "<p>Hello, rendered</p>", "representation": "view"}
    return v2_page(body={"view": view}, **changes)


def v2_attachment(**changes: object) -> dict[str, object]:
    """Return one result of GET /wiki/api/v2/pages/{id}/attachments.

    The sandbox's ``downloadLink`` is the v1 download, relative to /wiki.
    """
    attachment: dict[str, object] = {
        "id": "att196895",
        "title": "probe-complex.png",
        "mediaType": "image/png",
        "fileSize": ATTACHMENT_SIZE,
        "pageId": "196845",
        "downloadLink": "/rest/api/content/196845/child/attachment/att196895/download",
    }
    return {**attachment, **changes}


def v3_issue(**changes: object) -> dict[str, object]:
    """Return GET /rest/api/3/issue/{id}?expand=renderedFields, trimmed to what is read."""
    issue: dict[str, object] = {
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
    return {**issue, **changes}


def v3_comment(**changes: object) -> dict[str, object]:
    """Return one comment of GET /rest/api/3/issue/{id}/comment?expand=renderedBody."""
    comment: dict[str, object] = {
        "id": "10100",
        "author": {"accountId": "account-2"},
        "created": "2026-10-21T08:00:00.000+0000",
        "renderedBody": "<p>Seen.</p>",
    }
    return {**comment, **changes}
