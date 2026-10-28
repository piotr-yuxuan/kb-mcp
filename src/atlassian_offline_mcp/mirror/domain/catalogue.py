"""What the listings and users say beyond the snapshots, and each document's front matter.

A snapshot holds one document; the listings of its space give its place in the tree,
its fresher status and the names of the folders above it, and the users give its
author's name. The front matter of a mirrored document is built here from both, as the
table of ``docs/reference/data-layout.md`` says.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC
from functools import cached_property
from html import escape
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.content import BlogPost, ConfluenceDocument, Folder, Issue, Page
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter, PersonRole
from atlassian_offline_mcp.mirror.domain.mirror_layout import NONE, one_line

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from atlassian_offline_mcp.kernel.content import Person, Space

# The front matter's type of each kind of document.
TYPES: dict[type[ConfluenceDocument | Issue], str] = {
    Page: "page",
    BlogPost: "blogpost",
    Issue: "issue",
}


@dataclass(frozen=True)
class Catalogue:
    """The spaces, the users' names, and the documents and folders last listed.

    ``spaces`` are by id, ``names`` by account id, ``listed`` pages and blog posts by id,
    and ``folders`` by the id of the space that listed them.
    """

    spaces: Mapping[str, Space]
    names: Mapping[str, str]
    listed: Mapping[str, Page | BlogPost]
    folders: Mapping[str, Sequence[Folder]]

    @cached_property
    def nodes(self) -> dict[str, Page | Folder]:
        """Every listed page and folder, by id: the nodes of the spaces' trees."""
        folders = {folder.id: folder for each in self.folders.values() for folder in each}
        pages = {key: page for key, page in self.listed.items() if isinstance(page, Page)}
        return {**folders, **pages}

    def name(self, person: Person | None) -> str | None:
        """Name a person: by the display name given, else the users', else the account id."""
        if person is None:
            return None
        return one_line(person.display_name or self.names.get(person.account_id) or "") or (
            person.account_id
        )

    def status(self, document: ConfluenceDocument | Issue) -> str:
        """Return a document's status, from its listing when it is listed."""
        listed = self.listed.get(document.id) if isinstance(document, ConfluenceDocument) else None
        return (listed or document).status

    def breadcrumb(self, document: ConfluenceDocument | Issue) -> tuple[str, ...]:
        """Return the titles above a page, root first; an issue's parent key; else none.

        A page's parent comes from its listing when it is listed. The walk stops at a
        parent that is not listed, or at a loop.
        """
        if isinstance(document, Issue):
            return (document.parent,) if document.parent else ()
        listed = self.listed.get(document.id)
        page = listed if isinstance(listed, Page) else document
        parent = page.parent_id if isinstance(page, Page) else None
        above: list[str] = []
        while parent is not None and parent in self.nodes and parent not in above:
            above.append(parent)
            parent = self.nodes[parent].parent_id
        return tuple(one_line(self.nodes[node].title) for node in reversed(above))

    def tree(self, space: Space, links: Mapping[str, str]) -> str:
        """Lay out a space's tree as plain HTML: its pages and folders as a nested list.

        Siblings come by title, then id; a node whose parent is not listed is at the top.
        A page links its mirrored file, which ``links`` gives by page id, or says it is
        not yet mirrored; a folder is its title alone. A node on a loop is under no root,
        so it is left out.
        """
        pages = [
            page
            for page in self.listed.values()
            if isinstance(page, Page) and page.space_id == space.id
        ]
        nodes = {node.id: node for node in [*self.folders.get(space.id, ()), *pages]}
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


def front_matter(
    document: ConfluenceDocument | Issue,
    fetched_at: datetime,
    catalogue: Catalogue,
    site: str | None,
) -> FrontMatter:
    """Say what the mirror says of a document, as the layout's table does.

    Every text is one visible line; a page's space key comes from the listed spaces, and
    is None when its space is not listed, which ``FrontMatter`` refuses.
    """
    issue = document if isinstance(document, Issue) else None
    confluence = document if isinstance(document, ConfluenceDocument) else None
    space = None if confluence is None else catalogue.spaces.get(confluence.space_id)
    return FrontMatter(
        source=document.source,
        type=TYPES[type(document)],
        id=document.id,
        key=None if issue is None else issue.key,
        title=one_line(document.title),
        space=None if space is None else space.key,
        project=None if issue is None else issue.project,
        status=one_line(catalogue.status(document)),
        issue_type=None if issue is None else one_line(issue.issue_type),
        labels=tuple(one_line(label) for label in document.labels),
        people=tuple(
            PersonRole(role=role, name=catalogue.name(person), account=person.account_id)
            for role, person in (
                ("author", document.author),
                ("assignee", None if issue is None else issue.assignee),
            )
            if person is not None
        ),
        created=document.created.astimezone(UTC),
        updated=document.updated.astimezone(UTC),
        version=None if confluence is None else confluence.version,
        revision=document.revision,
        url=None if site is None else site + document.url,
        breadcrumb=catalogue.breadcrumb(document),
        fetched_at=fetched_at.astimezone(UTC),
    )
