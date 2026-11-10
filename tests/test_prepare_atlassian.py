"""The mirror end to end: a raw store built from documented responses, prepared to files.

The expectations come from the "Markdown mirror" section of the data layout: the paths,
the front matter's keys and values, the body's sections, the assets, the trees, and a
run that changes nothing writing nothing. A run prepares Confluence, then Jira, apart, as
plan 030 has it: each places every document, and writes and removes its own files.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.markdown import load
from kb_mcp.mirror.adapters.mirror_files import write_changed
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocFailedError
from kb_mcp.mirror.domain.mirror import FrontMatter, Mention
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.atlassian.prepare.app.prepare import PREPARED, prepare_atlassian
from kb_mcp.sources.atlassian.prepare.app.preparer import prepare_classes
from kb_mcp.sources.worklog.prepare.adapters.owned import worklog_owned
from tests.composed import MODEL
from tests.mirrors import prepared_source
from tests.samples import (
    v1_user,
    v2_attachment,
    v2_folder,
    v2_page,
    v2_space,
    v3_comment,
    v3_issue,
)
from tests.test_prepare_worklog import Counting
from tests.test_pruning import events_named

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from kb_mcp.kernel.outcome import Outcome
    from kb_mcp.sources.atlassian.prepare.app.prepare import AtlassianCounts

SITE = "https://site.example.invalid"
FETCHED = datetime(2026, 10, 22, 8, 15, tzinfo=UTC)
IMAGE = b"\x89PNG an image"
OTHER_IMAGE = b"\x89PNG another image"
SPACE_ID = "196613"
WORDS = "Words of the leaf page."
# Each source's documents: Home, Leaf and the blog post; the issue.
DOCUMENTS = {"confluence": 3, "jira": 1}
# A conversion for each document's file, and Confluence's for the space's tree.
CONVERSIONS = {"confluence": 4, "jira": 1}
# Each source's files: its documents, Confluence's tree, and the file that its documents
# attach, the leaf's image and the blog post's being one, the issue's another.
FILES = {"confluence": 5, "jira": 2}


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

    def run(
        self,
        site: str | None = SITE,
        markdown: Callable[[str], str] | None = None,
        sources: Sequence[str] = ("confluence", "jira"),
    ) -> dict[str, Outcome[AtlassianCounts]]:
        """Mirror each source of the store, in order, through the cache; give its outcome.

        Pandoc writes the Markdown, unless another writer is given.
        """
        writer = markdown or Pandoc.find().markdown
        return {
            source: prepared_source(self.store, self.docs, site, writer, source)
            for source in sources
        }

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


def each(
    outcomes: dict[str, Outcome[AtlassianCounts]],
    count: Callable[[Outcome[AtlassianCounts]], object],
) -> dict[str, object]:
    """Give a count of each source's outcome, by the source's name."""
    return {source: count(outcome) for source, outcome in outcomes.items()}


def test_the_mirror_writes_exactly_the_layouts_paths(sandbox: Sandbox) -> None:
    """Pages, the blog post, the issue, the tree and one asset per distinct file."""
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.problems) == {"confluence": (), "jira": ()}
    assert each(outcomes, lambda outcome: outcome.counts.documents) == DOCUMENTS
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
        people=(Mention(role="author", name="A Person", identity="atlassian:account-1"),),
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
            Mention(role="author", name="A Person", identity="atlassian:account-1"),
            Mention(role="creator", name="Another Person", identity="atlassian:account-2"),
            Mention(
                role="commenter",
                name="Another Person",
                identity="atlassian:account-2",
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
    outcomes = sandbox.run()
    changes = each(
        outcomes, lambda outcome: (outcome.counts.changes.written, outcome.counts.changes.removed)
    )
    assert changes == {"confluence": (0, 0), "jira": (0, 0)}
    assert each(outcomes, lambda outcome: outcome.counts.changes.unchanged) == FILES
    assert sum(FILES.values()) == len(files)
    assert {path: path.stat().st_mtime_ns for path in sandbox.docs.rglob("*")} == times
    shutil.rmtree(sandbox.docs)
    sandbox.run()
    assert sandbox.files() == files


def test_a_second_run_with_nothing_changed_runs_pandoc_on_nothing(sandbox: Sandbox) -> None:
    """Plan 039, criterion 5: each conversion of the first run is reused, no file written."""
    pandoc = Counting(path=Pandoc.find().path)
    first = sandbox.run(markdown=pandoc.markdown)
    assert each(first, lambda outcome: (outcome.counts.converted, outcome.counts.reused)) == {
        source: (count, 0) for source, count in CONVERSIONS.items()
    }
    assert len(pandoc.runs) == sum(CONVERSIONS.values())
    pandoc.runs.clear()
    with capture_logs() as events:
        second = sandbox.run(markdown=pandoc.markdown)
    assert pandoc.runs == []
    assert each(
        second, lambda outcome: (outcome.counts.converted, outcome.counts.changes.written)
    ) == {
        "confluence": (0, 0),
        "jira": (0, 0),
    }
    assert events_named(events, "prepare.written") == [
        {
            "source": source,
            "written": 0,
            "unchanged": FILES[source],
            "removed": 0,
            "converted": 0,
            "reused": CONVERSIONS[source],
            "pruned": 0,
            "log_level": "info",
        }
        for source in ("confluence", "jira")
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
        assert sandbox.run(markdown=pandoc.markdown)["confluence"].problems
    view.write_bytes(kept)
    pandoc.runs.clear()
    with capture_logs() as mended:
        outcomes = sandbox.run(markdown=pandoc.markdown)
    assert each(outcomes, lambda outcome: (outcome.problems, outcome.counts.reused)) == {
        source: ((), count) for source, count in CONVERSIONS.items()
    }
    assert pandoc.runs == []
    assert [each["pruned"] for each in events_named(damaged, "prepare.written")] == [0, 0]
    assert [each["pruned"] for each in events_named(mended, "prepare.written")] == [1, 0]


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
    assert [outcome.problems for outcome in warm.values()] == [(), ()]
    assert (
        sum(outcome.counts.converted for outcome in warm.values()) == len(pandoc.runs) == converted
    )
    fresh = Sandbox(tmp_path / "fresh")
    shutil.copytree(linked.store.root, fresh.store.root)
    cold = fresh.run(site, pandoc.markdown)
    assert each(cold, lambda outcome: (outcome.counts.converted, outcome.counts.reused)) == each(
        warm, lambda outcome: (outcome.counts.converted + outcome.counts.reused, 0)
    )
    assert linked.files() == fresh.files()


def test_deleting_the_cache_after_a_warm_mirror_changes_no_file(linked: Sandbox) -> None:
    """Plan 039, criterion 6: the next mirror converts everything again, and writes nothing."""
    linked.run()
    assert each(linked.run(), lambda outcome: outcome.counts.reused) == CONVERSIONS
    files = linked.files()
    times = {path: path.stat().st_mtime_ns for path in linked.docs.rglob("*")}
    (linked.data / "conversions.sqlite").unlink()
    outcomes = linked.run()
    assert each(outcomes, lambda outcome: outcome.counts.converted) == CONVERSIONS
    assert each(outcomes, lambda outcome: outcome.counts.reused) == {"confluence": 0, "jira": 0}
    changes = each(
        outcomes, lambda outcome: (outcome.counts.changes.written, outcome.counts.changes.removed)
    )
    assert changes == {"confluence": (0, 0), "jira": (0, 0)}
    assert linked.files() == files
    assert {path: path.stat().st_mtime_ns for path in linked.docs.rglob("*")} == times


def test_a_renamed_page_moves_to_its_new_slug(sandbox: Sandbox) -> None:
    """A new version with a new title has a new file; the old one is gone."""
    sandbox.run()
    with sandbox.store.writing():
        leaf = page_responses("300", "Leaf, renamed", 3, "<p>Renamed.</p>", [])
        sandbox.store.put(Page, leaf, FETCHED, {})
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.problems) == {"confluence": (), "jira": ()}
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
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 1,
        "jira": 0,
    }
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
    """Each problem is reported where it is, by its source; good files are written, old kept.

    Every problem is Confluence's, whose files all stay; Jira's prepare writes its issue
    again, and has nothing to remove.
    """
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
    outcomes = sandbox.run(markdown=failing_on("News, failing."))
    assert outcomes["jira"].problems == ()
    reasons = {problem.where: problem.reason for problem in outcomes["confluence"].problems}
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
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 0,
        "jira": 0,
    }
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
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.counts.unsupported) == {
        "confluence": {"macro: roadmap": 2},
        "jira": {},
    }


def test_injected_titles_and_names_are_inert(sandbox: Sandbox) -> None:
    """Markdown and HTML in a title are escaped; line breaks and hidden marks go."""
    title = f"*Bold* [link](http://x.invalid) <script>{chr(0x200B)}"
    with sandbox.store.writing():
        sandbox.store.put_users(
            [v1_user(accountId="account-1", displayName=f"A{chr(0x2028)}Person")]
        )
        sandbox.store.put(Page, page_responses("100", title, 2, "<p>Hello</p>", []), FETCHED, {})
    assert each(sandbox.run(), lambda outcome: outcome.problems) == {"confluence": (), "jira": ()}
    path = next(path for path in sandbox.files() if path.startswith("confluence/MFS/100-"))
    matter, body = load(sandbox.text(path), "home")
    assert matter.title == "*Bold* [link](http://x.invalid) <script>"
    assert matter.author == "A Person"
    assert body.startswith("# \\*Bold\\* \\[link\\](http://x.invalid) \\<script\\>\n")
    assert path == "confluence/MFS/100-bold-link-http-x-invalid-script.md"


def test_a_clean_run_removes_only_the_files_the_mirror_owns(sandbox: Sandbox) -> None:
    """A stale document in the layout's place goes; other files under docs/ stay.

    The stale attached file goes with the first prepare, Confluence's, the stale issue
    with Jira's; a tree is Confluence's alone.
    """
    sandbox.run()
    foreign = [
        "notes.md",
        "confluence/MFS/.draft.md",
        "assets/readme.txt",
        "jira/PRB/sub/x.md",
        "jira/PRB/_tree.md",
    ]
    stale = ["jira/PRB/PRB-99.md", f"assets/{'c' * 64}.png"]
    for relative in [*foreign, *stale]:
        (sandbox.docs / relative).parent.mkdir(parents=True, exist_ok=True)
        (sandbox.docs / relative).write_text("left here", "utf-8")
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 1,
        "jira": 1,
    }
    files = sandbox.files()
    assert all(relative in files for relative in foreign)
    assert not [relative for relative in stale if relative in files]


def test_the_mirror_leaves_the_work_log_s_files_and_the_work_log_the_mirror_s(
    sandbox: Sandbox,
) -> None:
    """Each preparer removes only the files it owns; neither removes the other's."""
    sandbox.run()
    worklog = ["worklog/entries/e-0123456789abcdef-notes.md", "worklog/transcripts/t-20261020-1.md"]
    for relative in worklog:
        (sandbox.docs / relative).parent.mkdir(parents=True, exist_ok=True)
        (sandbox.docs / relative).write_text("a work-log file", "utf-8")
    prepared = set(sandbox.files()) - set(worklog)
    assert each(sandbox.run(), lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 0,
        "jira": 0,
    }
    assert write_changed(sandbox.docs, {}, worklog_owned, remove=True).removed == len(worklog)
    assert set(sandbox.files()) == prepared


def test_the_tree_links_only_files_that_were_built(sandbox: Sandbox) -> None:
    """A renamed page whose conversion fails is not yet mirrored under its new name."""
    sandbox.run()
    with sandbox.store.writing():
        renamed = page_responses("300", "Leaf, renamed", 3, "<p>Failing leaf.</p>", [])
        sandbox.store.put(Page, renamed, FETCHED, {})
    outcomes = sandbox.run(markdown=failing_on("Failing leaf."))
    where = [problem.where for problem in outcomes["confluence"].problems]
    assert where == ["confluence/pages/300/000003"]
    tree = sandbox.text("confluence/MFS/_tree.md")
    assert "Leaf (not yet mirrored)" in tree
    assert "300-leaf-renamed.md" not in tree
    assert "confluence/MFS/300-leaf.md" in sandbox.files()


# The issue's description, linking Leaf by its address on the site, then its image.
LEAF_LINK = (
    '<p>See <a href="https://site.example.invalid/wiki/spaces/MFS/pages/300/Leaf">the leaf</a>.'
    '</p><p><img src="/rest/api/3/attachment/content/10000"></p>'
)


@pytest.fixture
def crossed(sandbox: Sandbox) -> Sandbox:
    """Give the sandbox where the issue links to Leaf and attaches Leaf's image.

    Leaf links to the issue already: each source's file then depends on the other's
    documents, and one attached file is both sources'.
    """
    issue = issue_responses("What are archived ideas?", "2026-10-21T09:00:00.000+0000")
    document = issue[jira_v3.ISSUE]
    assert isinstance(document, dict)
    document["renderedFields"] = {"description": LEAF_LINK}
    with sandbox.store.writing():
        sandbox.store.put(Issue, issue, FETCHED, {"10000": digest(IMAGE)})
    return sandbox


def test_jira_alone_links_confluence_s_pages_and_writes_its_own_files_alone(
    crossed: Sandbox,
) -> None:
    """Plan 030, criterion 11: Jira's prepare places every document, Leaf's too.

    So its issue links Leaf's file, which it does not write; it writes the issue and the
    file the issue attaches.
    """
    outcomes = crossed.run(sources=("jira",))
    assert each(outcomes, lambda outcome: outcome.problems) == {"jira": ()}
    assert set(crossed.files()) == {"jira/PRB/PRB-1.md", f"assets/{digest(IMAGE)}.png"}
    _, body = load(crossed.text("jira/PRB/PRB-1.md"), "issue")
    assert "[the leaf](../../confluence/MFS/300-leaf.md)" in body


def test_either_source_first_writes_the_same_files(crossed: Sandbox, tmp_path: Path) -> None:
    """Plan 030, criterion 11: Confluence then Jira, or Jira then Confluence, the same bytes.

    Each links the other's file, and the file that both attach is one.
    """
    crossed.run()
    other = Sandbox(tmp_path / "other")
    shutil.copytree(crossed.store.root, other.store.root)
    other.run(sources=("jira", "confluence"))
    files = crossed.files()
    assert files == other.files()
    _, leaf = load(crossed.text("confluence/MFS/300-leaf.md"), "leaf")
    assert "[PRB-1](../../jira/PRB/PRB-1.md)" in leaf
    assert [path for path in files if path.startswith("assets/")] == [f"assets/{digest(IMAGE)}.png"]


@pytest.mark.parametrize(
    "document_classes",
    [(Page,), (BlogPost,), (Page, Issue), ()],
    ids=["pages", "blog posts", "two sources' types", "none"],
)
def test_types_other_than_all_of_a_source_s_are_refused_and_no_file_removed(
    sandbox: Sandbox, document_classes: tuple[type[Page | BlogPost | Issue], ...]
) -> None:
    """Plan 030: a source's files are removed whichever types it built, so it builds them all.

    A prepare of the pages alone would otherwise remove every blog post.
    """
    sandbox.run()
    before = sandbox.files()
    path = sandbox.docs.parent / "conversions.sqlite"
    with (
        conversions.opened(path, lambda: "a writer", str, source="confluence") as cache,
        pytest.raises(KeyError),
    ):
        prepare_atlassian(sandbox.store, sandbox.docs, None, cache, document_classes)
    assert sandbox.files() == before


def test_a_file_that_both_sources_attach_stays_while_either_wants_it(crossed: Sandbox) -> None:
    """Plan 030: Leaf and the blog post gone, Confluence's prepare keeps the issue's image.

    Then the issue gone, Jira's prepare removes its file and the image, which no placed
    document wants any more.
    """
    crossed.run()
    for resource_type, document in (("pages", "300"), ("blogposts", "600")):
        shutil.rmtree(crossed.store.root / "confluence" / resource_type / document)
    assert crossed.run(sources=("confluence",))["confluence"].counts.changes.removed == len(
        ["300-leaf.md", "blog/600-news.md"]
    )
    image = f"assets/{digest(IMAGE)}.png"
    assert image in crossed.files()
    shutil.rmtree(crossed.store.root / "jira" / "issues" / "10000")
    assert crossed.run(sources=("jira",))["jira"].counts.changes.removed == len(["PRB-1.md", image])
    assert image not in crossed.files()


def test_a_jira_document_that_pandoc_fails_on_keeps_its_file_while_a_stale_page_goes(
    sandbox: Sandbox,
) -> None:
    """Plan 030, criterion 11: a source's conversion problems hold back its removals alone."""
    sandbox.run()
    before = sandbox.files()
    with sandbox.store.writing():
        failing = issue_responses("Failing ideas", "2026-10-21T09:00:00.000+0000")
        sandbox.store.put(Issue, failing, FETCHED, {"10000": digest(OTHER_IMAGE)})
    shutil.rmtree(sandbox.store.root / "confluence" / "pages" / "300")
    outcomes = sandbox.run(markdown=failing_on("Failing ideas"))
    assert outcomes["confluence"].problems == ()
    assert [problem.reason for problem in outcomes["jira"].problems] == ["pandoc: exit status 9"]
    files = sandbox.files()
    assert "confluence/MFS/300-leaf.md" not in files
    assert files["jira/PRB/PRB-1.md"] == before["jira/PRB/PRB-1.md"]


def test_an_unreadable_issue_holds_back_jira_s_removals_and_every_attached_file_s(
    sandbox: Sandbox,
) -> None:
    """Plan 030, criterion 11: not Confluence's, whose stale page goes.

    The issue unreadable, the file it attached is wanted by no placed document, and stays
    with a stale one; so does a stale issue. Mended, the next run removes both.
    """
    sandbox.run()
    stale = ["jira/PRB/PRB-99.md", f"assets/{'c' * 64}.png"]
    for relative in stale:
        (sandbox.docs / relative).write_text("left here", "utf-8")
    shutil.rmtree(sandbox.store.root / "confluence" / "pages" / "300")
    snapshot = next((sandbox.store.root / "jira" / "issues" / "10000").iterdir()) / jira_v3.ISSUE
    kept = snapshot.read_bytes()
    snapshot.write_text("{}", "utf-8")
    outcomes = sandbox.run()
    assert outcomes["confluence"].problems == ()
    where = [problem.where.rpartition("/")[0] for problem in outcomes["jira"].problems]
    assert where == ["jira/issues/10000"]
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 1,
        "jira": 0,
    }
    files = sandbox.files()
    assert "confluence/MFS/300-leaf.md" not in files
    held = [*stale, "jira/PRB/PRB-1.md", f"assets/{digest(OTHER_IMAGE)}.png"]
    assert [relative for relative in held if relative not in files] == []
    snapshot.write_bytes(kept)
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 1,
        "jira": 1,
    }
    assert [relative for relative in stale if relative in sandbox.files()] == []


# An image that the next revision of a document attaches in place of its first.
THIRD_IMAGE = b"\x89PNG the next image"


def issue_with_the_next_image(sandbox: Sandbox, summary: str) -> str:
    """Store PRB-1's next revision, its file another; give the file that its last copy links."""
    with sandbox.store.writing():
        next_image = sandbox.store.put_blob(THIRD_IMAGE)
        updated = issue_responses(summary, "2026-10-21T09:00:00.000+0000")
        sandbox.store.put(Issue, updated, FETCHED, {"10000": next_image})
    return f"assets/{digest(OTHER_IMAGE)}.png"


def test_a_file_that_a_kept_issue_links_stays_while_pandoc_fails_on_its_next_revision(
    sandbox: Sandbox,
) -> None:
    """The last good copy of a document keeps its image, whichever source's prepare runs.

    No placed document wants the issue's first image, its next revision attaching another,
    yet the file not rebuilt still links it. Built at last, it no longer does: the image
    goes with Jira's prepare.
    """
    sandbox.run()
    before = sandbox.files()
    image = issue_with_the_next_image(sandbox, "Failing ideas")
    outcomes = sandbox.run(markdown=failing_on("Failing ideas"))
    assert outcomes["confluence"].problems == ()
    assert [problem.reason for problem in outcomes["jira"].problems] == ["pandoc: exit status 9"]
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 0,
        "jira": 0,
    }
    files = sandbox.files()
    assert files["jira/PRB/PRB-1.md"] == before["jira/PRB/PRB-1.md"]
    assert image in files
    assert image.removeprefix("assets/") in sandbox.text("jira/PRB/PRB-1.md")
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 0,
        "jira": 1,
    }
    assert image not in sandbox.files()


def test_a_file_that_a_page_not_rebuilt_links_outlives_the_hold_of_its_source_s_problem(
    sandbox: Sandbox,
) -> None:
    """Page 300 fails: Jira's prepare, which has no problem, leaves its image to its file.

    Both documents that attach the image take another: no placed document wants it.
    """
    sandbox.run()
    before = sandbox.files()
    with sandbox.store.writing():
        next_image = sandbox.store.put_blob(THIRD_IMAGE)
        leaf = [v2_attachment(id="att400", title="leaf.png", pageId="300")]
        failing = page_responses("300", "Leaf", 3, "<p>Failing leaf.</p>", leaf)
        sandbox.store.put(Page, failing, FETCHED, {"att400": next_image})
        sandbox.store.put(
            BlogPost, post_responses("<p>News.</p>", 2), FETCHED, {"att700": next_image}
        )
    outcomes = sandbox.run(markdown=failing_on("Failing leaf."))
    assert [problem.where for problem in outcomes["confluence"].problems] == [
        "confluence/pages/300/000003"
    ]
    assert outcomes["jira"].problems == ()
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 0,
        "jira": 0,
    }
    files = sandbox.files()
    assert files["confluence/MFS/300-leaf.md"] == before["confluence/MFS/300-leaf.md"]
    assert f"assets/{digest(IMAGE)}.png" in files


def test_a_file_that_the_source_not_prepared_links_stays_until_it_is_prepared(
    sandbox: Sandbox,
) -> None:
    """With no problem at all, Confluence's prepare leaves the image of Jira's file not rebuilt.

    As ``prepare confluence`` after a fetch does; Jira's prepare then takes it.
    """
    sandbox.run()
    image = issue_with_the_next_image(sandbox, "Other ideas")
    assert sandbox.run(sources=("confluence",))["confluence"].counts.changes.removed == 0
    assert image in sandbox.files()
    assert sandbox.run(sources=("jira",))["jira"].counts.changes.removed == 1
    assert image not in sandbox.files()


def test_a_file_that_a_stale_document_alone_links_goes_with_that_document(
    sandbox: Sandbox,
) -> None:
    """The issue gone from the store, Jira's prepare removes its file, then its file's image."""
    sandbox.run()
    image = f"assets/{digest(OTHER_IMAGE)}.png"
    shutil.rmtree(sandbox.store.root / "jira" / "issues" / "10000")
    outcomes = sandbox.run()
    assert each(outcomes, lambda outcome: outcome.counts.changes.removed) == {
        "confluence": 0,
        "jira": len(["PRB-1.md", image]),
    }
    assert image not in sandbox.files()


def space_damaged(sandbox: Sandbox) -> None:
    """Make the record of the space unreadable, as a disk or an editor might."""
    (sandbox.store.root / "confluence" / "spaces" / SPACE_ID / "space.json").write_text(
        "{}", "utf-8"
    )


def issue_damaged(sandbox: Sandbox) -> None:
    """Make the newest snapshot of the issue unreadable."""
    folder = max((sandbox.store.root / "jira" / "issues" / "10000").iterdir())
    (folder / jira_v3.ISSUE).write_text("{}", "utf-8")


def prepared(
    sandbox: Sandbox, source: str
) -> tuple[Outcome[AtlassianCounts], list[dict[str, object]]]:
    """Prepare one source as its preparer does; give how it ended, and what it warned."""
    settings = MODEL(data_dir=sandbox.data)
    with capture_logs() as events:
        done = prepare_classes(settings, SITE, Pandoc.find(), source, PREPARED[source])
    return done, [each for each in events if each["log_level"] == "warning"]


def test_a_prepare_of_jira_says_what_it_could_not_read_of_confluence(crossed: Sandbox) -> None:
    """The space unreadable changes Jira's file: its link to Leaf falls back on the site.

    So Jira's prepare, which has no problem of its own and whose row is done, says each
    of Confluence's as a warning, and that it removed nothing is not said.
    """
    crossed.run()
    _, linked_body = load(crossed.text("jira/PRB/PRB-1.md"), "issue")
    assert "[the leaf](../../confluence/MFS/300-leaf.md)" in linked_body
    space_damaged(crossed)
    done, warned = prepared(crossed, "jira")
    assert (done.ending, done.problems) == ("done", ())
    _, body = load(crossed.text("jira/PRB/PRB-1.md"), "issue")
    assert f"[the leaf]({SITE}/wiki/spaces/MFS/pages/300/Leaf)" in body
    theirs = done.warnings
    assert theirs
    assert all(each.reason.startswith("confluence's, read here: ") for each in theirs)
    assert [(each["event"], each["source"], each["where"], each["reason"]) for each in warned] == [
        ("prepare.not_mirrored", "jira", warning.where, warning.reason) for warning in theirs
    ]


def test_a_prepare_of_confluence_says_what_it_could_not_read_of_jira(crossed: Sandbox) -> None:
    """The issue unreadable, Confluence's prepare fails nothing of its own, and says it."""
    crossed.run()
    issue_damaged(crossed)
    done, warned = prepared(crossed, "confluence")
    assert (done.ending, done.problems) == ("done", ())
    (theirs,) = done.warnings
    assert theirs.where.startswith("jira/issues/10000/")
    assert theirs.reason.startswith("jira's, read here: ")
    assert [(each["event"], each["source"], each["where"]) for each in warned] == [
        ("prepare.not_mirrored", "confluence", theirs.where)
    ]
    assert done.text("short").endswith(f"warning: {theirs.where}: {theirs.reason}\nwarnings: 1\n")


def test_a_prepare_of_a_source_with_no_problem_anywhere_says_nothing(crossed: Sandbox) -> None:
    """Nothing is said of another source when its documents all read."""
    done, warned = prepared(crossed, "jira")
    assert (done.warnings, warned) == ((), [])
    assert "warning" not in done.text("short")


def test_each_source_prunes_its_own_conversions_alone(sandbox: Sandbox) -> None:
    """Plan 030, criterion 11: Leaf edited, Confluence's prepare prunes Leaf's old conversion.

    Jira's rows, which that prepare did not use, stay: Jira's prepare then converts
    nothing.
    """
    pandoc = Counting(path=Pandoc.find().path)
    sandbox.run(markdown=pandoc.markdown)
    leaf_edited(sandbox)
    with capture_logs() as events:
        sandbox.run(markdown=pandoc.markdown, sources=("confluence",))
    assert [each["pruned"] for each in events_named(events, "prepare.written")] == [1]
    pandoc.runs.clear()
    jira = sandbox.run(markdown=pandoc.markdown, sources=("jira",))["jira"]
    assert (jira.counts.converted, jira.counts.reused, pandoc.runs) == (0, CONVERSIONS["jira"], [])


def test_a_cache_of_plan_039_s_columns_is_adopted_and_nothing_converted(
    sandbox: Sandbox,
) -> None:
    """Plan 056: its rows name no source, though each holds a conversion used.

    The tag pre-kb-mcp's file, on the user's other machine. The first prepare makes each
    row one of each Atlassian source, saying so once; neither converts any text again,
    and both write the same files.
    """
    sandbox.run()
    files = sandbox.files()
    path = sandbox.data / "conversions.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        kept = connection.execute("SELECT DISTINCT key, markdown FROM conversions").fetchall()
    for suffix in ("", "-wal", "-shm"):
        path.with_name(f"{path.name}{suffix}").unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE conversions (key TEXT PRIMARY KEY, markdown TEXT NOT NULL)"
        )
        connection.executemany("INSERT INTO conversions (key, markdown) VALUES (?, ?)", kept)
        connection.commit()
    with capture_logs() as events:
        outcomes = sandbox.run()
    assert events_named(events, "prepare.cache_adopted") == [
        {"sources": ["confluence", "jira"], "rows": len(kept), "log_level": "info"}
    ]
    assert events_named(events, "prepare.cache_replaced") == []
    assert each(outcomes, lambda outcome: (outcome.counts.converted, outcome.counts.reused)) == {
        source: (0, count) for source, count in CONVERSIONS.items()
    }
    assert sandbox.files() == files
