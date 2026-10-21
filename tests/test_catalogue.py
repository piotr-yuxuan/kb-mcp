"""What the listings and users add to a snapshot: names, status, breadcrumbs, front matter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from atlassian_offline_mcp.domain.catalogue import Catalogue, front_matter
from atlassian_offline_mcp.domain.content import (
    BlogPost,
    Folder,
    Issue,
    Page,
    Person,
    RefusedError,
    Space,
)

PARIS = timezone(timedelta(hours=2))
MOMENT = datetime(2026, 10, 20, 23, 52, 41, 371000, tzinfo=PARIS)
FETCHED = datetime(2026, 10, 22, 10, 15, tzinfo=PARIS)
SITE = "https://site.example.invalid"


def page(page_id: str, title: str, parent: str | None, **changes: object) -> Page:
    """Return a page of space 1 under a parent page, or at the top."""
    made = Page(
        id=page_id,
        title=title,
        author=Person("account-1"),
        created=MOMENT,
        updated=MOMENT,
        url=f"/wiki/spaces/MFS/pages/{page_id}",
        space_id="1",
        version=3,
        status="current",
        parent_id=parent,
        parent_type=None if parent is None else "page",
    )
    return replace(made, **changes)


ROOT = page("10", "Root", None)
FOLDER = Folder("20", "A folder", "10", "page")
LEAF = page("30", "Leaf", "20", parent_type="folder")
POST = BlogPost(
    id="40",
    title="News",
    author=None,
    created=MOMENT,
    updated=MOMENT,
    url="/wiki/spaces/MFS/blog/2026/10/20/40/News",
    space_id="1",
    version=1,
    status="current",
)
ISSUE = Issue(
    id="10000",
    title="What are\narchived ideas?",
    author=Person("account-2", "Another\u2028Person"),
    created=MOMENT,
    updated=MOMENT,
    url="/browse/PRB-1",
    labels=("probe",),
    key="PRB-1",
    project="PRB",
    issue_type="Idea",
    status="Parking lot",
    assignee=None,
    parent="PRB-3",
)
CATALOGUE = Catalogue(
    spaces={"1": Space("1", "MFS", "A space")},
    names={"account-1": "A Person"},
    listed={
        ROOT.id: ROOT,
        LEAF.id: page("30", "Leaf, renamed", "20", status="archived", parent_type="folder"),
        POST.id: POST,
    },
    folders={"1": (FOLDER,)},
)


def test_a_name_is_the_display_name_else_the_users_else_the_account_id() -> None:
    """Jira gives names; Confluence names come from the users; else the account id."""
    assert CATALOGUE.name(Person("account-2", "Given")) == "Given"
    assert CATALOGUE.name(Person("account-1")) == "A Person"
    assert CATALOGUE.name(Person("account-9")) == "account-9"
    assert CATALOGUE.name(None) is None


def test_a_listed_page_takes_its_status_from_the_listing() -> None:
    """The listing is fresher than a snapshot; an unlisted page keeps its own status."""
    assert CATALOGUE.status(LEAF) == "archived"
    assert CATALOGUE.status(page("99", "Alone", None, status="draft")) == "draft"


def test_breadcrumbs_climb_pages_and_folders_root_first() -> None:
    """A page's ancestors, a blog post's none, an issue's parent key."""
    assert CATALOGUE.breadcrumb(LEAF) == ("Root", "A folder")
    assert CATALOGUE.breadcrumb(ROOT) == ()
    assert CATALOGUE.breadcrumb(POST) == ()
    assert CATALOGUE.breadcrumb(ISSUE) == ("PRB-3",)


def test_a_breadcrumb_stops_at_an_unlisted_parent_or_a_loop() -> None:
    """A parent missing from the listings, or a loop, ends the walk."""
    looping = Catalogue(
        spaces={},
        names={},
        listed={},
        folders={"1": (Folder("1", "One", "2", "folder"), Folder("2", "Two", "1", "folder"))},
    )
    assert looping.breadcrumb(page("3", "Under a loop", "1")) == ("Two", "One")
    assert looping.breadcrumb(page("3", "Under nothing", "9")) == ()


def test_a_page_front_matter_follows_the_layout_table() -> None:
    """Confluence keys set, Jira keys null, times in UTC, url from the site."""
    matter = front_matter(LEAF, FETCHED, CATALOGUE, SITE)
    assert (matter.source, matter.type, matter.id, matter.key) == ("confluence", "page", "30", None)
    assert (matter.space, matter.project, matter.issue_type) == ("MFS", None, None)
    assert (matter.status, matter.author, matter.assignee) == ("archived", "A Person", None)
    assert (matter.version, matter.revision) == (3, "000003")
    assert matter.created == datetime(2026, 10, 20, 21, 52, 41, 371000, tzinfo=UTC)
    assert matter.fetched_at == datetime(2026, 10, 22, 8, 15, tzinfo=UTC)
    assert matter.url == f"{SITE}/wiki/spaces/MFS/pages/30"
    assert matter.breadcrumb == ("Root", "A folder")
    assert front_matter(LEAF, FETCHED, CATALOGUE, None).url is None


def test_an_issue_front_matter_is_one_line_texts() -> None:
    """Jira keys set, Confluence keys null; line breaks in texts become spaces."""
    matter = front_matter(ISSUE, FETCHED, CATALOGUE, SITE)
    assert (matter.source, matter.type, matter.key, matter.project) == (
        "jira",
        "issue",
        "PRB-1",
        "PRB",
    )
    assert (matter.space, matter.version, matter.issue_type) == (None, None, "Idea")
    assert matter.title == "What are archived ideas?"
    assert matter.author == "Another Person"
    assert matter.breadcrumb == ("PRB-3",)
    assert matter.revision == "20261020T215241.371000Z"


def test_a_page_of_a_space_not_listed_is_refused() -> None:
    """Its folder cannot be named, so its front matter has no space key."""
    other = page("50", "Elsewhere", None, space_id="2")
    with pytest.raises(RefusedError):
        front_matter(other, FETCHED, CATALOGUE, SITE)
