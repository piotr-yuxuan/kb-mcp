"""The mirror's paths and text rules, as the data layout states them."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest

from kb_mcp.kernel.slug import slug
from kb_mcp.mirror.domain.mirror_text import one_line, visible
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.atlassian.prepare.domain.layout import (
    asset_path,
    confluence_path,
    document_html,
    issue_path,
    tree_path,
)
from kb_mcp.sources.worklog.prepare.domain.layout import retired, worklog_path

MOMENT = datetime(2026, 10, 20, 21, 52, 41, tzinfo=UTC)
DIGEST = "e" * 64


def page(title: str, document_class: type[Page | BlogPost] = Page) -> Page | BlogPost:
    """Return a page or a blog post with this title."""
    return document_class(
        id="196845",
        title=title,
        author=None,
        created=MOMENT,
        updated=MOMENT,
        site_path="/wiki/spaces/MFS/pages/196845",
        space_id="196613",
        version=3,
        status="current",
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Probe complex", "probe-complex"),
        ("  Hello, World!  ", "hello-world"),
        ("Crème brûlée", "creme-brulee"),
        ("ADR-020: Strongroom   as the only store", "adr-020-strongroom-as-the-only-store"),
        ("\uff26\uff55\uff4c\uff4c width \u2460", "full-width-1"),
        ("日本語", ""),
        ("--", ""),
        ("a" * 70, "a" * 60),
        # Cut at 60, where a run of other characters becomes the last "-", then removed.
        ("a" * 59 + " b", "a" * 59),
    ],
)
def test_a_slug_keeps_ascii_letters_and_digits(title: str, expected: str) -> None:
    """NFKD, lowered, accents dropped, other runs as one -, trimmed, cut at 60."""
    assert slug(title) == expected


def test_documents_are_placed_by_space_project_and_key() -> None:
    """Pages and blog posts by space key, id and slug; issues by project and key."""
    assert confluence_path("confluence", page("Probe complex"), "MFS") == PurePosixPath(
        "confluence/MFS/196845-probe-complex.md"
    )
    assert confluence_path("confluence", page("News!", BlogPost), "MFS") == PurePosixPath(
        "confluence/MFS/blog/196845-news.md"
    )
    issue = Issue(
        id="10000",
        title="What are archived ideas?",
        author=None,
        created=MOMENT,
        updated=MOMENT,
        site_path="/browse/PRB-1",
        key="PRB-1",
        project="PRB",
        issue_type="Idea",
        status="Parking lot",
    )
    assert issue_path("jira", issue) == PurePosixPath("jira/PRB/PRB-1.md")
    assert tree_path("confluence", "MFS") == PurePosixPath("confluence/MFS/_tree.md")


@pytest.mark.parametrize(
    ("document_type", "identifier", "title", "expected"),
    [
        (
            "entry",
            "e-0123456789abcdef-2",
            "Retrospective notes",
            "entries/e-0123456789abcdef-2-retrospective-notes.md",
        ),
        (
            "transcript",
            "t-20261020-1",
            "Transcript, 2026-10-20 Tue, 1",
            "transcripts/t-20261020-1-transcript-2026-10-20-tue-1.md",
        ),
        ("entry", "e-0123456789abcdef", "", "entries/e-0123456789abcdef.md"),
        ("day", "d-20261027", "<2026-10-27 Tue>", "days/d-20261027.md"),
        (
            "meeting",
            "m-20261027-payments-stand-up",
            "Payments stand-up",
            "meetings/m-20261027-payments-stand-up.md",
        ),
    ],
)
def test_work_log_documents_are_placed_by_type_id_and_title(
    document_type: str, identifier: str, title: str, expected: str
) -> None:
    """<data>/docs/worklog/{entries,transcripts}/<id>-<slug>.md, as plan 017 says.

    A day's and a meeting's file is <data>/docs/worklog/{days,meetings}/<id>.md alone, as
    plan 042 says: the title is in the id already.
    """
    path = worklog_path("worklog", document_type, identifier, title)
    assert path == PurePosixPath("worklog", expected)


ENTRY, SECOND = "e-0123456789abcdef", "e-0123456789abcdef-2"
NOTES, NOTES_ON_X = "t-20261021-notes", "t-20261021-notes-on-x"
KNOWN = {ENTRY, SECOND, NOTES, NOTES_ON_X, "d-20261027"}
KNOWN |= {"m-20261026-one-to-one", "m-20261026-one-to-one--2"}


@pytest.mark.parametrize(
    ("document_type", "identifier", "title", "written", "gone"),
    [
        ("entry", ENTRY, "Retrospective notes", {ENTRY}, True),
        ("entry", SECOND, "Retrospective notes", {SECOND}, False),
        ("entry", SECOND, "Retrospective notes", {ENTRY, SECOND}, True),
        ("entry", ENTRY, "2026 plan", {ENTRY}, True),
        ("entry", ENTRY, "", {ENTRY}, True),
        ("entry", ENTRY, "2 plan", {SECOND}, False),
        ("entry", ENTRY, "2 plan", {ENTRY, SECOND}, True),
        ("transcript", NOTES, "On x, the ledger", {NOTES_ON_X}, False),
        ("transcript", NOTES_ON_X, "Notes on the ledger", {NOTES_ON_X}, False),
        ("transcript", NOTES_ON_X, "Notes on the ledger", {NOTES, NOTES_ON_X}, True),
        ("meeting", "m-20261026-one-to-one", "One-to-one", {"m-20261026-one-to-one"}, True),
        ("day", "d-20261027", "<2026-10-27 Tue>", {"d-20261027"}, True),
        ("entry", "e-fedcba9876543210", "Gone", KNOWN, False),
    ],
)
def test_a_file_is_retired_when_each_known_id_that_begins_its_name_is_written(
    document_type: str, identifier: str, title: str, written: set[str], *, gone: bool
) -> None:
    """A known id begins a name alone or before a dash; one at least, and each one written.

    So that a name that two ids could give, the first entry of a digest titled ``2 plan``
    or its second titled ``Plan``, any name of the second, a transcript ``notes`` titled
    ``On x, the ledger`` or ``notes on x`` titled ``The ledger``, is no one's while one of
    them is not written: its file stays. A name that no known id begins stays too; one
    that a known id and a dash begin is that id's, though its slug begins with a number.
    """
    path = worklog_path("worklog", document_type, identifier, title)
    assert retired([path], KNOWN, written) == ({path} if gone else set())


def test_an_empty_slug_leaves_the_id_alone() -> None:
    """A title without ASCII letters or digits names the file by its id."""
    assert confluence_path("confluence", page("日本語"), "MFS") == PurePosixPath(
        "confluence/MFS/196845.md"
    )


@pytest.mark.parametrize(
    ("filename", "name"),
    [
        ("probe-complex.PNG", f"{DIGEST}.png"),
        ("archive.tar.gz", f"{DIGEST}.gz"),
        ("notes", DIGEST),
        ("odd.ext-ension", DIGEST),
        ("too.longextension", DIGEST),
        ("trailing.", DIGEST),
    ],
)
def test_an_asset_keeps_a_plain_extension_only(filename: str, name: str) -> None:
    """The extension, lowered, when it matches [a-z0-9]{1,8}; otherwise none."""
    assert asset_path(DIGEST, filename) == PurePosixPath("assets") / name


def test_invisible_characters_are_removed() -> None:
    """Zero-width, bidi, tag, control, surrogate and private characters go; tab stays."""
    text = "a\u200bb\u202ec\u2066d\U000e0041e\U000e0100f\x07g\th\ni\u00a0j\ud800k\ue000l"
    assert visible(text) == "abcdefg\th\ni\u00a0jkl"
    assert visible("line\u2028para\u2029end") == "line para end"


def test_one_line_turns_every_line_break_into_a_space() -> None:
    """Each kind of line break becomes a space, and invisible characters go."""
    assert one_line("a\nb\r\nc\u2028d\x85e\u200b") == "a b c d e"


def test_an_empty_section_says_none() -> None:
    """No attachments, and an issue's comments when there are none, read None."""
    html = document_html("Title", "<p>Body</p>", [], [])
    assert html.endswith("<h2>Attachments</h2><p>None.</p><h2>Comments</h2><p>None.</p>")
    assert "Comments" not in document_html("Title", "<p>Body</p>", [], None)
