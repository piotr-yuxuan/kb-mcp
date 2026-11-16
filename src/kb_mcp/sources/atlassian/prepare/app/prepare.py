"""The newest snapshot of every document of one Atlassian source, as Markdown.

The Atlassian sources of one site, Confluence's and Jira's, are prepared apart, each by
its document types. Each reads the whole store, every source's view of it, and places
every document, so that a link or an image of any reaches its file, then builds the
source's own files of ``docs/reference/data-layout.md``'s Markdown mirror and their
bytes, and hands them to ``mirror_files``, which writes those that changed. Pandoc's
conversions come through the source's rows of the cache of ``conversions``, which
converts only what it has not converted before. What cannot be read or converted is
reported by the source it belongs to, and a source that reports anything removes none of
its files and none of its conversions, so that the last good copy of each stays; an
attached file stays while any document's file links it. Reading, building and writing
are each a span; each document built is counted and timed, never a span, as
``docs/reference/telemetry/prepare.md`` lists it.
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

from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.outcome import Outcome, OutcomeWarning, Problem
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.adapters.instruments import CONVERSION_DURATION, DOCUMENTS
from kb_mcp.mirror.adapters.markdown import TIME, dump
from kb_mcp.mirror.adapters.mirror_files import Changes, write_changed
from kb_mcp.mirror.adapters.pandoc import PandocFailedError
from kb_mcp.mirror.adapters.source_files import SOURCE_FILE, dumped
from kb_mcp.mirror.domain.mirror import SourceFile, scope_name
from kb_mcp.observability.adapters.progress import task
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import (
    COVERAGE,
    TOMBSTONES,
    UNREADABLE,
    RawStore,
    StoredSnapshot,
    reason,
)
from kb_mcp.sources.atlassian.fetch.domain.content import (
    BlogPost,
    ConfluenceDocument,
    Folder,
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
from kb_mcp.sources.atlassian.prepare.domain.catalogue import (
    CONTAINERS,
    TYPE_ROLES,
    Catalogue,
    folder_front_matter,
    front_matter,
)
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

# The document classes of a source, which a prepare takes whole.
type Classes = tuple[type[Page | BlogPost | Issue], ...]
# A comment's headings sit under its own third-level heading.
COMMENT_SHIFT = 3
UNKNOWN_AUTHOR = "unknown author"
# What building one document's file can meet: a value the front matter refuses, a text
# no file can hold, markup the parser cannot read whole, pandoc failing. All but the
# second name no content.
DOCUMENT_ERRORS = (ValueError, PandocFailedError)
NAMED_ERRORS = (RefusedError, MarkupError, PandocFailedError)
TRACER = trace.get_tracer(__name__)


class AtlassianCounts(Record):
    """What a prepare did: documents prepared, conversions, files changed, placeholders.

    ``converted`` counts the conversions pandoc ran, ``reused`` those the cache gave: a
    document's file and a space's tree are one each.
    """

    documents: int
    converted: int
    reused: int
    changes: Changes
    unsupported: Counter[str]

    def text(self, detail: Detail) -> str:
        """Write the counts of documents, of conversions run and reused, of files.

        In detail, what the mirror does not show, by name, follows.
        """
        unsupported = sorted(self.unsupported.items()) if detail == "detailed" else []
        return (
            f"documents: {self.documents}\n"
            f"converted by pandoc: {self.converted}\n"
            f"reused from the cache: {self.reused}\n"
            f"files written: {self.changes.written}\n"
            f"files unchanged: {self.changes.unchanged}\n"
            f"files removed: {self.changes.removed}\n"
        ) + "".join(f"not shown, {name}: {count}\n" for name, count in unsupported)


class Placed(Record):
    """A source's stored snapshot, and its document's file in the mirror."""

    source: str
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
        """Name the document as the site's links and images do: its key for Jira, else its id."""
        document = self.document
        return document.key if isinstance(document, Issue) else document.id


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
        where = f"{store.source}/spaces/{space_id}/listed_at.json"
        problems.append(Problem(where=where, reason=reason(error)))
        return EPOCH


def read_catalogue(
    store: RawStore, problems: list[Problem]
) -> tuple[Catalogue, set[str], dict[str, datetime]]:
    """Read the spaces, site users, listings, the scopes' as-of times and what is gone.

    Also return the spaces whose listing failed, and when each space was listed. A record
    of coverage that cannot be read is a problem, and no as-of time is known; one of
    tombstones, a problem too, and nothing is known gone.
    """
    spaces = {space.id: space for space in readable(store.spaces(), problems)}
    users = readable(store.users(), problems)
    try:
        as_of = store.coverage().as_of
    except UNREADABLE as error:
        problems.append(Problem(where=COVERAGE, reason=reason(error)))
        as_of = {}
    try:
        gone = {key: stone for key, stone in store.tombstones().items() if stone.confirmed}
    except UNREADABLE as error:
        problems.append(Problem(where=TOMBSTONES, reason=reason(error)))
        gone = {}
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
    catalogue = Catalogue(
        spaces=spaces, names=names, listed=listed, folders=folders, as_of=as_of, gone=gone
    )
    return catalogue, damaged, times


def place(
    store: RawStore,
    sources: Mapping[str, Classes],
    catalogue: Catalogue,
    times: Mapping[str, datetime],
    problems: Mapping[str, list[Problem]],
) -> tuple[list[Placed], dict[PurePosixPath, PurePosixPath | None]]:
    """Read the newest snapshot of every document of these sources, and say where each goes.

    ``sources`` gives each source's document classes by its name, each read from its view
    of the store that ``store`` views. A page or a blog post goes to the space whose
    freshest listing names it, before the one its snapshot names, everywhere the mirror
    uses its space; one whose space is not listed has no folder, and is reported. A
    document confirmed gone is left out: a page or a blog post unless a listing taken
    after it answered gone names it again; an issue that a whole read names again has no
    tombstone. Each problem goes to the list of the source it belongs to, by its name, in
    ``problems``. Also return the files that must go even when the source reports
    problems: those of documents gone (to None), and the old file of a document that
    moved (to its new file).
    """
    placed: list[Placed] = []
    retired: dict[PurePosixPath, PurePosixPath | None] = {}
    for source, found in (
        (name, item)
        for name, classes in sources.items()
        for document_class in classes
        for item in readable(RawStore(store.root, name).latest(document_class), problems[name])
    ):
        stored, document = found, found.snapshot.document
        stone = catalogue.gone.get((source, document.document_type.name, document.id))
        if isinstance(document, Issue):
            path = issue_path(source, document)
            if stone is None:
                placed.append(Placed(source=source, stored=stored, path=path))
            else:
                retired[path] = None
            continue
        if not isinstance(document, ConfluenceDocument):
            continue
        before = catalogue.spaces.get(document.space_id)
        listed = catalogue.listed.get(document.id)
        # Gone, unless a listing taken after its first answer of gone names it again.
        named = times.get(listed.space_id) if listed is not None else None
        is_gone = stone is not None and (named is None or named <= stone.first_gone)
        moves = listed is not None and listed.space_id != document.space_id
        old = confluence_path(source, document, before.key) if before is not None else None
        if is_gone:
            if old is not None:
                retired[old] = None
            continue
        if moves:
            moved = replace(document, space_id=listed.space_id)
            stored = replace(stored, snapshot=replace(stored.snapshot, document=moved))
            document = moved
        if document.space_id in catalogue.spaces:
            path = confluence_path(source, document, catalogue.spaces[document.space_id].key)
            placed.append(Placed(source=source, stored=stored, path=path))
            if moves and old is not None:
                retired[old] = path
        else:
            problems[source].append(Problem(where=where(store, stored), reason="space not listed"))
    return placed, retired


def folder_files(
    source: str, catalogue: Catalogue, times: Mapping[str, datetime], problems: list[Problem]
) -> dict[str, tuple[PurePosixPath, bytes]]:
    """Give the file of each folder of the source's spaces by its id: its path and its bytes.

    A folder is a container, its file a front matter without a body. It goes in the space
    whose freshest listing names it, by ``times``, as a page does, which also dates a
    folder whose response gave no time. One whose front matter is refused is a problem,
    by its space's listing of folders.
    """
    homes = {
        folder.id: (space_id, folder)
        for space_id in sorted(catalogue.folders, key=times.__getitem__)
        for folder in catalogue.folders[space_id]
    }
    files: dict[str, tuple[PurePosixPath, bytes]] = {}
    for space_id, folder in homes.values():
        space = catalogue.spaces[space_id]
        try:
            matter = folder_front_matter(source, folder, space, catalogue, times[space_id])
        except RefusedError as error:
            where = f"{source}/spaces/{space_id}/folders.json"
            problems.append(Problem(where=where, reason=str(error)))
            continue
        files[folder.id] = (confluence_path(source, folder, space.key), dump(matter, "").encode())
    return files


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
    matter = front_matter(placed.source, snapshot, catalogue, context.link_targets.site)
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
    sites: Mapping[str, str | None],
    conversions: Conversions,
    sources: Mapping[str, Classes],
) -> Outcome[AtlassianCounts]:
    """Write the documents of ``store``'s source from the raw store to ``docs``.

    ``sources`` gives the document classes of each Atlassian source, by its name, and
    ``sites`` the site of each, ``store``'s among them, which raises KeyError, a caller's
    error, before anything is read when it is not. The sources of its site, those
    below, are placed; every source's files are read for the attached files that they
    link, as every source writes into one folder of them. Of the site's, the one whose
    classes are pages lists the spaces, which the others read too.
    ``conversions`` writes HTML as Markdown, through the source's rows of the cache.
    Every document of every source is placed, so that links and images reach the other
    sources' files, but only those of ``store``'s source are built and written, with
    the files they attach, and each space's tree when pages are among them. The source then
    removes its files that are no longer wanted, and prunes its conversions that this
    run did not use, unless it reports a problem, those that it found reading the other
    source's coming back as warnings, which fail nothing of its own, though a link or an
    image of its files may then not reach that source's document. An attached file that no placed
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
    source, site = store.source, sites[store.source]
    placing = {name: each for name, each in sources.items() if sites[name] == site}
    document_classes = placing[source]
    # The problems found, by the source they belong to: the catalogue's are its lister's.
    found: dict[str, list[Problem]] = {name: [] for name in placing}
    problems = found[source]
    lister = next((name for name, classes in placing.items() if Page in classes), source)
    with TRACER.start_as_current_span("prepare.read"):
        catalogue, damaged, times = read_catalogue(RawStore(store.root, lister), found[lister])
        placed, retired = place(store, placing, catalogue, times, found)
        # The source's issues, whose titles name their children's parents.
        catalogue = replace(
            catalogue,
            issues={
                issue.id: issue
                for issue in (each.document for each in placed if each.source == source)
                if isinstance(issue, Issue)
            },
        )
        linked, assets = link_targets(placed, store, site)
    own = [each for each in placed if each.source == source]
    _, files = link_targets(own, store, site)
    log.info(
        "prepare.placed",
        source=source,
        documents=len(own),
        assets=len(files),
        problems=len(problems),
    )
    # A source of pages writes the folders of their spaces too, each a container.
    folders = folder_files(source, catalogue, times, problems) if Page in document_classes else {}
    wanted: dict[PurePosixPath, bytes | Path] = {**files, **dict(folders.values())}
    if own:
        # The source's file beside its documents: the roles that each of its types takes,
        # its containers, a source of pages' folders, and its scopes' as-of times.
        wanted[PurePosixPath(source, SOURCE_FILE)] = dumped(
            SourceFile(
                roles={
                    each.document_type.name: TYPE_ROLES[each.document_type.name]
                    for each in (
                        *document_classes,
                        *((Folder,) if Page in document_classes else ()),
                    )
                },
                containers=CONTAINERS if Page in document_classes else (),
                as_of={
                    scope_name(scope.type.name, scope.key): moment.astimezone(UTC)
                    for scope, moment in catalogue.as_of.items()
                    if scope.source == source
                },
            )
        )
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
        # Each space's tree is its lister's, built with its pages and folders; Jira has none.
        for space in catalogue.spaces.values() if Page in document_classes else ():
            tree = tree_path(source, space.key)
            # Only the files built: a page whose file failed has no file yet.
            links = {
                each.document.id: posixpath.relpath(each.path, tree.parent)
                for each in placed
                if isinstance(each.document, Page)
                and each.document.space_id == space.id
                and each.path in wanted
            } | {
                folder_id: posixpath.relpath(path, tree.parent)
                for folder_id, (path, _) in folders.items()
                if path.parent == tree.parent
            }
            try:
                if space.id not in damaged:
                    wanted[tree] = conversions.markdown(catalogue.tree(space, links)).encode()
            except PandocFailedError as error:
                at = f"{source}/spaces/{space.id}"
                problems.append(Problem(where=at, reason=str(error)))
    # A moved document's old file goes once its new one is built, never before.
    gone = [old for old, new in retired.items() if new is None or new in wanted]
    with TRACER.start_as_current_span("prepare.write"):
        changes = write_changed(
            docs,
            wanted,
            lambda folder: owned(folder, source, document_classes),
            remove=not problems,
            retired=gone,
        )
        # Once the source's files are as they stay, what no placed document wants and no
        # file links, while no problem was found.
        swept = write_changed(
            docs,
            {},
            lambda folder: unlinked(folder, attached(folder) - set(assets), sources),
            remove=not any(found.values()),
        )
        changes = replace(changes, removed=changes.removed + swept.removed)
        pruned = 0 if problems else conversions.drop_unused()
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
    return Outcome.of(
        AtlassianCounts(
            documents=sum(1 for each in own if each.path in wanted) + len(folders),
            converted=conversions.converted,
            reused=conversions.reused,
            changes=changes,
            unsupported=unsupported,
        ),
        problems,
        (
            OutcomeWarning(where=each.where, reason=f"{name}'s, read here: {each.reason}")
            for name, problems_of in found.items()
            if name != source
            for each in problems_of
        ),
    )
