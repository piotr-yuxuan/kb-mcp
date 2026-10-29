"""The mirror: the newest snapshot of every document of the raw store, as Markdown.

It reads the store, builds every file of ``docs/reference/data-layout.md``'s Markdown
mirror and its bytes, then hands them to ``mirror_files``, which writes those that
changed. Pandoc's conversions come through the cache of ``conversions``, which converts
only what it has not converted before. What cannot be read or converted is reported, and
a run that reports anything removes nothing, neither a file nor a conversion, so that the
last good copy of each stays. Reading, building and writing are each a span; each
document built is counted and timed, never a span, as
``docs/reference/telemetry/mirror.md`` lists it.
"""

from __future__ import annotations

import posixpath
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC
from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics, trace

from kb_mcp.kernel.content import BlogPost, ConfluenceDocument, Issue, Page
from kb_mcp.kernel.names import RefusedError
from kb_mcp.mirror.adapters.markdown import TIME, dump
from kb_mcp.mirror.adapters.mirror_files import Changes, owned, sync
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.mirror.adapters.site_html import (
    Context,
    MarkupError,
    Mirrored,
    normalise,
)
from kb_mcp.mirror.domain.catalogue import Catalogue, front_matter
from kb_mcp.mirror.domain.mirror_layout import (
    asset_path,
    confluence_path,
    document_html,
    issue_path,
    tree_path,
)
from kb_mcp.observability.adapters.progress import task
from kb_mcp.sources.atlassian.adapters.raw_store import (
    UNREADABLE,
    RawStore,
    Stored,
    Unreadable,
    reason,
)
from kb_mcp.sources.atlassian.domain.period import EPOCH

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from pathlib import Path, PurePosixPath

    from kb_mcp.kernel.content import Folder
    from kb_mcp.mirror.adapters.conversions import Conversions

KINDS: tuple[type[Page | BlogPost | Issue], ...] = (Page, BlogPost, Issue)
# A comment's headings sit under its own third-level heading.
COMMENT_SHIFT = 3
UNKNOWN_AUTHOR = "unknown author"
# What building one document's file can meet: a value the front matter refuses, a text
# no file can hold, markup the parser cannot read whole, pandoc failing. All but the
# second name no content.
DOCUMENT_ERRORS = (ValueError, PandocFailedError)
NAMED_ERRORS = (RefusedError, MarkupError, PandocFailedError)
TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
# The documents whose file a run built, or failed to; how long each took to build, pandoc
# writing its Markdown included. A span each would make a run's trace too large.
DOCUMENTS = METER.create_counter(
    "kb_mcp.mirror.documents", unit="{document}", description="Documents built, by outcome"
)
CONVERSION_DURATION = METER.create_histogram(
    "kb_mcp.mirror.conversion.duration", unit="s", description="How long a document's file took"
)


@dataclass(frozen=True)
class Problem:
    """Something not mirrored: where it is in the store, and why, without content."""

    where: str
    reason: str


@dataclass(frozen=True)
class Outcome:
    """What a run did: documents mirrored, conversions, files changed, placeholders, problems.

    ``converted`` counts the conversions pandoc ran, ``reused`` those the cache gave: a
    document's file and a space's tree are one each.
    """

    documents: int
    converted: int
    reused: int
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


def listed_at(store: RawStore, space_id: str, problems: list[Problem]) -> datetime:
    """Say when a space was listed: the epoch when no run said so, or the record is damaged."""
    try:
        return store.listed_at(space_id) or EPOCH
    except UNREADABLE as error:
        problems.append(Problem(f"confluence/spaces/{space_id}/listed_at.json", reason(error)))
        return EPOCH


def read_catalogue(
    store: RawStore, problems: list[Problem]
) -> tuple[Catalogue, set[str], dict[str, datetime]]:
    """Read the spaces, users and listings.

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
        for kind in (Page, BlogPost):
            entries = readable(store.listed(space_id, kind), problems)
            listed.update((each.id, each) for each in entries)
        folders[space_id] = tuple(readable(store.folders(space_id), problems))
        if len(problems) > before:
            damaged.add(space_id)
    names = {user.account_id: user.display_name for user in users if user.display_name}
    return Catalogue(spaces, names, listed, folders), damaged, times


def place(
    store: RawStore, catalogue: Catalogue, times: Mapping[str, datetime], problems: list[Problem]
) -> tuple[list[Placed], dict[PurePosixPath, PurePosixPath | None]]:
    """Read the newest snapshot of every document, and say where each is mirrored.

    A page or a blog post goes to the space whose freshest listing names it, before the
    one its snapshot names, everywhere the mirror uses its space; one whose space is not
    listed has no folder, and is reported. A document confirmed gone is left out, unless
    a listing taken after it answered gone names it again. Also return the files that
    must go even when the run reports problems: those of documents gone (to None), and
    the old file of a document that moved (to its new file).
    """
    placed: list[Placed] = []
    retired: dict[PurePosixPath, PurePosixPath | None] = {}
    try:
        gone = {key: stone for key, stone in store.tombstones().items() if stone.confirmed}
    except UNREADABLE as error:
        problems.append(Problem("tombstones.json", reason(error)))
        gone = {}
    for found in (item for kind in KINDS for item in readable(store.latest(kind), problems)):
        stored, document = found, found.snapshot.document
        if isinstance(document, Issue):
            placed.append(Placed(stored, issue_path(document)))
            continue
        if not isinstance(document, ConfluenceDocument):
            continue
        before = catalogue.spaces.get(document.space_id)
        listed = catalogue.listed.get(document.id)
        stone = gone.get((document.kind, document.id))
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
            placed.append(Placed(stored, confluence_path(document, key)))
            if moves and old is not None:
                retired[old] = confluence_path(document, key)
        else:
            problems.append(Problem(where(store, stored), "space not listed"))
    return placed, retired


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
    placed: Placed, catalogue: Catalogue, context: Context, conversions: Conversions
) -> bytes:
    """Return the bytes of one document's file: its front matter, then its Markdown."""
    snapshot, document = placed.stored.snapshot, placed.document
    matter = front_matter(
        document, snapshot.comments, placed.stored.fetched_at, catalogue, context.mirrored.site
    )
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
    return dump(matter, conversions.markdown(body)).encode()


def mirror(store: RawStore, docs: Path, site: str | None, conversions: Conversions) -> Outcome:
    """Mirror the raw store into ``docs``, with ``conversions`` writing HTML as Markdown.

    Once the files are written, the conversions that this run did not use are pruned,
    unless it reports a problem. The task ``documents`` reports the documents' files
    built, each by its path. The spans ``mirror.read``, ``mirror.build`` and
    ``mirror.write`` hold reading the store, building the files and writing them, the
    prune included; ``mirror.placed`` and ``mirror.written`` say at INFO how many
    documents were placed, and files written and conversions run, reused and pruned,
    ``mirror.document`` at DEBUG each document built, by its path, id and title.
    """
    log = structlog.get_logger()
    problems: list[Problem] = []
    with TRACER.start_as_current_span("mirror.read"):
        catalogue, damaged, times = read_catalogue(store, problems)
        placed, retired = place(store, catalogue, times, problems)
        mirrored, assets = index(placed, store, site)
    log.info("mirror.placed", documents=len(placed), assets=len(assets), problems=len(problems))
    wanted: dict[PurePosixPath, bytes | Path] = {**assets}
    unsupported: Counter[str] = Counter()
    with TRACER.start_as_current_span("mirror.build"):
        with task("documents", len(placed)) as built:
            for each in built.each(placed, lambda one: str(one.path)):
                context = Context(each.handle, each.path, mirrored, unsupported=unsupported)
                began = time.perf_counter()
                try:
                    wanted[each.path] = document_file(each, catalogue, context, conversions)
                    DOCUMENTS.add(1, {"kb_mcp.outcome": "mirrored"})
                except DOCUMENT_ERRORS as error:
                    reason = str(error) if isinstance(error, NAMED_ERRORS) else type(error).__name__
                    problems.append(Problem(where(store, each.stored), reason))
                    DOCUMENTS.add(1, {"kb_mcp.outcome": "failed"})
                seconds = time.perf_counter() - began
                CONVERSION_DURATION.record(seconds)
                log.debug(
                    "mirror.document",
                    path=str(each.path),
                    id=each.handle,
                    title=each.document.title,
                    seconds=round(seconds, 3),
                )
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
                    wanted[tree] = conversions.markdown(catalogue.tree(space, links)).encode()
            except PandocFailedError as error:
                problems.append(Problem(f"confluence/spaces/{space.id}", str(error)))
    written = sum(1 for each in placed if each.path in wanted)
    # A moved document's old file goes once its new one is built, never before.
    gone = [old for old, new in retired.items() if new is None or new in wanted]
    with TRACER.start_as_current_span("mirror.write"):
        changes = sync(docs, wanted, owned, remove=not problems, retired=gone)
        pruned = conversions.prune(remove=not problems)
    log.info(
        "mirror.written",
        written=changes.written,
        unchanged=changes.unchanged,
        removed=changes.removed,
        converted=conversions.converted,
        reused=conversions.reused,
        pruned=pruned,
    )
    return Outcome(
        written, conversions.converted, conversions.reused, changes, unsupported, tuple(problems)
    )
