"""The mirror: the newest snapshot of every document of the raw store, as Markdown.

It reads the store, builds every file of ``docs/reference/data-layout.md``'s Markdown
mirror and its bytes, then hands them to ``mirror_files``, which writes those that
changed. What cannot be read or converted is reported, and a run that reports anything
removes nothing, so that the last good copy of each file stays.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.markdown import TIME, dump
from atlassian_offline_mcp.adapters.mirror_files import Changes, sync
from atlassian_offline_mcp.adapters.pandoc import PandocFailedError
from atlassian_offline_mcp.adapters.raw_store import RawStore, Stored, Unreadable
from atlassian_offline_mcp.adapters.site_html import Context, MarkupError, Mirrored, normalise
from atlassian_offline_mcp.domain.catalogue import Catalogue, front_matter
from atlassian_offline_mcp.domain.content import (
    BlogPost,
    ConfluenceDocument,
    Issue,
    Page,
    RefusedError,
)
from atlassian_offline_mcp.domain.mirror_layout import (
    asset_path,
    confluence_path,
    document_html,
    issue_path,
    tree_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path, PurePosixPath

    from atlassian_offline_mcp.domain.content import Folder

KINDS: tuple[type[Page | BlogPost | Issue], ...] = (Page, BlogPost, Issue)
# A comment's headings sit under its own third-level heading.
COMMENT_SHIFT = 3
UNKNOWN_AUTHOR = "unknown author"
# What building one document's file can meet: a value the front matter refuses, a text
# no file can hold, markup the parser cannot read whole, pandoc failing. All but the
# second name no content.
DOCUMENT_ERRORS = (ValueError, PandocFailedError)
NAMED_ERRORS = (RefusedError, MarkupError, PandocFailedError)


@dataclass(frozen=True)
class Problem:
    """Something not mirrored: where it is in the store, and why, without content."""

    where: str
    reason: str


@dataclass(frozen=True)
class Outcome:
    """What a run did: documents mirrored, files changed, placeholders, and problems."""

    documents: int
    changes: Changes
    unsupported: Counter[str]
    problems: tuple[Problem, ...]


@dataclass(frozen=True)
class Placed:
    """A stored snapshot, and the file where its document is mirrored."""

    stored: Stored
    path: PurePosixPath

    @property
    def document(self) -> ConfluenceDocument | Issue:
        """The document of the snapshot."""
        document = self.stored.snapshot.document
        if not isinstance(document, ConfluenceDocument | Issue):
            message = f"{type(document).__name__}: not a document the mirror knows"
            raise TypeError(message)
        return document

    @property
    def handle(self) -> str:
        """Name the document as links and images do: its key for Jira, else its id."""
        document = self.document
        return document.key if isinstance(document, Issue) else document.id


def readable[T](items: Iterable[T | Unreadable], problems: list[Problem]) -> list[T]:
    """Keep what the store could read, and report each item it could not."""
    kept: list[T] = []
    for item in items:
        if isinstance(item, Unreadable):
            problems.append(Problem(item.where, item.reason))
        else:
            kept.append(item)
    return kept


def where(store: RawStore, stored: Stored) -> str:
    """Say where a snapshot is within the store."""
    return stored.folder.relative_to(store.root).as_posix()


def read_catalogue(store: RawStore, problems: list[Problem]) -> tuple[Catalogue, set[str]]:
    """Read the spaces, users and listings; also return the spaces whose listing failed."""
    spaces = {space.id: space for space in readable(store.spaces(), problems)}
    users = readable(store.users(), problems)
    listed: dict[str, Page | BlogPost] = {}
    folders: dict[str, tuple[Folder, ...]] = {}
    damaged: set[str] = set()
    for space_id in spaces:
        before = len(problems)
        for kind in (Page, BlogPost):
            entries = readable(store.listed(space_id, kind), problems)
            listed.update((each.id, each) for each in entries)
        folders[space_id] = tuple(readable(store.folders(space_id), problems))
        if len(problems) > before:
            damaged.add(space_id)
    names = {user.account_id: user.display_name for user in users if user.display_name}
    return Catalogue(spaces, names, listed, folders), damaged


def place(store: RawStore, catalogue: Catalogue, problems: list[Problem]) -> list[Placed]:
    """Read the newest snapshot of every document, and say where each is mirrored.

    A page or a blog post whose space is not listed has no folder, and is reported.
    """
    placed: list[Placed] = []
    for stored in (item for kind in KINDS for item in readable(store.latest(kind), problems)):
        document = stored.snapshot.document
        if isinstance(document, Issue):
            placed.append(Placed(stored, issue_path(document)))
        elif isinstance(document, ConfluenceDocument) and document.space_id in catalogue.spaces:
            key = catalogue.spaces[document.space_id].key
            placed.append(Placed(stored, confluence_path(document, key)))
        else:
            problems.append(Problem(where(store, stored), "space not listed"))
    return placed


def index(
    placed: Iterable[Placed], store: RawStore, site: str | None
) -> tuple[Mirrored, dict[PurePosixPath, Path]]:
    """Return what the mirror holds for links and images, and the file of each asset."""
    files: dict[tuple[str, str], PurePosixPath | None] = {}
    names: dict[tuple[str, str], PurePosixPath | None] = {}
    assets: dict[PurePosixPath, Path] = {}
    for each in placed:
        for attachment in each.stored.snapshot.attachments:
            digest = each.stored.blobs.get(attachment.id)
            asset = None if digest is None else asset_path(digest, attachment.filename)
            files[each.handle, attachment.id] = asset
            names.setdefault((each.handle, attachment.filename), asset)
            if digest is not None and asset is not None:
                assets[asset] = store.blob(digest)
    documents = {each.handle: each.path for each in placed}
    return Mirrored(site, documents, files, names), assets


def document_file(
    placed: Placed, catalogue: Catalogue, context: Context, markdown: Callable[[str], str]
) -> bytes:
    """Return the bytes of one document's file: its front matter, then its Markdown."""
    snapshot, document = placed.stored.snapshot, placed.document
    matter = front_matter(document, placed.stored.fetched_at, catalogue, context.mirrored.site)
    attachments = [
        (each.filename, None if asset is None else context.relative(asset))
        for each in snapshot.attachments
        for asset in [context.mirrored.files.get((placed.handle, each.id))]
    ]
    comments = None
    if isinstance(document, Issue):
        under = replace(context, shift=COMMENT_SHIFT)
        comments = [
            (
                (
                    f"{catalogue.name(each.author) or UNKNOWN_AUTHOR},"
                    f" {each.created.astimezone(UTC).strftime(TIME)}"
                ),
                normalise(each.html, under),
            )
            for each in snapshot.comments
        ]
    body = document_html(document.title, normalise(snapshot.html, context), attachments, comments)
    return dump(matter, markdown(body)).encode()


def mirror(
    store: RawStore, docs: Path, site: str | None, markdown: Callable[[str], str]
) -> Outcome:
    """Mirror the raw store into ``docs``, with ``markdown`` writing HTML as Markdown."""
    problems: list[Problem] = []
    catalogue, damaged = read_catalogue(store, problems)
    placed = place(store, catalogue, problems)
    mirrored, assets = index(placed, store, site)
    wanted: dict[PurePosixPath, bytes | Path] = {**assets}
    unsupported: Counter[str] = Counter()
    for each in placed:
        context = Context(each.handle, each.path, mirrored, unsupported=unsupported)
        try:
            wanted[each.path] = document_file(each, catalogue, context, markdown)
        except DOCUMENT_ERRORS as error:
            reason = str(error) if isinstance(error, NAMED_ERRORS) else type(error).__name__
            problems.append(Problem(where(store, each.stored), reason))
    for space in catalogue.spaces.values():
        tree = tree_path(space.key)
        # Only the files built: a page whose file failed is not yet mirrored.
        links = {
            each.document.id: posixpath.relpath(each.path, tree.parent)
            for each in placed
            if isinstance(each.document, Page)
            and each.document.space_id == space.id
            and each.path in wanted
        }
        try:
            if space.id not in damaged:
                wanted[tree] = markdown(catalogue.tree(space, links)).encode()
        except PandocFailedError as error:
            problems.append(Problem(f"confluence/spaces/{space.id}", str(error)))
    written = sum(1 for each in placed if each.path in wanted)
    return Outcome(written, sync(docs, wanted, remove=not problems), unsupported, tuple(problems))
