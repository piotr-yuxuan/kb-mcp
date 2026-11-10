"""Where Confluence's and Jira's files go in the mirror, and how a document is laid out.

The paths and rules are those of ``docs/reference/data-layout.md``. A document is laid
out here as plain HTML, which pandoc then writes as Markdown, so that every text the
site gave is escaped by one writer.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from kb_mcp.kernel.names import ASSETS
from kb_mcp.kernel.slug import slug
from kb_mcp.mirror.domain.mirror_text import one_line
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.sources.atlassian.fetch.domain.content import ConfluenceDocument, Issue

TREE = "_tree.md"
EXTENSION = re.compile(r"[a-z0-9]{1,8}")
# The name of an asset: the file's SHA-256, then its extension if it has one.
ASSET_NAME = re.compile(r"[0-9a-f]{64}(?:\.[a-z0-9]{1,8})?")
NONE = "<p>None.</p>"


def confluence_path(source: str, document: ConfluenceDocument, space: str) -> PurePosixPath:
    """Return where a source's page or blog post of the space with this key goes in the mirror."""
    name = "-".join(part for part in (document.id, slug(document.title)) if part)
    folder = PurePosixPath(source, space)
    if isinstance(document, BlogPost):
        folder /= "blog"
    return folder / f"{name}.md"


def issue_path(source: str, issue: Issue) -> PurePosixPath:
    """Return where a source's issue goes in the mirror."""
    return PurePosixPath(source, issue.project, f"{issue.key}.md")


def tree_path(source: str, space: str) -> PurePosixPath:
    """Return where the tree of a source's space with this key is."""
    return PurePosixPath(source, space, TREE)


def asset_path(digest: str, filename: str) -> PurePosixPath:
    """Return where an attached file goes in the mirror: its digest and its name's extension."""
    extension = PurePosixPath(filename).suffix.removeprefix(".").lower()
    if EXTENSION.fullmatch(extension):
        return PurePosixPath(ASSETS, f"{digest}.{extension}")
    return PurePosixPath(ASSETS, digest)


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
