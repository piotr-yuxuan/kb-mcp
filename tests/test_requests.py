"""What the adapters ask the site for, and how they follow a paged listing."""

from __future__ import annotations

from datetime import date

import httpx

from kb_mcp.kernel.fields import Fields
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.http import Request
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Page
from tests.samples import v2_page

NEXT = "/wiki/api/v2/spaces/196613/pages?limit=250&cursor=abc"


def url(request: Request) -> str:
    """Return the URL that httpx would ask for, on any site."""
    return str(httpx.URL(request.path, params=request.params))


def test_a_space_is_found_by_its_key() -> None:
    """GET /wiki/api/v2/spaces?keys=KEY, as the v2 documentation names it."""
    assert url(confluence_v2.space_request("MFS")) == "/wiki/api/v2/spaces?keys=MFS"


def test_a_space_lists_its_pages_with_archived_ones_and_its_blog_posts() -> None:
    """Pages include archived ones; listings ask for the largest page the API allows."""
    pages = confluence_v2.listing_request("196613", Page)
    posts = confluence_v2.listing_request("196613", BlogPost)
    assert url(pages) == "/wiki/api/v2/spaces/196613/pages?limit=250&status=current%2Carchived"
    assert url(posts) == "/wiki/api/v2/spaces/196613/blogposts?limit=250&status=current"


def test_both_bodies_are_asked_for_at_the_listed_version() -> None:
    """The storage body comes with labels; both GETs name the same version."""
    page = confluence_v2.listed(Fields(v2_page(), "page"), Page)
    assert url(confluence_v2.document_request(page, "storage")) == (
        "/wiki/api/v2/pages/196845?body-format=storage&version=3&include-labels=true"
    )
    assert url(confluence_v2.document_request(page, "view")) == (
        "/wiki/api/v2/pages/196845?body-format=view&version=3"
    )


def test_users_are_asked_for_by_repeated_account_ids() -> None:
    """The v1 bulk GET takes one accountId parameter per user."""
    request = confluence_v2.users_request(["a-1", "a-2"])
    assert url(request) == "/wiki/rest/api/user/bulk?accountId=a-1&accountId=a-2&limit=50"


def test_a_v2_listing_follows_its_next_link() -> None:
    """The next page is the path in _links.next, query included; none on the last page."""
    first = Fields({"results": [{"id": "1"}], "_links": {"next": NEXT}}, "response")
    results, following = confluence_v2.listing_page(first, Request(path="/wiki/x"))
    assert [item.text("id") for item in results] == ["1"]
    assert following == Request(path=NEXT)
    last = Fields({"results": [], "_links": {"base": "https://site/wiki"}}, "response")
    assert confluence_v2.listing_page(last, Request(path="/wiki/x"))[1] is None


def test_an_anonymous_user_is_not_signed_in() -> None:
    """An expired session reads Confluence as anonymous, with no account id."""
    assert confluence_v2.signed_in(Fields({"type": "known", "accountId": "a-1"}, "user"))
    assert not confluence_v2.signed_in(Fields({"type": "anonymous"}, "user"))


def test_a_search_names_the_project_quoted_and_the_dates() -> None:
    """JQL with the quoted key and the dates, asking for the fields the adapter reads."""
    request = jira_v3.search_request("PRB", date(2026, 10, 14), date(2026, 10, 23))
    assert request.path == "/rest/api/3/search/jql"
    assert request.params["jql"] == (
        'project = "PRB" AND updated >= "2026-10-14" AND updated < "2026-10-23"'
        " ORDER BY updated DESC"
    )
    assert request.params["fields"] == jira_v3.ISSUE_FIELDS


def test_a_search_follows_its_page_token_until_the_last_page() -> None:
    """The next page repeats the search with nextPageToken; isLast ends it."""
    request = jira_v3.search_request("PRB", date(2026, 10, 14), date(2026, 10, 23))
    page = Fields({"issues": [], "nextPageToken": "t1", "isLast": False}, "search")
    _, following = jira_v3.search_page(page, request)
    assert following is not None
    assert following.params == {**request.params, "nextPageToken": "t1"}
    last = Fields({"issues": [], "isLast": True}, "search")
    assert jira_v3.search_page(last, request)[1] is None


def test_comments_follow_start_at_until_the_total() -> None:
    """Comments page by startAt; a page that reaches the total, or is empty, is the last."""
    request = jira_v3.comments_request("10000")
    page = Fields({"comments": [{"id": "1"}, {"id": "2"}], "startAt": 0, "total": 3}, "c")
    _, following = jira_v3.comments_page(page, request)
    assert following is not None
    assert following.params["startAt"] == "2"
    last = Fields({"comments": [{"id": "3"}], "startAt": 2, "total": 3}, "c")
    assert jira_v3.comments_page(last, request)[1] is None
    empty = Fields({"comments": [], "startAt": 2, "total": 9}, "c")
    assert jira_v3.comments_page(empty, request)[1] is None
