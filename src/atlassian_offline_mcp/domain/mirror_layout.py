"""The Markdown mirror's layout: where each file goes, and how each file is laid out.

The paths and rules are those of ``docs/reference/data-layout.md``. A document and a tree
are laid out here as plain HTML, which pandoc then writes as Markdown, so that every
text the site gave is escaped by one writer.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from html import escape
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from atlassian_offline_mcp.domain.content import BlogPost, Folder, Page

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from atlassian_offline_mcp.domain.content import ConfluenceDocument, Issue, Space

ASSETS = PurePosixPath("assets")
TREE = "_tree.md"
SLUG_LENGTH = 60
EXTENSION = re.compile(r"[a-z0-9]{1,8}")
NOT_SLUG = re.compile(r"[^a-z0-9]+")
# Characters that show nothing or reorder what is shown, apart from tab and line feed:
# format characters (zero-width, bidirectional controls, tags) and controls.
INVISIBLE_CATEGORIES = frozenset({"Cf", "Cc"})
KEPT_CONTROLS = frozenset("\t\n")
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
    """Remove the characters that show nothing, or reorder what is shown."""
    return "".join(
        char
        for char in text
        if char in KEPT_CONTROLS
        or (
            unicodedata.category(char) not in INVISIBLE_CATEGORIES
            and ord(char) not in VARIATION_SUPPLEMENT
        )
    )


def one_line(text: str) -> str:
    """Make a text one visible line: line breaks of any kind become spaces."""
    return visible(" ".join(text.splitlines()))


def breadcrumb(parent_id: str | None, nodes: Mapping[str, Page | Folder]) -> tuple[str, ...]:
    """Return the titles of the ancestors from this parent up, root first.

    The walk stops at a parent that is not among the nodes, or at a loop.
    """
    titles: list[str] = []
    seen: set[str] = set()
    while parent_id is not None and parent_id in nodes and parent_id not in seen:
        seen.add(parent_id)
        titles.append(one_line(nodes[parent_id].title))
        parent_id = nodes[parent_id].parent_id
    return tuple(reversed(titles))


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
        f'<li><a href="{escape(link)}">{escape(name)}</a></li>'
        if link is not None
        else f"<li>{escape(name)} (not downloaded)</li>"
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


def tree_html(
    space: Space, pages: Sequence[Page], folders: Sequence[Folder], links: Mapping[str, str]
) -> str:
    """Lay out a space's tree: its pages and folders as a nested list.

    Siblings come by title, then id; a node whose parent is not listed is at the top. A
    page links its mirrored file, given by ``links``, or says it is not yet mirrored; a
    folder is its title alone. A node on a loop is under no root, so it is left out.
    """
    nodes: dict[str, Page | Folder] = {node.id: node for node in [*folders, *pages]}
    children: defaultdict[str | None, list[Page | Folder]] = defaultdict(list)
    for node in nodes.values():
        children[node.parent_id if node.parent_id in nodes else None].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (one_line(node.title).casefold(), node.id))
    html = [f"<h1>{escape(one_line(space.name))} ({escape(space.key)})</h1>"]
    if not children[None]:
        return html[0] + NONE
    # Depth first, without recursion: one iterator of siblings per open list.
    html.append("<ul>")
    stack = [iter(children[None])]
    while stack:
        node = next(stack[-1], None)
        if node is None:
            stack.pop()
            html.append("</ul></li>" if stack else "</ul>")
            continue
        title = escape(one_line(node.title))
        if isinstance(node, Folder):
            html.append(f"<li>{title}")
        elif node.id in links:
            html.append(f'<li><a href="{escape(links[node.id])}">{title}</a>')
        else:
            html.append(f"<li>{title} (not yet mirrored)")
        if children[node.id]:
            html.append("<ul>")
            stack.append(iter(children[node.id]))
        else:
            html.append("</li>")
    return "".join(html)
