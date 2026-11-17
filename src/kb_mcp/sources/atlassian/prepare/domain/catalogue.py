"""What the listings and site users say beyond the snapshots, and each document's front matter.

A snapshot holds one document and its comments; the listings of its space give its
place in the tree, its fresher status and the names of the folders above it, and the
site users give its people's names. The front matter of a document of the mirror is built
here from all of them, as the table of ``docs/reference/data-layout.md`` says.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from functools import cached_property
from html import escape
from typing import TYPE_CHECKING, Self

from pydantic import Field, model_validator

from kb_mcp.kernel.names import ATLASSIAN_ISSUER, RefusedError, require
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import FrontMatter, Mention, document_id, scope_name
from kb_mcp.mirror.domain.mirror_text import one_line
from kb_mcp.sources.atlassian.fetch.domain.content import (
    REVISION,
    BlogPost,
    ConfluenceDocument,
    Folder,
    Issue,
    Page,
    Space,
    time_revision,
    version_revision,
)
from kb_mcp.sources.atlassian.fetch.domain.coverage import Scope
from kb_mcp.sources.atlassian.fetch.domain.deletions import DocumentKey, Tombstone
from kb_mcp.sources.atlassian.fetch.domain.names import (
    BLOGPOST,
    FOLDER,
    ISSUE,
    PAGE,
    PROJECT,
    SPACE,
)
from kb_mcp.sources.atlassian.fetch.domain.period import EPOCH
from kb_mcp.sources.atlassian.prepare.domain.layout import NONE

if TYPE_CHECKING:
    from kb_mcp.sources.atlassian.fetch.domain.content import SiteUser, Snapshot

# The roles that each document type takes, by its name, in the order of the roles.
TYPE_ROLES = {
    PAGE.name: ("author", "commenter"),
    BLOGPOST.name: ("author", "commenter"),
    ISSUE.name: ("author", "creator", "assignee", "commenter"),
    FOLDER.name: (),
}
# The container types, by name, as Confluence and Jira declare them: no body, no section.
CONTAINERS = tuple(
    each.name for each in (*SPACE.document_types, *PROJECT.document_types) if each.container
)
# Keys that the documents of one scope type alone have, always: a space's, a project's.
ONLY = {"version": SPACE, "key": PROJECT, "subtype": PROJECT}


class AtlassianFrontMatter(FrontMatter):
    """The front matter of a document of Confluence or Jira: every source's rules, and theirs."""

    @model_validator(mode="after")
    def check_atlassian(self) -> Self:
        """Refuse what the layout's table rules out for Confluence and Jira.

        A type of neither, a key that only another type has, or that its type always has
        and it lacks, but a container's version, a scope not of its type's scope type or off
        its key's rule, a revision off ``REVISION``, and a role that its type does not
        take.
        """
        if self.type not in {
            each.name for each in (*SPACE.document_types, *PROJECT.document_types)
        }:
            message = "type: not one of Confluence's or Jira's"
            raise RefusedError(message)
        for name, scope_type in ONLY.items():
            held = self.type in {each.name for each in scope_type.document_types}
            given = getattr(self, name) is not None
            # A container's response may give no version, which it then lacks.
            if given != held and not (name == "version" and self.type in CONTAINERS):
                message = f"{name}: only and always in a {scope_type.name}"
                raise RefusedError(message)
        type_name, key = self.scope.split(":", 1)
        scope_type = SPACE if self.type in {each.name for each in SPACE.document_types} else PROJECT
        if type_name != scope_type.name or scope_type.key is None:
            message = "scope: not of its type's scope type"
            raise RefusedError(message)
        require(scope_type.key, key, "scope")
        require(REVISION, self.revision, "revision")
        if any(person.role not in TYPE_ROLES[self.type] for person in self.people):
            message = "people: a role that its type does not take"
            raise RefusedError(message)
        return self


class Catalogue(Record):
    """The spaces, the site users' names, the documents and folders last listed, the issues.

    ``spaces`` are by id, ``names`` by account id, ``listed`` pages and blog posts by id,
    ``folders`` by the id of the space that listed them, ``issues``, those of the raw
    store, by id, ``as_of`` each scope's as-of time, as its coverage records it, and
    ``gone`` the tombstones confirmed, by document.
    """

    spaces: Mapping[str, Space]
    names: Mapping[str, str]
    listed: Mapping[str, Page | BlogPost]
    folders: Mapping[str, Sequence[Folder]]
    issues: Mapping[str, Issue] = Field(default_factory=dict)
    as_of: Mapping[Scope, datetime] = Field(default_factory=dict)
    gone: Mapping[DocumentKey, Tombstone] = Field(default_factory=dict)

    @cached_property
    def nodes(self) -> dict[str, Page | Folder]:
        """Every listed page and folder, by id: the nodes of the spaces' trees."""
        folders = {folder.id: folder for each in self.folders.values() for folder in each}
        pages = {key: page for key, page in self.listed.items() if isinstance(page, Page)}
        return {**folders, **pages}

    def name(self, person: SiteUser | None) -> str | None:
        """Name a person: by the display name given, else the site users', else the account id."""
        if person is None:
            return None
        return one_line(person.display_name or self.names.get(person.account_id) or "") or (
            person.account_id
        )

    def status(self, document: ConfluenceDocument | Issue) -> str:
        """Return a document's status, from its listing when it is listed."""
        listed = self.listed.get(document.id) if isinstance(document, ConfluenceDocument) else None
        return (listed or document).status

    def parent(self, document: ConfluenceDocument | Issue | Folder) -> str | None:
        """Give the id of a page's or a folder's parent, a page or a folder, or an issue's.

        Else None. A page's comes from its listing when it is listed.
        """
        if isinstance(document, Issue):
            return None if document.parent is None else document.parent.id
        listed = self.listed.get(document.id)
        node = listed if isinstance(listed, Page) else document
        return node.parent_id if isinstance(node, Page | Folder) else None

    def breadcrumb(self, document: ConfluenceDocument | Issue | Folder) -> tuple[str, ...]:
        """Return the titles above a page, a folder or an issue, root first; else none.

        A page's parent comes from its listing when it is listed, and the walk stops at a
        parent that is not listed. An issue's parent's title is its own response's, and
        each further one its parent's, so that the walk stops above a parent not in
        ``issues``. Either stops at a loop.
        """
        if isinstance(document, Issue):
            titles: list[str] = []
            seen, issue = {document.id}, document
            while issue is not None and issue.parent is not None and issue.parent.id not in seen:
                titles.append(one_line(issue.parent.title))
                seen.add(issue.parent.id)
                issue = self.issues.get(issue.parent.id)
            return tuple(reversed(titles))
        parent = self.parent(document)
        above: list[str] = []
        while parent is not None and parent in self.nodes and parent not in above:
            above.append(parent)
            parent = self.nodes[parent].parent_id
        return tuple(one_line(self.nodes[node].title) for node in reversed(above))

    def tree(self, space: Space, links: Mapping[str, str]) -> str:
        """Lay out a space's tree as plain HTML: its pages and folders as a nested list.

        Siblings come by title, then id; a node whose parent is not listed is at the top.
        A page or a folder links its file in the mirror, which ``links`` gives by id; a
        page without one says "not yet mirrored", and a folder is its title alone. A node
        on a loop is under no root, so it is left out.
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
            if node.id in links:
                html.append(f'<li><a href="{escape(links[node.id])}">{title}</a>')
            elif isinstance(node, Folder):
                html.append(f"<li>{title}")
            else:
                html.append(f"<li>{title} (not yet mirrored)")
            if children[node.id]:
                html.append("<ul>")
                stack.append(iter(children[node.id]))
            else:
                html.append("</li>")
        return "".join(html)


def identity(person: SiteUser) -> str:
    """Give a site user's identity: the Atlassian issuer and their account id."""
    return f"{ATLASSIAN_ISSUER}:{person.account_id}"


def folder_front_matter(
    source: str, folder: Folder, space: Space, catalogue: Catalogue
) -> FrontMatter:
    """Say what the mirror says of a source's folder in a space: a container, with no body.

    Its scope is the space's, its parent and its breadcrumb are as a page's would be,
    and its revision is its version's. It names no people, labels nor links, and has no
    address: its response gives no web page. A folder whose response gave no status has
    none; no update time, the epoch, which no content of the site precedes, so that its
    file stays as it is from one run to the next; no creation time, its update time; no
    version, none, and a revision by its update time.
    """
    parent = catalogue.parent(folder)
    updated = folder.updated or EPOCH
    return AtlassianFrontMatter(
        source=source,
        type=FOLDER.name,
        id=folder.id,
        key=None,
        title=one_line(folder.title),
        scope=scope_name(SPACE.name, space.key),
        status=one_line(folder.status or ""),
        subtype=None,
        labels=(),
        people=(),
        parent=None if parent is None else document_id(source, parent),
        links=(),
        created=(folder.created or updated).astimezone(UTC),
        updated=updated.astimezone(UTC),
        version=folder.version,
        revision=time_revision(updated)
        if folder.version is None
        else version_revision(folder.version),
        url=None,
        breadcrumb=catalogue.breadcrumb(folder),
    )


def front_matter(
    source: str, snapshot: Snapshot, catalogue: Catalogue, site: str | None
) -> FrontMatter:
    """Say what the mirror says of a source's snapshot, as the layout's table does.

    Every text is one visible line; a page's space key comes from the listed spaces, and
    one whose space is not listed is refused. Each commenter comes once, by their first
    comment, with the times of their comments ascending; a comment without an author
    names nobody. Raises TypeError for a document that is neither Confluence's nor
    Jira's.
    """
    document, comments = snapshot.document, snapshot.comments
    if not isinstance(document, ConfluenceDocument | Issue):
        message = f"{type(document).__name__}: not a document the mirror knows"
        raise TypeError(message)
    issue = document if isinstance(document, Issue) else None
    confluence = document if isinstance(document, ConfluenceDocument) else None
    space = None if confluence is None else catalogue.spaces.get(confluence.space_id)
    if confluence is not None and space is None:
        message = "scope: the space is not listed"
        raise RefusedError(message)
    parent = catalogue.parent(document)
    # Each commenter's comment times, by name and identity, the first comment first.
    said: dict[tuple[str, str], list[datetime]] = {}
    for comment in sorted(comments, key=lambda each: each.created):
        if comment.author is not None:
            commenter = (catalogue.name(comment.author), identity(comment.author))
            said.setdefault(commenter, []).append(comment.created.astimezone(UTC))
    sole = [
        Mention(role=role, name=catalogue.name(person), identity=identity(person))
        for role, person in (
            ("author", document.author),
            ("creator", None if issue is None else issue.creator),
            ("assignee", None if issue is None else issue.assignee),
        )
        if person is not None
    ]
    commenters = [
        Mention(role="commenter", name=name, identity=held, at=tuple(at))
        for (name, held), at in said.items()
    ]
    return AtlassianFrontMatter(
        source=source,
        type=document.document_type.name,
        id=document.id,
        key=None if issue is None else issue.key,
        title=one_line(document.title),
        scope=(
            scope_name(PROJECT.name, issue.project)
            if space is None
            else scope_name(SPACE.name, space.key)
        ),
        status=one_line(catalogue.status(document)),
        subtype=None if issue is None else one_line(issue.issue_type),
        labels=tuple(one_line(label) for label in document.labels),
        people=(*sole, *commenters),
        parent=None if parent is None else document_id(source, parent),
        links=(),
        created=document.created.astimezone(UTC),
        updated=document.updated.astimezone(UTC),
        version=None if confluence is None else confluence.version,
        revision=document.revision,
        url=None if site is None else site + document.site_path,
        breadcrumb=catalogue.breadcrumb(document),
    )
