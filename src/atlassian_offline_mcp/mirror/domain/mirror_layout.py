"""The Markdown mirror's layout: where each file goes, and how a document is laid out.

The paths and rules are those of ``docs/reference/data-layout.md``. A document is laid
out here as plain HTML, which pandoc then writes as Markdown, so that every text the
site gave is escaped by one writer.
"""

from __future__ import annotations

import re
import unicodedata
from html import escape
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.content import BlogPost

if TYPE_CHECKING:
    from collections.abc import Sequence

    from atlassian_offline_mcp.kernel.content import ConfluenceDocument, Issue

ASSETS = PurePosixPath("assets")
TREE = "_tree.md"
# The work log's folders, by the type of their documents.
WORKLOG = {
    "entry": PurePosixPath("worklog/entries"),
    "transcript": PurePosixPath("worklog/transcripts"),
}
SLUG_LENGTH = 60
EXTENSION = re.compile(r"[a-z0-9]{1,8}")
# The name of an asset: the file's SHA-256, then its extension if it has one.
ASSET_NAME = re.compile(r"[0-9a-f]{64}(?:\.[a-z0-9]{1,8})?")
NOT_SLUG = re.compile(r"[^a-z0-9]+")
# Characters that show nothing, reorder what is shown, or cannot be written, apart from
# tab and line feed: controls, format characters (zero-width, bidirectional controls,
# tags), lone surrogates, private use and unassigned code points.
INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
KEPT_CONTROLS = frozenset("\t\n")
# Line and paragraph separators, which Markdown does not know as line breaks.
SEPARATORS = frozenset({"Zl", "Zp"})
# The variation selectors supplement, which no visible text needs.
VARIATION_SUPPLEMENT = range(0xE0100, 0xE01F0)
NONE = "<p>None.</p>"


def slug(title: str) -> str:
    """Name a title in a path: ASCII letters and digits, other runs as one ``-``.

    The title is decomposed (NFKD) and lowered, and its combining marks dropped, so that
    an accented letter keeps its base letter. It is cut at 60 characters, without a
    ``-`` at either end; it may be empty.
    """
    decomposed = unicodedata.normalize("NFKD", title).lower()
    kept = "".join(char for char in decomposed if not unicodedata.combining(char))
    return NOT_SLUG.sub("-", kept).strip("-")[:SLUG_LENGTH].rstrip("-")


def confluence_path(document: ConfluenceDocument, space: str) -> PurePosixPath:
    """Return where a page or a blog post of the space with this key is mirrored."""
    name = "-".join(part for part in (document.id, slug(document.title)) if part)
    folder = PurePosixPath("confluence", space)
    if isinstance(document, BlogPost):
        folder /= "blog"
    return folder / f"{name}.md"


def issue_path(issue: Issue) -> PurePosixPath:
    """Return where an issue is mirrored."""
    return PurePosixPath("jira", issue.project, f"{issue.key}.md")


def worklog_path(document_type: str, identifier: str, title: str) -> PurePosixPath:
    """Return where a document of the work log, of this type, id and title, is mirrored."""
    name = "-".join(part for part in (identifier, slug(title)) if part)
    return WORKLOG[document_type] / f"{name}.md"


def tree_path(space: str) -> PurePosixPath:
    """Return where the tree of the space with this key is."""
    return PurePosixPath("confluence", space, TREE)


def asset_path(digest: str, filename: str) -> PurePosixPath:
    """Return where an attached file is mirrored: its digest and its name's extension."""
    extension = PurePosixPath(filename).suffix.removeprefix(".").lower()
    if EXTENSION.fullmatch(extension):
        return ASSETS / f"{digest}.{extension}"
    return ASSETS / digest


def visible(text: str) -> str:
    """Remove the characters that show nothing, reorder what is shown, or cannot be written.

    A line or paragraph separator (U+2028, U+2029) becomes a space.
    """
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char in KEPT_CONTROLS or (
            category not in INVISIBLE_CATEGORIES and ord(char) not in VARIATION_SUPPLEMENT
        ):
            kept.append(" " if category in SEPARATORS else char)
    return "".join(kept)


def one_line(text: str) -> str:
    """Make a text one visible line: line breaks of any kind become spaces."""
    return visible(" ".join(text.splitlines()))


def document_html(
    title: str,
    body: str,
    attachments: Sequence[tuple[str, str | None]],
    comments: Sequence[tuple[str, str]] | None,
) -> str:
    """Lay out a document: its title, its body, its attachments, then its comments.

    ``body`` and each comment are normalised HTML. Each attachment is a file name and the
    link to its asset, or None when its file was not downloaded. Each comment is its
    heading and its HTML; ``comments`` is None for a document without a comments section.
    """
    items = [
        f'<li><a href="{escape(link)}">{escape(one_line(name))}</a></li>'
        if link is not None
        else f"<li>{escape(one_line(name))} (not downloaded)</li>"
        for name, link in attachments
    ]
    parts = [f"<h1>{escape(one_line(title))}</h1>", body, "<h2>Attachments</h2>"]
    parts.append(f"<ul>{''.join(items)}</ul>" if items else NONE)
    if comments is not None:
        parts.append("<h2>Comments</h2>")
        parts.extend(f"<h3>{escape(one_line(heading))}</h3>{html}" for heading, html in comments)
        if not comments:
            parts.append(NONE)
    return "".join(parts)
