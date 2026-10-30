"""What the listings and users add to a snapshot: names, status, breadcrumbs, front matter."""

from __future__ import annotations

from copy import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from kb_mcp.kernel.names import RefusedError
from kb_mcp.mirror.domain.mirror import PersonRole
from kb_mcp.sources.atlassian.fetch.domain.content import (
    BlogPost,
    Comment,
    Folder,
    Issue,
    Page,
    Person,
    Space,
)
from kb_mcp.sources.atlassian.prepare.domain.catalogue import Catalogue, front_matter

PARIS = timezone(timedelta(hours=2))
MOMENT = datetime(2026, 10, 20, 23, 52, 41, 371000, tzinfo=PARIS)
FETCHED = datetime(2026, 10, 22, 10, 15, tzinfo=PARIS)
SITE = "https://site.example.invalid"


def page(page_id: str, title: str, parent: str | None, **changes: object) -> Page:
    """Return a page of space 1 under a parent page, or at the top."""
    made = Page(
        id=page_id,
        title=title,
        author=Person(account_id="account-1"),
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
FOLDER = Folder(id="20", title="A folder", parent_id="10", parent_type="page")
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
    author=Person(account_id="account-2", display_name="Another\u2028Person"),
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
    spaces={"1": Space(id="1", key="MFS", name="A space")},
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
    assert CATALOGUE.name(Person(account_id="account-2", display_name="Given")) == "Given"
    assert CATALOGUE.name(Person(account_id="account-1")) == "A Person"
    assert CATALOGUE.name(Person(account_id="account-9")) == "account-9"
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
        folders={
            "1": (
                Folder(id="1", title="One", parent_id="2", parent_type="folder"),
                Folder(id="2", title="Two", parent_id="1", parent_type="folder"),
            )
        },
    )
    assert looping.breadcrumb(page("3", "Under a loop", "1")) == ("Two", "One")
    assert looping.breadcrumb(page("3", "Under nothing", "9")) == ()


def test_a_page_front_matter_follows_the_layout_table() -> None:
    """Confluence keys set, Jira keys null, times in UTC, url from the site."""
    matter = front_matter(LEAF, (), FETCHED, CATALOGUE, SITE)
    assert (matter.source, matter.type, matter.id, matter.key) == ("confluence", "page", "30", None)
    assert (matter.space, matter.project, matter.issue_type) == ("MFS", None, None)
    assert (matter.status, matter.author, matter.assignee) == ("archived", "A Person", None)
    assert matter.people == (PersonRole(role="author", name="A Person", account="account-1"),)
    assert (matter.version, matter.revision) == (3, "000003")
    assert matter.created == datetime(2026, 10, 20, 21, 52, 41, 371000, tzinfo=UTC)
    assert matter.fetched_at == datetime(2026, 10, 22, 8, 15, tzinfo=UTC)
    assert matter.url == f"{SITE}/wiki/spaces/MFS/pages/30"
    assert matter.breadcrumb == ("Root", "A folder")
    assert front_matter(LEAF, (), FETCHED, CATALOGUE, None).url is None


def test_an_issue_front_matter_is_one_line_texts() -> None:
    """Jira keys set, Confluence keys null; line breaks in texts become spaces."""
    matter = front_matter(ISSUE, (), FETCHED, CATALOGUE, SITE)
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
        front_matter(other, (), FETCHED, CATALOGUE, SITE)


ANOTHER = Person(account_id="account-2", display_name="Another Person")
# Filed by Another Person for A Person, assigned to someone whom nothing names.
FILED = replace(
    ISSUE,
    author=Person(account_id="account-1", display_name="A Person"),
    creator=ANOTHER,
    assignee=Person(account_id="account-3"),
)
# Three comments by two people, as Jira gives them: by creation time. A Person's is
# named by the users.
COMMENTS = (
    Comment(id="1", author=ANOTHER, created=datetime(2026, 10, 21, 10, tzinfo=PARIS), html=""),
    Comment(
        id="2",
        author=Person(account_id="account-1"),
        created=datetime(2026, 10, 21, 9, 30, tzinfo=UTC),
        html="",
    ),
    Comment(id="3", author=ANOTHER, created=datetime(2026, 10, 22, 8, tzinfo=UTC), html=""),
)


def test_an_issue_names_its_people_in_the_order_of_the_roles() -> None:
    """Author, creator, assignee, then each commenter once, their times in UTC, ascending."""
    matter = front_matter(FILED, COMMENTS, FETCHED, CATALOGUE, SITE)
    assert matter.people == (
        PersonRole(role="author", name="A Person", account="account-1"),
        PersonRole(role="creator", name="Another Person", account="account-2"),
        PersonRole(role="assignee", name="account-3", account="account-3"),
        PersonRole(
            role="commenter",
            name="Another Person",
            account="account-2",
            at=(datetime(2026, 10, 21, 8, tzinfo=UTC), datetime(2026, 10, 22, 8, tzinfo=UTC)),
        ),
        PersonRole(
            role="commenter",
            name="A Person",
            account="account-1",
            at=(datetime(2026, 10, 21, 9, 30, tzinfo=UTC),),
        ),
    )
    # The values that the keys author and assignee held before 041.
    assert (matter.author, matter.assignee) == ("A Person", "account-3")


def test_commenters_come_by_their_first_comment_in_whatever_order_given() -> None:
    """Comments given newest first name the same commenters, in the same order."""
    given = front_matter(FILED, COMMENTS, FETCHED, CATALOGUE, SITE)
    reversed_ = front_matter(FILED, reversed(COMMENTS), FETCHED, CATALOGUE, SITE)
    assert reversed_.people == given.people


def test_a_commenter_is_one_name_with_one_account() -> None:
    """Namesakes of two accounts are two commenters; one account under two names, two."""
    namesake = Person(account_id="account-4", display_name="Another Person")
    renamed = Person(account_id="account-2", display_name="A Person")
    comments = (
        Comment(id="5", author=ANOTHER, created=datetime(2026, 10, 21, 8, tzinfo=UTC), html=""),
        Comment(id="6", author=namesake, created=datetime(2026, 10, 21, 9, tzinfo=UTC), html=""),
        Comment(id="7", author=renamed, created=datetime(2026, 10, 21, 10, tzinfo=UTC), html=""),
        Comment(id="8", author=namesake, created=datetime(2026, 10, 21, 11, tzinfo=UTC), html=""),
    )
    matter = front_matter(FILED, comments, FETCHED, CATALOGUE, SITE)
    commenters = [person for person in matter.people if person.role == "commenter"]
    assert [(person.name, person.account, len(person.at)) for person in commenters] == [
        ("Another Person", "account-2", 1),
        ("Another Person", "account-4", 2),
        ("A Person", "account-2", 1),
    ]


def test_a_comment_without_an_author_names_nobody() -> None:
    """Jira leaves out the author of an anonymous comment; no commenter stands for it."""
    anonymous = Comment(id="4", author=None, created=MOMENT, html="")
    matter = front_matter(FILED, (anonymous,), FETCHED, CATALOGUE, SITE)
    assert [person.role for person in matter.people] == ["author", "creator", "assignee"]
