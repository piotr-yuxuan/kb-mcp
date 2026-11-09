"""The newest snapshot of every document of one Atlassian source, as Markdown.

Confluence and Jira are prepared apart, each by its resource types. Each reads the
whole store and places every document, so that a link or an image of either reaches its
file, then builds the source's own files of ``docs/reference/data-layout.md``'s Markdown
mirror and their bytes, and hands them to ``mirror_files``, which writes those that
changed. Pandoc's conversions come through the source's rows of the cache of
``conversions``, which converts only what it has not converted before. What cannot be
read or converted is reported by the source it belongs to, and a source that reports
anything removes none of its files and none of its conversions, so that the last good
copy of each stays; an attached file stays while any document's file links it. Reading,
building and writing are each a span; each document built is counted and timed, never a
span, as ``docs/reference/telemetry/prepare.md`` lists it.
"""

from __future__ import annotations

import posixpath
import time
from collections import Counter
from copy import replace
from datetime import UTC
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace
from pydantic import Field

from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.outcome import Problem
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.adapters.instruments import CONVERSION_DURATION, DOCUMENTS
from kb_mcp.mirror.adapters.markdown import TIME, dump
from kb_mcp.mirror.adapters.mirror_files import Changes, write_changed
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.mirror.domain.mirror import ref_of
from kb_mcp.observability.adapters.progress import task
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import (
    UNREADABLE,
    RawStore,
    StoredSnapshot,
    reason,
)
from kb_mcp.sources.atlassian.fetch.domain.content import (
    DOCUMENT_CLASSES,
    BlogPost,
    ConfluenceDocument,
    Issue,
    Page,
)
from kb_mcp.sources.atlassian.fetch.domain.period import EPOCH
from kb_mcp.sources.atlassian.prepare.adapters.owned import attached, owned, unlinked
from kb_mcp.sources.atlassian.prepare.adapters.site_html import (
    LinkTargets,
    MarkupError,
    RenderContext,
    normalise,
)
from kb_mcp.sources.atlassian.prepare.domain.catalogue import Catalogue, front_matter
from kb_mcp.sources.atlassian.prepare.domain.layout import (
    asset_path,
    confluence_path,
    document_html,
    issue_path,
    tree_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from pathlib import Path

    from kb_mcp.kernel.output import Detail
    from kb_mcp.mirror.adapters.conversions import Conversions
    from kb_mcp.sources.atlassian.fetch.domain.content import Folder

# The document classes that each source prepares, by its name, in the order that it is
# prepared, as each class names its source: Confluence's pages and blog posts, with each
# space's tree, then Jira's issues.
PREPARED: dict[str, tuple[type[Page | BlogPost | Issue], ...]] = {
    source: tuple(
        document_class for document_class in DOCUMENT_CLASSES if document_class.source == source
    )
    for source in dict.fromkeys(document_class.source for document_class in DOCUMENT_CLASSES)
}
# Each source by all of its document classes, which a prepare takes whole: it removes the
# files of them all (``owned``), so a prepare of some of them would remove the files of the
# others.
SOURCE_OF = {document_classes: source for source, document_classes in PREPARED.items()}
# A comment's headings sit under its own third-level heading.
COMMENT_SHIFT = 3
UNKNOWN_AUTHOR = "unknown author"
# What building one document's file can meet: a value the front matter refuses, a text
# no file can hold, markup the parser cannot read whole, pandoc failing. All but the
# second name no content.
DOCUMENT_ERRORS = (ValueError, PandocFailedError)
NAMED_ERRORS = (RefusedError, MarkupError, PandocFailedError)
TRACER = trace.get_tracer(__name__)


class AtlassianPrepareOutcome(Record):
    """What a run did: documents prepared, conversions, files changed, placeholders, problems.

    ``converted`` counts the conversions pandoc ran, ``reused`` those the cache gave: a
    document's file and a space's tree are one each. ``problems`` are the source's own;
    ``elsewhere`` holds, by source, those that it found reading another's, which fail
    nothing of its own, though a link or an image of its files may then not reach that
    source's document.
    """

    documents: int
    converted: int
    reused: int
    changes: Changes
    unsupported: Counter[str]
    problems: tuple[Problem, ...]
    elsewhere: dict[str, tuple[Problem, ...]] = Field(default_factory=dict)

    def text(self, summary: Detail) -> str:
        """Write the counts of documents, of conversions run and reused, of files, of problems.

        In detail, what the mirror does not show, by name, comes before the problems;
        those of another source follow, when any.
        """
        unsupported = sorted(self.unsupported.items()) if summary == "detailed" else []
        return (
            f"documents: {self.documents}\n"
            f"converted by pandoc: {self.converted}\n"
            f"reused from the cache: {self.reused}\n"
            f"files written: {self.changes.written}\n"
            f"files unchanged: {self.changes.unchanged}\n"
            f"files removed: {self.changes.removed}\n"
            + "".join(f"not shown, {name}: {count}\n" for name, count in unsupported)
            + f"problems: {len(self.problems)}\n"
            + "".join(
                f"problems of {name}, read here: {len(each)}\n"
                for name, each in self.elsewhere.items()
            )
        )


class Placed(Record):
    """A stored snapshot, and its document's file in the mirror."""

    stored: StoredSnapshot
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
    def ref(self) -> str:
        """Name the document as links and images do: its key for Jira, else its id."""
        document = self.document
        return ref_of(document.key if isinstance(document, Issue) else None, document.id)


def readable[T](items: Iterable[T | Problem], problems: list[Problem]) -> list[T]:
    """Keep what the raw store could read, and report each item it could not."""
    kept: list[T] = []
    for item in items:
        if isinstance(item, Problem):
            problems.append(item)
        else:
            kept.append(item)
    return kept


def where(store: RawStore, stored: StoredSnapshot) -> str:
    """Say where a snapshot is within the store."""
    return stored.folder.relative_to(store.root).as_posix()


def listed_at(store: RawStore, space_id: str, problems: list[Problem]) -> datetime:
    """Say when a space was listed: the epoch when no run said so, or the record is damaged."""
    try:
        return store.listed_at(space_id) or EPOCH
    except UNREADABLE as error:
        problems.append(
            Problem(where=f"confluence/spaces/{space_id}/listed_at.json", reason=reason(error))
        )
        return EPOCH


def read_catalogue(
    store: RawStore, problems: list[Problem]
) -> tuple[Catalogue, set[str], dict[str, datetime]]:
    """Read the spaces, site users and listings.

    Also return the spaces whose listing failed, and when each space was listed.
    """
    spaces = {space.id: space for space in readable(store.spaces(), problems)}
    users = readable(store.users(), problems)
    times = {space_id: listed_at(store, space_id, problems) for space_id in spaces}
    listed: dict[str, Page | BlogPost] = {}
    folders: dict[str, tuple[Folder, ...]] = {}
    damaged: set[str] = set()
    # The freshest listing last, so that it wins for a document that two listings name.
    for space_id in sorted(spaces, key=times.__getitem__):
        before = len(problems)
        for document_class in (Page, BlogPost):
            entries = readable(store.listed(space_id, document_class), problems)
            listed.update((each.id, each) for each in entries)
        folders[space_id] = tuple(readable(store.folders(space_id), problems))
        if len(problems) > before:
            damaged.add(space_id)
    names = {user.account_id: user.display_name for user in users if user.display_name}
    return Catalogue(spaces=spaces, names=names, listed=listed, folders=folders), damaged, times


def place(
    store: RawStore,
    catalogue: Catalogue,
    times: Mapping[str, datetime],
    problems: Mapping[str, list[Problem]],
) -> tuple[list[Placed], dict[PurePosixPath, PurePosixPath | None]]:
    """Read the newest snapshot of every document, and say where each goes in the mirror.

    A page or a blog post goes to the space whose freshest listing names it, before the
    one its snapshot names, everywhere the mirror uses its space; one whose space is not
    listed has no folder, and is reported. A document confirmed gone is left out, unless
    a listing taken after it answered gone names it again. Each problem goes to the list
    of the source it belongs to, by its name, in ``problems``; the tombstones are
    Confluence's. Also return the files that must go even when the source reports
    problems: those of documents gone (to None), and the old file of a document that
    moved (to its new file).
    """
    placed: list[Placed] = []
    retired: dict[PurePosixPath, PurePosixPath | None] = {}
    try:
        gone = {key: stone for key, stone in store.tombstones().items() if stone.confirmed}
    except UNREADABLE as error:
        problems[ConfluenceDocument.source].append(
            Problem(where="tombstones.json", reason=reason(error))
        )
        gone = {}
    for found in (
        item
        for document_class in DOCUMENT_CLASSES
        for item in readable(store.latest(document_class), problems[document_class.source])
    ):
        stored, document = found, found.snapshot.document
        if isinstance(document, Issue):
            placed.append(Placed(stored=stored, path=issue_path(document)))
            continue
        if not isinstance(document, ConfluenceDocument):
            continue
        before = catalogue.spaces.get(document.space_id)
        listed = catalogue.listed.get(document.id)
        stone = gone.get((document.resource_type, document.id))
        # Gone, unless a listing taken after its first answer of gone names it again.
        named = times.get(listed.space_id) if listed is not None else None
        is_gone = stone is not None and (named is None or named <= stone.first_gone)
        moves = listed is not None and listed.space_id != document.space_id
        old = confluence_path(document, before.key) if before is not None else None
        if is_gone:
            if old is not None:
                retired[old] = None
            continue
        if moves:
            moved = replace(document, space_id=listed.space_id)
            stored = replace(stored, snapshot=replace(stored.snapshot, document=moved))
            document = moved
        if document.space_id in catalogue.spaces:
            key = catalogue.spaces[document.space_id].key
            placed.append(Placed(stored=stored, path=confluence_path(document, key)))
            if moves and old is not None:
                retired[old] = confluence_path(document, key)
        else:
            problems[document.source].append(
                Problem(where=where(store, stored), reason="space not listed")
            )
    return placed, retired


def link_targets(
    placed: Iterable[Placed], store: RawStore, site: str | None
) -> tuple[LinkTargets, dict[PurePosixPath, Path]]:
    """Return what the mirror holds for links and images, and the file of each asset."""
    files: dict[tuple[str, str], PurePosixPath | None] = {}
    names: dict[tuple[str, str], PurePosixPath | None] = {}
    assets: dict[PurePosixPath, Path] = {}
    for each in placed:
        for attachment in each.stored.snapshot.attachments:
            digest = each.stored.blobs.get(attachment.id)
            asset = None if digest is None else asset_path(digest, attachment.filename)
            files[each.ref, attachment.id] = asset
            names.setdefault((each.ref, attachment.filename), asset)
            if digest is not None and asset is not None:
                assets[asset] = store.blob(digest)
    documents = {each.ref: each.path for each in placed}
    return LinkTargets(site=site, documents=documents, files=files, names=names), assets


def document_file(
    placed: Placed, catalogue: Catalogue, context: RenderContext, conversions: Conversions
) -> bytes:
    """Return the bytes of one document's file: its front matter, then its Markdown."""
    snapshot, document = placed.stored.snapshot, placed.document
    matter = front_matter(
        document, snapshot.comments, placed.stored.fetched_at, catalogue, context.link_targets.site
    )
    attachments = [
        (each.filename, None if asset is None else context.relative(asset))
        for each in snapshot.attachments
        for asset in [context.link_targets.files.get((placed.ref, each.id))]
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
    return dump(matter, conversions.markdown(body)).encode()


def prepare_atlassian(
    store: RawStore,
    docs: Path,
    site: str | None,
    conversions: Conversions,
    document_classes: tuple[type[Page | BlogPost | Issue], ...],
) -> AtlassianPrepareOutcome:
    """Write the documents of ``document_classes``, one source's, from the raw store to ``docs``.

    ``document_classes`` are all of one source's, as ``PREPARED`` gives them; any other
    raises KeyError, a caller's error, before anything is read. ``conversions`` writes HTML
    as Markdown, through the source's rows of the cache.
    Every document of the raw store is placed, so that links and images reach the other
    source's files, but only those of ``document_classes`` are built and written, with
    the files they attach, and each space's tree when pages are among them. The source then
    removes its files that are no longer wanted, and prunes its conversions that this
    run did not use, unless it reports a problem, those that it found reading the other
    source's coming back apart from its own. An attached file that no placed
    document wants goes next, while no file left of either source links it and no
    problem was found, of either source: a document that cannot be read or placed wants
    none of its files, and a last good copy links what its document wanted. The task
    named after the source, as ``confluence documents``, reports the documents' files
    built, each by its path. The spans ``prepare.read``, ``prepare.build`` and
    ``prepare.write`` hold reading the raw store, building the files and writing them, the
    prune included; ``prepare.placed``
    and ``prepare.written`` say at INFO, with the source, how many of its documents were
    placed, and files written and conversions run, reused and pruned, ``prepare.document``
    at DEBUG each document built, by its path, id and title.
    """
    log = structlog.get_logger()
    source = SOURCE_OF[document_classes]
    # The problems found, by the source they belong to: the catalogue's are Confluence's.
    found: dict[str, list[Problem]] = {
        document_class.source: [] for document_class in DOCUMENT_CLASSES
    }
    problems = found[source]
    with TRACER.start_as_current_span("prepare.read"):
        catalogue, damaged, times = read_catalogue(store, found[ConfluenceDocument.source])
        placed, retired = place(store, catalogue, times, found)
        linked, assets = link_targets(placed, store, site)
    own = [each for each in placed if isinstance(each.document, document_classes)]
    _, files = link_targets(own, store, site)
    log.info(
        "prepare.placed",
        source=source,
        documents=len(own),
        assets=len(files),
        problems=len(problems),
    )
    wanted: dict[PurePosixPath, bytes | Path] = {**files}
    unsupported: Counter[str] = Counter()
    with TRACER.start_as_current_span("prepare.build"):
        with task(f"{source} documents", len(own)) as built:
            for each in built.each(own, lambda one: str(one.path)):
                context = RenderContext(
                    owner=each.ref, here=each.path, link_targets=linked, unsupported=unsupported
                )
                began = time.perf_counter()
                try:
                    wanted[each.path] = document_file(each, catalogue, context, conversions)
                    DOCUMENTS.add(1, {"kb_mcp.outcome": "mirrored"})
                except DOCUMENT_ERRORS as error:
                    reason = str(error) if isinstance(error, NAMED_ERRORS) else type(error).__name__
                    problems.append(Problem(where=where(store, each.stored), reason=reason))
                    DOCUMENTS.add(1, {"kb_mcp.outcome": "failed"})
                seconds = time.perf_counter() - began
                CONVERSION_DURATION.record(seconds)
                log.debug(
                    "prepare.document",
                    path=str(each.path),
                    id=each.ref,
                    title=each.document.title,
                    seconds=round(seconds, 3),
                )
        # Each space's tree is Confluence's, built with its pages; Jira has none.
        spaces = catalogue.spaces.values() if Page in document_classes else ()
        for space in spaces:
            tree = tree_path(space.key)
            # Only the files built: a page whose file failed has no file yet.
            links = {
                each.document.id: posixpath.relpath(each.path, tree.parent)
                for each in placed
                if isinstance(each.document, Page)
                and each.document.space_id == space.id
                and each.path in wanted
            }
            try:
                if space.id not in damaged:
                    wanted[tree] = conversions.markdown(catalogue.tree(space, links)).encode()
            except PandocFailedError as error:
                problems.append(Problem(where=f"confluence/spaces/{space.id}", reason=str(error)))
    written = sum(1 for each in own if each.path in wanted)
    # A moved document's old file goes once its new one is built, never before.
    gone = [old for old, new in retired.items() if new is None or new in wanted]
    with TRACER.start_as_current_span("prepare.write"):
        changes = write_changed(
            docs, wanted, lambda folder: owned(folder, source), remove=not problems, retired=gone
        )
        # Once the source's files are as they stay, what no placed document wants and no
        # file links, while no problem was found.
        swept = write_changed(
            docs,
            {},
            lambda folder: unlinked(folder, attached(folder) - set(assets)),
            remove=not any(found.values()),
        )
        changes = replace(changes, removed=changes.removed + swept.removed)
        pruned = conversions.drop_unused(remove=not problems)
    log.info(
        "prepare.written",
        source=source,
        written=changes.written,
        unchanged=changes.unchanged,
        removed=changes.removed,
        converted=conversions.converted,
        reused=conversions.reused,
        pruned=pruned,
    )
    return AtlassianPrepareOutcome(
        documents=written,
        converted=conversions.converted,
        reused=conversions.reused,
        changes=changes,
        unsupported=unsupported,
        problems=tuple(problems),
        elsewhere={name: tuple(each) for name, each in found.items() if each and name != source},
    )
