"""The mirror end to end: a raw store built from documented responses, mirrored to files.

The expectations come from the "Markdown mirror" section of the data layout: the paths,
the front matter's keys and values, the body's sections, the assets, the trees, and a
run that changes nothing writing nothing.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from kb_mcp.mirror.adapters.markdown import load
from kb_mcp.mirror.adapters.mirror_files import sync
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocFailedError
from kb_mcp.mirror.domain.mirror import FrontMatter, PersonRole
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.worklog.prepare.adapters.owned import worklog_owned
from tests.mirrors import mirrored
from tests.samples import (
    v1_user,
    v2_attachment,
    v2_folder,
    v2_page,
    v2_space,
    v3_comment,
    v3_issue,
)
from tests.test_pruning import events_named
from tests.test_worklog_mirror import Counting

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from kb_mcp.sources.atlassian.prepare.app.prepare import Outcome

SITE = "https://site.example.invalid"
FETCHED = datetime(2026, 10, 22, 8, 15, tzinfo=UTC)
IMAGE = b"\x89PNG an image"
OTHER_IMAGE = b"\x89PNG another image"
SPACE_ID = "196613"
WORDS = "Words of the leaf page."
# Home, Leaf, the blog post and the issue.
DOCUMENTS = 4
# A conversion for each document's file, and one for the space's tree.
CONVERSIONS = DOCUMENTS + 1


def listing_page(
    page_id: str, title: str, parent: str | None, parent_type: str | None, **changes: object
) -> dict[str, object]:
    """Return one entry of a space's page listing: no body, no labels."""
    entry = v2_page(
        id=page_id,
        title=title,
        parentId=parent,
        parentType=parent_type,
        version={"number": 1, "createdAt": "2026-10-20T21:52:41Z"},
        _links={"webui": f"/spaces/MFS/pages/{page_id}/{title.replace(' ', '+')}"},
        **changes,
    )
    del entry["labels"], entry["body"]
    return entry


def page_responses(
    page_id: str,
    title: str,
    version: int,
    html: str,
    attachments: list[dict[str, object]],
    **changes: object,
) -> dict[str, object]:
    """Return a page's snapshot responses at a version, with its view and attachments."""
    stamp = {"number": version, "createdAt": "2026-10-20T21:52:41Z"}
    webui = {"webui": f"/spaces/MFS/pages/{page_id}/{title.replace(' ', '+')}"}
    view = {"value": html, "representation": "view"}
    return {
        confluence_v2.DOCUMENT: v2_page(
            id=page_id, title=title, version=stamp, _links=webui, **changes
        ),
        confluence_v2.VIEW: v2_page(id=page_id, version=stamp, body={"view": view}),
        confluence_v2.ATTACHMENTS: attachments,
    }


def leaf_html() -> str:
    """Return the leaf page's view: its words, its image, links to an issue and a post."""
    return (
        f"<p>{WORDS}</p>"
        '<p><span class="confluence-embedded-file-wrapper"><img class="confluence-embedded-image"'
        ' src="https://site.example.invalid/wiki/download/thumbnails/300/leaf.png?version=1"'
        ' data-linked-resource-id="400" data-linked-resource-type="attachment"'
        ' data-linked-resource-default-alias="leaf.png" data-linked-resource-container-id="300">'
        "</span></p>"
        '<p>See <a href="https://site.example.invalid/browse/PRB-1">PRB-1</a> and'
        ' <a href="/wiki/spaces/MFS/blog/2026/10/20/600/News">the news</a>.</p>'
    )


@dataclass
class Sandbox:
    """A raw store under a scratch data directory, and the mirror beside it."""

    data: Path

    @cached_property
    def store(self) -> RawStore:
        """The raw store, one object, so that its lock is held where it writes."""
        return RawStore(self.data / "raw")

    @property
    def docs(self) -> Path:
        """The mirror."""
        return self.data / "docs"

    def run(self, site: str | None = SITE, markdown: Callable[[str], str] | None = None) -> Outcome:
        """Mirror the store, with pandoc unless another writer is given, through the cache."""
        return mirrored(self.store, self.docs, site, markdown or Pandoc.find().markdown)

    def files(self) -> dict[str, bytes]:
        """Return every file of the mirror, by its path within ``docs``."""
        return {
            path.relative_to(self.docs).as_posix(): path.read_bytes()
            for path in sorted(self.docs.rglob("*"))
            if path.is_file()
        }

    def text(self, relative: str) -> str:
        """Read one file of the mirror."""
        return (self.docs / relative).read_text("utf-8")


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    """Give a store with a space, its tree, a blog post, an issue and their files.

    The tree: Home (page 100) holds a folder (200), which holds Leaf (300); Home also
    holds a page listed but never downloaded (500). Leaf has a downloaded image, the
    blog post (600) the same file, the issue PRB-1 one file downloaded and one not, and
    two comments, one without an author.
    """
    sandbox = Sandbox(tmp_path / "data")
    store = sandbox.store
    with store.writing():
        image = store.put_blob(IMAGE)
        issue_image = store.put_blob(OTHER_IMAGE)
        store.put_space(v2_space(id=SPACE_ID), LISTED, [POST_LISTED], [FOLDER])
        store.put_users([v1_user(accountId="account-1", displayName="A Person")])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home page.</p>", []), FETCHED, {})
        leaf = [v2_attachment(id="att400", title="leaf.png", pageId="300")]
        store.put(
            Page, page_responses("300", "Leaf", 2, leaf_html(), leaf), FETCHED, {"att400": image}
        )
        store.put(BlogPost, post_responses("<p>News.</p>"), FETCHED, {"att700": image})
        store.put(
            Issue, issue_responses("What are archived ideas?"), FETCHED, {"10000": issue_image}
        )
    return sandbox


LISTED = [
    listing_page("100", "Home", None, None),
    listing_page("300", "Leaf", "200", "folder", status="archived"),
    listing_page("500", "Listed only", "100", "page"),
]
POST_URL = "/spaces/MFS/blog/2026/10/20/600/News"
POST_LISTED = v2_page(id="600", title="News", parentId=None, _links={"webui": POST_URL})
FOLDER = v2_folder(id="200", title="Plans", parentId="100", parentType="page")


def post_responses(html: str, version: int = 1) -> dict[str, object]:
    """Return the blog post's snapshot responses at a version, with one attachment."""
    responses = page_responses("600", "News", version, html, [v2_attachment(id="att700")])
    stamp = {"number": version, "createdAt": "2026-10-20T21:52:41Z"}
    responses[confluence_v2.DOCUMENT] = v2_page(
        id="600", title="News", version=stamp, _links={"webui": POST_URL}
    )
    return responses


def issue_responses(
    summary: str, updated: str = "2026-10-20T22:37:58.027+0100"
) -> dict[str, object]:
    """Return PRB-1's responses: two files, one not downloaded, and two comments."""
    fields = v3_issue()["fields"]
    assert isinstance(fields, dict)
    downloaded = fields["attachment"][0]
    fields.update(
        summary=summary,
        updated=updated,
        attachment=[downloaded, {**downloaded, "id": "10001", "filename": "x.pdf"}],
    )
    description = '<p>An image.</p><p><img src="/rest/api/3/attachment/content/10000"></p>'
    anonymous = v3_comment(id="10101")
    del anonymous["author"]
    return {
        jira_v3.ISSUE: v3_issue(fields=fields, renderedFields={"description": description}),
        jira_v3.COMMENTS: [v3_comment(), anonymous],
    }


def digest(data: bytes) -> str:
    """Return the SHA-256 that names a file."""
    return hashlib.sha256(data).hexdigest()


def test_the_mirror_writes_exactly_the_layouts_paths(sandbox: Sandbox) -> None:
    """Pages, the blog post, the issue, the tree and one asset per distinct file."""
    outcome = sandbox.run()
    assert outcome.problems == ()
    assert outcome.documents == DOCUMENTS
    assert set(sandbox.files()) == {
        "confluence/MFS/100-home.md",
        "confluence/MFS/300-leaf.md",
        "confluence/MFS/blog/600-news.md",
        "confluence/MFS/_tree.md",
        "jira/PRB/PRB-1.md",
        f"assets/{digest(IMAGE)}.png",
        f"assets/{digest(OTHER_IMAGE)}.png",
    }
    assert (sandbox.docs / "assets" / f"{digest(IMAGE)}.png").read_bytes() == IMAGE


def test_each_front_matter_follows_the_layouts_table(sandbox: Sandbox) -> None:
    """Every key, in the layout's order, with the value its row says."""
    sandbox.run()
    leaf, _ = load(sandbox.text("confluence/MFS/300-leaf.md"), "leaf")
    assert leaf == FrontMatter(
        source="confluence",
        type="page",
        id="300",
        key=None,
        title="Leaf",
        space="MFS",
        project=None,
        status="archived",
        issue_type=None,
        labels=("probe",),
        people=(PersonRole(role="author", name="A Person", account="account-1"),),
        links=(),
        created=datetime(2026, 10, 20, 21, 27, 34, tzinfo=UTC),
        updated=datetime(2026, 10, 20, 21, 52, 41, tzinfo=UTC),
        version=2,
        revision="000002",
        url=f"{SITE}/wiki/spaces/MFS/pages/300/Leaf",
        breadcrumb=("Home", "Plans"),
        fetched_at=FETCHED,
    )
    post, _ = load(sandbox.text("confluence/MFS/blog/600-news.md"), "post")
    assert (post.type, post.breadcrumb, post.url) == ("blogpost", (), f"{SITE}/wiki{POST_URL}")
    issue, _ = load(sandbox.text("jira/PRB/PRB-1.md"), "issue")
    assert issue == FrontMatter(
        source="jira",
        type="issue",
        id="10000",
        key="PRB-1",
        title="What are archived ideas?",
        space=None,
        project="PRB",
        status="Parking lot",
        issue_type="Idea",
        labels=("probe",),
        # The comment without an author names nobody.
        people=(
            PersonRole(role="author", name="A Person", account="account-1"),
            PersonRole(role="creator", name="Another Person", account="account-2"),
            PersonRole(
                role="commenter",
                name="Another Person",
                account="account-2",
                at=(datetime(2026, 10, 21, 8, tzinfo=UTC),),
            ),
        ),
        links=(),
        created=datetime(2026, 10, 20, 21, 33, 32, tzinfo=UTC),
        updated=datetime(2026, 10, 20, 21, 37, 58, tzinfo=UTC),
        version=None,
        revision="20261020T213758.027000Z",
        url=f"{SITE}/browse/PRB-1",
        breadcrumb=("PRB-3",),
        fetched_at=FETCHED,
    )


def test_without_a_site_no_address_is_absolute(sandbox: Sandbox) -> None:
    """The url is null, and links to the site stay site paths."""
    sandbox.run(site=None)
    leaf, _ = load(sandbox.text("confluence/MFS/300-leaf.md"), "leaf")
    assert leaf.url is None


def test_each_body_has_the_layouts_sections(sandbox: Sandbox) -> None:
    """Title, body, attachments, then for an issue its comments, each under its heading."""
    sandbox.run()
    _, leaf = load(sandbox.text("confluence/MFS/300-leaf.md"), "leaf")
    image = f"../../assets/{digest(IMAGE)}.png"
    assert leaf == (
        f"# Leaf\n\n{WORDS}\n\n![leaf.png]({image})\n\n"
        "See [PRB-1](../../jira/PRB/PRB-1.md) and [the news](blog/600-news.md).\n\n"
        f"## Attachments\n\n- [leaf.png]({image})\n"
    )
    _, home = load(sandbox.text("confluence/MFS/100-home.md"), "home")
    assert home == "# Home\n\nHome page.\n\n## Attachments\n\nNone.\n"
    _, post = load(sandbox.text("confluence/MFS/blog/600-news.md"), "post")
    assert f"- [probe-complex.png](../../../assets/{digest(IMAGE)}.png)" in post
    _, issue = load(sandbox.text("jira/PRB/PRB-1.md"), "issue")
    issue_image = f"../../assets/{digest(OTHER_IMAGE)}.png"
    assert issue == (
        f"# What are archived ideas?\n\nAn image.\n\n![image]({issue_image})\n\n"
        f"## Attachments\n\n- [probe-issue.png]({issue_image})\n- x.pdf (not downloaded)\n\n"
        "## Comments\n\n### Another Person, 2026-10-21T08:00:00Z\n\nSeen.\n\n"
        "### unknown author, 2026-10-21T08:00:00Z\n\nSeen.\n"
    )


def test_the_tree_nests_pages_and_folders(sandbox: Sandbox) -> None:
    """Siblings by title; a page without a body is named as not yet mirrored."""
    sandbox.run()
    assert sandbox.text("confluence/MFS/_tree.md") == (
        "# A space (MFS)\n\n"
        "- [Home](100-home.md)\n"
        "  - Listed only (not yet mirrored)\n"
        "  - Plans\n"
        "    - [Leaf](300-leaf.md)\n"
    )


def test_a_second_run_writes_nothing_and_a_rebuild_gives_the_same_bytes(
    sandbox: Sandbox,
) -> None:
    """No file is written again, no time changes; deleting docs/ rebuilds it exactly."""
    sandbox.run()
    files = sandbox.files()
    times = {path: path.stat().st_mtime_ns for path in sandbox.docs.rglob("*")}
    outcome = sandbox.run()
    assert (outcome.changes.written, outcome.changes.removed) == (0, 0)
    assert outcome.changes.unchanged == len(files)
    assert {path: path.stat().st_mtime_ns for path in sandbox.docs.rglob("*")} == times
    shutil.rmtree(sandbox.docs)
    sandbox.run()
    assert sandbox.files() == files


def test_a_second_run_with_nothing_changed_runs_pandoc_on_nothing(sandbox: Sandbox) -> None:
    """Plan 039, criterion 5: each conversion of the first run is reused, no file written."""
    pandoc = Counting(path=Pandoc.find().path)
    first = sandbox.run(markdown=pandoc.markdown)
    assert (first.converted, first.reused, len(pandoc.runs)) == (CONVERSIONS, 0, CONVERSIONS)
    pandoc.runs.clear()
    with capture_logs() as events:
        second = sandbox.run(markdown=pandoc.markdown)
    assert pandoc.runs == []
    assert (second.converted, second.reused, second.changes.written) == (0, CONVERSIONS, 0)
    assert events_named(events, "mirror.written") == [
        {
            "written": 0,
            "unchanged": len(sandbox.files()),
            "removed": 0,
            "converted": 0,
            "reused": CONVERSIONS,
            "pruned": 0,
            "log_level": "info",
        }
    ]


def test_a_run_with_a_problem_keeps_the_conversion_of_what_it_could_not_read(
    sandbox: Sandbox,
) -> None:
    """Plan 039, criterion 5: Home's view damaged, then mended, and pandoc runs on nothing.

    The run between prunes nothing, though it converts the tree anew, without Home's
    link; the next, which reports nothing, prunes that tree alone.
    """
    pandoc = Counting(path=Pandoc.find().path)
    sandbox.run(markdown=pandoc.markdown)
    view = next((sandbox.store.root / "confluence" / "pages" / "100").iterdir()) / "view.json"
    kept = view.read_bytes()
    view.write_text("{}", "utf-8")
    with capture_logs() as damaged:
        assert sandbox.run(markdown=pandoc.markdown).problems
    view.write_bytes(kept)
    pandoc.runs.clear()
    with capture_logs() as mended:
        outcome = sandbox.run(markdown=pandoc.markdown)
    assert (outcome.problems, outcome.reused, pandoc.runs) == ((), CONVERSIONS, [])
    assert [each["pruned"] for each in events_named(damaged, "mirror.written")] == [0]
    assert [each["pruned"] for each in events_named(mended, "mirror.written")] == [1]


# Home's view links to the page listed only, never stored, by its address on the site.
HOME_HTML = (
    "<p>Home page.</p>"
    '<p>See <a href="/wiki/spaces/MFS/pages/500/Listed+only">what is listed</a>.</p>'
)
OTHER_SITE = "https://other.example.invalid"


@pytest.fixture
def linked(sandbox: Sandbox) -> Sandbox:
    """Give the sandbox where a file's HTML depends on more than its own snapshot.

    Home links to the page listed only (500), the blog post links to Home, and a third
    comment on PRB-1 is by A Person, whom the users alone name.
    """
    issue = issue_responses("What are archived ideas?", "2026-10-21T09:00:00.000+0000")
    comments = issue[jira_v3.COMMENTS]
    assert isinstance(comments, list)
    comments.append(v3_comment(id="10102", author={"accountId": "account-1", "displayName": None}))
    news = '<p>News, from <a href="/wiki/spaces/MFS/pages/100/Home">Home</a>.</p>'
    with sandbox.store.writing():
        sandbox.store.put(Page, page_responses("100", "Home", 2, HOME_HTML, []), FETCHED, {})
        sandbox.store.put(BlogPost, post_responses(news, 2), FETCHED, {"att700": digest(IMAGE)})
        sandbox.store.put(Issue, issue, FETCHED, {"10000": digest(OTHER_IMAGE)})
    return sandbox


def unchanged(_: Sandbox) -> None:
    """Change nothing in the store."""


def leaf_edited(sandbox: Sandbox) -> None:
    """Store a new snapshot of Leaf, with other words."""
    with sandbox.store.writing():
        leaf = page_responses("300", "Leaf", 3, "<p>Other words.</p>", [])
        sandbox.store.put(Page, leaf, FETCHED, {})


def home_renamed(sandbox: Sandbox) -> None:
    """Rename Home, in a new snapshot and in its space's listing, as a download would."""
    listed = [listing_page("100", "Home, renamed", None, None), *LISTED[1:]]
    with sandbox.store.writing():
        home = page_responses("100", "Home, renamed", 3, HOME_HTML, [])
        sandbox.store.put(Page, home, FETCHED, {})
        sandbox.store.put_space(v2_space(id=SPACE_ID), listed, [POST_LISTED], [FOLDER])


def listed_page_stored(sandbox: Sandbox) -> None:
    """Store the page that Home links to, listed only until now."""
    with sandbox.store.writing():
        listed = page_responses("500", "Listed only", 1, "<p>Listed.</p>", [])
        sandbox.store.put(Page, listed, FETCHED, {})


def user_renamed(sandbox: Sandbox) -> None:
    """Rename A Person among the users."""
    with sandbox.store.writing():
        sandbox.store.put_users([v1_user(accountId="account-1", displayName="A Person, renamed")])


# Each change, the site of the run after it, and the conversions whose HTML it changes,
# which pandoc alone may run through the cache.
CHANGES = [
    pytest.param(unchanged, SITE, 0, id="unchanged"),
    # Leaf's file; the tree names Leaf as before.
    pytest.param(leaf_edited, SITE, 1, id="new-snapshot"),
    # Home's heading, the post's link to Home's new file, and the tree; Leaf's breadcrumb
    # is in its front matter.
    pytest.param(home_renamed, SITE, 3, id="title"),
    # The new page's file, Home's link to it made relative, and the tree's.
    pytest.param(listed_page_stored, SITE, 3, id="linked-page-stored"),
    # The heading of A Person's comment; the authors are in the front matter.
    pytest.param(user_renamed, SITE, 1, id="user-name"),
    # Home's link to the page not stored, on the new site; Leaf's links, which name the
    # old site, no longer the site's.
    pytest.param(unchanged, OTHER_SITE, 2, id="site"),
]


@pytest.mark.parametrize(("change", "site", "converted"), CHANGES)
def test_a_mirror_through_a_warm_cache_writes_the_bytes_of_one_from_none(
    linked: Sandbox,
    tmp_path: Path,
    change: Callable[[Sandbox], None],
    site: str,
    converted: int,
) -> None:
    """Plan 039, criterion 6: after each change, the same files, each the same bytes.

    The mirror from no cache runs in another data folder, over a copy of the raw store.
    Through the cache, pandoc runs only on what the change touched.
    """
    pandoc = Counting(path=Pandoc.find().path)
    linked.run(markdown=pandoc.markdown)
    change(linked)
    pandoc.runs.clear()
    warm = linked.run(site, pandoc.markdown)
    assert (warm.problems, warm.converted, len(pandoc.runs)) == ((), converted, converted)
    fresh = Sandbox(tmp_path / "fresh")
    shutil.copytree(linked.store.root, fresh.store.root)
    cold = fresh.run(site, pandoc.markdown)
    assert (cold.converted, cold.reused) == (warm.converted + warm.reused, 0)
    assert linked.files() == fresh.files()


def test_deleting_the_cache_after_a_warm_mirror_changes_no_file(linked: Sandbox) -> None:
    """Plan 039, criterion 6: the next mirror converts everything again, and writes nothing."""
    linked.run()
    assert linked.run().reused == CONVERSIONS
    files = linked.files()
    times = {path: path.stat().st_mtime_ns for path in linked.docs.rglob("*")}
    (linked.data / "conversions.sqlite").unlink()
    outcome = linked.run()
    assert (outcome.converted, outcome.reused) == (CONVERSIONS, 0)
    assert (outcome.changes.written, outcome.changes.removed) == (0, 0)
    assert linked.files() == files
    assert {path: path.stat().st_mtime_ns for path in linked.docs.rglob("*")} == times


def test_a_renamed_page_moves_to_its_new_slug(sandbox: Sandbox) -> None:
    """A new version with a new title has a new file; the old one is gone."""
    sandbox.run()
    with sandbox.store.writing():
        leaf = page_responses("300", "Leaf, renamed", 3, "<p>Renamed.</p>", [])
        sandbox.store.put(Page, leaf, FETCHED, {})
    outcome = sandbox.run()
    assert outcome.problems == ()
    files = sandbox.files()
    assert "confluence/MFS/300-leaf-renamed.md" in files
    assert "confluence/MFS/300-leaf.md" not in files
    assert "[Leaf](300-leaf-renamed.md)" in sandbox.text("confluence/MFS/_tree.md")


def test_a_document_gone_from_the_store_loses_its_file_not_shared_assets(
    sandbox: Sandbox,
) -> None:
    """The leaf's file goes; the image it shares with the blog post stays."""
    sandbox.run()
    shutil.rmtree(sandbox.store.root / "confluence" / "pages" / "300")
    outcome = sandbox.run()
    assert outcome.changes.removed == 1
    files = sandbox.files()
    assert "confluence/MFS/300-leaf.md" not in files
    assert f"assets/{digest(IMAGE)}.png" in files
    assert "Leaf (not yet mirrored)" in sandbox.text("confluence/MFS/_tree.md")


def failing_on(marker: str) -> Callable[[str], str]:
    """Return a Markdown writer that fails, as pandoc would, on HTML holding ``marker``."""
    pandoc = Pandoc.find()

    def markdown(html: str) -> str:
        if marker in html:
            message = "pandoc: exit status 9"
            raise PandocFailedError(message)
        return pandoc.markdown(html)

    return markdown


def test_a_run_with_problems_reports_them_and_removes_nothing(sandbox: Sandbox) -> None:
    """Each problem is reported where it is; good files are written, old ones kept."""
    sandbox.run()
    before = sandbox.files()
    with sandbox.store.writing():
        broken = page_responses("100", "Home", 2, "<p>Home again.</p>", [])
        document = broken[confluence_v2.DOCUMENT]
        assert isinstance(document, dict)
        del document["title"]
        sandbox.store.put(Page, broken, FETCHED, {})
        stray = page_responses("800", "Stray", 1, "<p>Elsewhere.</p>", [], spaceId="999")
        sandbox.store.put(Page, stray, FETCHED, {})
        sandbox.store.put(BlogPost, post_responses("<p>News, failing.</p>", 2), FETCHED, {})
        updated = issue_responses("Archived ideas, renamed", "2026-10-21T09:00:00.000+0000")
        sandbox.store.put(Issue, updated, FETCHED, {})
        untitled = listing_page("900", "Untitled", "100", "page")
        del untitled["title"]
        renamed = listing_page("100", "Home, renamed", None, None)
        sandbox.store.put_space(v2_space(id=SPACE_ID), [renamed, untitled], [POST_LISTED], [FOLDER])
    shutil.rmtree(sandbox.store.root / "confluence" / "pages" / "300")
    outcome = sandbox.run(markdown=failing_on("News, failing."))
    reasons = {problem.where: problem.reason for problem in outcome.problems}
    assert set(reasons) == {
        "confluence/pages/100/000002",
        "confluence/pages/800/000001",
        "confluence/blogposts/600/000002",
        f"confluence/spaces/{SPACE_ID}/pages.json[1]",
    }
    assert reasons["confluence/pages/100/000002"].startswith("document.json.title")
    assert reasons["confluence/pages/800/000001"] == "space not listed"
    assert reasons["confluence/blogposts/600/000002"] == "pandoc: exit status 9"
    after = sandbox.files()
    assert outcome.changes.removed == 0
    assert set(after) == set(before)
    assert after["jira/PRB/PRB-1.md"] != before["jira/PRB/PRB-1.md"]
    unchanged = ("100-home.md", "300-leaf.md", "blog/600-news.md", "_tree.md")
    assert all(
        after[f"confluence/MFS/{name}"] == before[f"confluence/MFS/{name}"] for name in unchanged
    )


def test_a_run_counts_each_macro_that_it_shows_as_unsupported(sandbox: Sandbox) -> None:
    """The outcome counts, by name, the macros that the documents show as placeholders."""
    roadmap = '<div class="conf-macro" data-macro-name="roadmap"><p>Road text</p></div>'
    with sandbox.store.writing():
        home = page_responses("100", "Home", 2, f"<p>Home again.</p>{roadmap}{roadmap}", [])
        sandbox.store.put(Page, home, FETCHED, {})
    outcome = sandbox.run()
    assert outcome.unsupported == {"macro: roadmap": 2}


def test_injected_titles_and_names_are_inert(sandbox: Sandbox) -> None:
    """Markdown and HTML in a title are escaped; line breaks and hidden marks go."""
    title = f"*Bold* [link](http://x.invalid) <script>{chr(0x200B)}"
    with sandbox.store.writing():
        sandbox.store.put_users(
            [v1_user(accountId="account-1", displayName=f"A{chr(0x2028)}Person")]
        )
        sandbox.store.put(Page, page_responses("100", title, 2, "<p>Hello</p>", []), FETCHED, {})
    assert sandbox.run().problems == ()
    path = next(path for path in sandbox.files() if path.startswith("confluence/MFS/100-"))
    matter, body = load(sandbox.text(path), "home")
    assert matter.title == "*Bold* [link](http://x.invalid) <script>"
    assert matter.author == "A Person"
    assert body.startswith("# \\*Bold\\* \\[link\\](http://x.invalid) \\<script\\>\n")
    assert path == "confluence/MFS/100-bold-link-http-x-invalid-script.md"


def test_a_clean_run_removes_only_the_files_the_mirror_owns(sandbox: Sandbox) -> None:
    """A stale document in the layout's place goes; other files under docs/ stay."""
    sandbox.run()
    foreign = ["notes.md", "confluence/MFS/.draft.md", "assets/readme.txt", "jira/PRB/sub/x.md"]
    stale = ["jira/PRB/PRB-99.md", f"assets/{'c' * 64}.png"]
    for relative in [*foreign, *stale]:
        (sandbox.docs / relative).parent.mkdir(parents=True, exist_ok=True)
        (sandbox.docs / relative).write_text("left here", "utf-8")
    outcome = sandbox.run()
    assert outcome.changes.removed == len(stale)
    files = sandbox.files()
    assert all(relative in files for relative in foreign)
    assert not [relative for relative in stale if relative in files]


def test_the_mirror_leaves_the_work_log_s_files_and_the_work_log_the_mirror_s(
    sandbox: Sandbox,
) -> None:
    """Each step removes only the files it owns; neither removes the other's."""
    sandbox.run()
    worklog = ["worklog/entries/e-0123456789abcdef-notes.md", "worklog/transcripts/t-20261020-1.md"]
    for relative in worklog:
        (sandbox.docs / relative).parent.mkdir(parents=True, exist_ok=True)
        (sandbox.docs / relative).write_text("a work-log file", "utf-8")
    mirrored = set(sandbox.files()) - set(worklog)
    assert sandbox.run().changes.removed == 0
    assert sync(sandbox.docs, {}, worklog_owned, remove=True).removed == len(worklog)
    assert set(sandbox.files()) == mirrored


def test_the_tree_links_only_files_that_were_built(sandbox: Sandbox) -> None:
    """A renamed page whose conversion fails is not yet mirrored under its new name."""
    sandbox.run()
    with sandbox.store.writing():
        renamed = page_responses("300", "Leaf, renamed", 3, "<p>Failing leaf.</p>", [])
        sandbox.store.put(Page, renamed, FETCHED, {})
    outcome = sandbox.run(markdown=failing_on("Failing leaf."))
    assert [problem.where for problem in outcome.problems] == ["confluence/pages/300/000003"]
    tree = sandbox.text("confluence/MFS/_tree.md")
    assert "Leaf (not yet mirrored)" in tree
    assert "300-leaf-renamed.md" not in tree
    assert "confluence/MFS/300-leaf.md" in sandbox.files()
