"""The raw store: responses as the site returned them, and attached files by digest."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.kernel.names import IDENTIFIER, RefusedError, require
from kb_mcp.kernel.outcome import Problem
from kb_mcp.kernel.record import Record
from kb_mcp.sources.atlassian.fetch.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.fetch.domain.content import (
    REVISION,
    BlogPost,
    Folder,
    Issue,
    Listed,
    Page,
    SiteUser,
    Snapshot,
    Space,
)
from kb_mcp.sources.atlassian.fetch.domain.coverage import Coverage, Scope
from kb_mcp.sources.atlassian.fetch.domain.deletions import DocumentKey, Tombstone
from kb_mcp.sources.atlassian.fetch.domain.names import (
    BLOGPOST,
    CONFLUENCE,
    JIRA,
    PAGE,
    PROJECT,
    SPACE,
)
from kb_mcp.sources.atlassian.fetch.domain.period import Period, PeriodError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from kb_mcp.sources.atlassian.fetch.domain.content import FetchedDocument

# The store's own file in a snapshot, beside the responses.
RECORD = "store.json"
# The store's own records of what runs covered, and of documents that answered as gone.
COVERAGE = "coverage.json"
TOMBSTONES = "tombstones.json"
# The store's own record, beside a space's listings, of when they were listed.
LISTED_AT = "listed_at.json"
# The site's users, merged, where Confluence's one source keeps its documents: they are
# the site's, which plan 059 keys by site.
USERS = Path(CONFLUENCE, "users.json")
# The scope types of the coverage's entries, by name; an entry written before plan 056
# names none, and its source, then always its connector's name, gives it.
SCOPE_TYPES = {SPACE.name: SPACE, PROJECT.name: PROJECT}
FORMER_TYPES = {CONFLUENCE: SPACE.name, JIRA: PROJECT.name}
# The scope type of each document type that a tombstone may name, by name; and the
# document type of a tombstone written before plan 056, by the plural it named as ``kind``.
HELD_IN = {
    each.name: scope_type for scope_type in (SPACE, PROJECT) for each in scope_type.document_types
}
FORMER_KINDS = {PAGE.plural: PAGE.name, BLOGPOST.plural: BLOGPOST.name}
# The times that a coverage's entry may hold beside its period, each a field of Coverage.
COVERAGE_TIMES = ("as_of", "whole_read_at")
# The file name of a response: one safe path part, then .json.
RESPONSE_NAME = re.compile(r"[A-Za-z0-9_-]+\.json")
DIGEST = re.compile(r"[0-9a-f]{64}")
# What a failed read is reported by: the field's path, or the error's class alone.
UNREADABLE = (ValueError, OSError)


class Representation(Record):
    """How the snapshots of one document type are read.

    ``files`` names the responses that a snapshot of the type must have. ``identity``
    reads only what names the folder (id and revision), so that a response whose other
    fields have changed is still kept, to be read once its adapter is fixed;
    ``snapshot`` reads it all.
    """

    files: tuple[str, ...]
    identity: Callable[[Mapping[str, object]], tuple[str, str]]
    snapshot: Callable[[Mapping[str, object]], Snapshot]


CONFLUENCE_FILES = (confluence_v2.DOCUMENT, confluence_v2.VIEW, confluence_v2.ATTACHMENTS)
REPRESENTATIONS: dict[type[FetchedDocument], Representation] = {
    Page: Representation(
        files=CONFLUENCE_FILES,
        identity=confluence_v2.identity,
        snapshot=partial(confluence_v2.snapshot, Page),
    ),
    BlogPost: Representation(
        files=CONFLUENCE_FILES,
        identity=confluence_v2.identity,
        snapshot=partial(confluence_v2.snapshot, BlogPost),
    ),
    Issue: Representation(
        files=(jira_v3.ISSUE, jira_v3.COMMENTS),
        identity=jira_v3.identity,
        snapshot=jira_v3.snapshot,
    ),
}


class StoreBusyError(RuntimeError):
    """Another run is writing the raw store."""


class StoredSnapshot(Record):
    """A stored snapshot, read into the domain, with the store's record of it.

    ``blobs`` maps each downloaded attachment's id to its file's SHA-256; an attachment
    of the snapshot that it lacks was not downloaded.
    """

    folder: Path
    snapshot: Snapshot
    fetched_at: datetime
    blobs: Mapping[str, str]


def _write_synced(path: Path, data: bytes) -> None:
    with path.open("wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def _replace_synced(path: Path, data: bytes) -> None:
    """Write a file whole, through a hidden file renamed over it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, hidden = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(handle)
    try:
        _write_synced(Path(hidden), data)
        Path(hidden).replace(path)
    finally:
        Path(hidden).unlink(missing_ok=True)


def _encode(value: object) -> bytes:
    # ASCII escapes keep any string the site sent storable, lone surrogates included.
    return json.dumps(value).encode()


def _decode(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _record_json(path: Path) -> object:
    # A record the store wrote and cannot read back is a changed shape, named by its file,
    # as is one that no read reaches, such as a folder in its place.
    try:
        return _decode(path)
    except UNREADABLE as error:
        why = "not JSON" if isinstance(error, ValueError) else f"not read: {type(error).__name__}"
        message = f"{path.name}: {why}"
        raise RepresentationError(message) from None


def reason(error: Exception) -> str:
    """Say why a read failed: a refused field's path, or the error's class alone.

    A representation error names a path; any other message could hold content.
    """
    return str(error) if isinstance(error, RepresentationError) else type(error).__name__


def _named(folder: Path, pattern: re.Pattern[str]) -> list[Path]:
    # Only names the store writes: never hidden leftovers, .DS_Store or copies.
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if pattern.fullmatch(path.name))


def _identifier(value: str, name: str) -> str:
    try:
        require(IDENTIFIER, value, name)
    except RefusedError as error:
        raise RepresentationError(str(error)) from None
    return value


class RawStore:
    """One source's view of the raw store: responses as received, and files by SHA-256.

    The sources of one site share the store under ``root``: its files, coverage, records
    of what answered as gone, site users and lock. Its source's snapshot of a document is
    the folder ``<root>/<source>/<plural>/<id>/<revision>/``, one JSON file per response
    plus the store's record. It is written whole into a hidden folder and renamed into
    place, so it is either complete or absent, and its responses never change. A space's
    listings are ``<root>/<source>/spaces/<id>/*.json``, each replaced whole; site users
    are ``<root>/confluence/users.json``, merged. A file is
    ``<root>/blobs/<digest[:2]>/<digest>``. One run at a time writes, inside ``writing``.
    """

    def __init__(self, root: Path, source: str) -> None:
        """Use ``root`` as the store, for ``source``, creating its folders as needed."""
        self.root = root
        self.source = source
        self._lock: int | None = None

    @contextmanager
    def writing(self) -> Iterator[None]:
        """Hold the store's lock while writing; raise ``StoreBusyError`` if it is held."""
        self.root.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(handle)
            raise StoreBusyError from None
        self._lock = handle
        try:
            yield
        finally:
            self._lock = None
            os.close(handle)  # closing the descriptor releases the lock

    def _check_writing(self) -> None:
        if self._lock is None:
            message = "the raw store is written only inside RawStore.writing()"
            raise RuntimeError(message)

    def folder(self, document: FetchedDocument | Listed) -> Path:
        """Return where the snapshot of this document at this revision is, or would be."""
        return (
            self.root
            / self.source
            / document.document_type.plural
            / document.id
            / document.revision
        )

    def has(self, document: FetchedDocument | Listed) -> bool:
        """Say whether this document's revision is stored."""
        return self.folder(document).is_dir()

    def put(
        self,
        document_class: type[FetchedDocument],
        responses: Mapping[str, object],
        fetched_at: datetime,
        blobs: Mapping[str, str],
    ) -> Path:
        """Store a snapshot as received, and return its folder.

        Every response the type needs must be there, since a stored revision is never
        written again; only the id and the revision are read, by the type's adapter.
        Every file that ``blobs`` names must be stored first, with ``put_blob``. A
        revision stored already keeps its responses, and records the new blobs.
        """
        self._check_writing()
        representation = REPRESENTATIONS[document_class]
        missing = [name for name in representation.files if name not in responses]
        if missing:
            message = f"a snapshot without {', '.join(missing)}"
            raise ValueError(message)
        identifier, revision = representation.identity(responses)
        _identifier(identifier, "id")
        if not REVISION.fullmatch(revision) or RECORD in responses:
            message = "not a revision, or a response named as the store's record"
            raise ValueError(message)
        if not all(RESPONSE_NAME.fullmatch(name) for name in responses):
            message = "not plain JSON file names of responses"
            raise ValueError(message)
        self._check_blobs(blobs)
        folder = (
            self.root / self.source / document_class.document_type.plural / identifier / revision
        )
        if not folder.is_dir():
            folder.parent.mkdir(parents=True, exist_ok=True)
            hidden = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=folder.parent))
            try:
                for name, response in responses.items():
                    _write_synced(hidden / name, _encode(response))
                _write_synced(hidden / RECORD, self._record(fetched_at, {}))
                hidden.rename(folder)
            except OSError:
                if not folder.is_dir():  # not another writer's snapshot, landed first
                    raise
            finally:
                shutil.rmtree(hidden, ignore_errors=True)
        self._merge_blobs(folder, blobs)
        return folder

    def add_blobs(self, document: FetchedDocument | Listed, blobs: Mapping[str, str]) -> None:
        """Record files downloaded after their snapshot was stored, such as on a retry."""
        self._check_writing()
        self._check_blobs(blobs)
        self._merge_blobs(self.folder(document), blobs)

    def _check_blobs(self, blobs: Mapping[str, str]) -> None:
        if not all(IDENTIFIER.fullmatch(key) for key in blobs) or not all(
            self.blob(digest).is_file() for digest in blobs.values()
        ):
            message = "blobs: not attachment ids with stored files"
            raise ValueError(message)

    def _merge_blobs(self, folder: Path, blobs: Mapping[str, str]) -> None:
        if not blobs:
            return
        fetched_at, stored = self._read_record(folder)
        _replace_synced(folder / RECORD, self._record(fetched_at, {**stored, **blobs}))

    @staticmethod
    def _record(fetched_at: datetime, blobs: Mapping[str, str]) -> bytes:
        moment = fetched_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = [{"attachment": key, "sha256": blobs[key]} for key in sorted(blobs)]
        return _encode({"fetched_at": moment, "blobs": entries})

    def _read_record(self, folder: Path) -> tuple[datetime, dict[str, str]]:
        record = Fields(_decode(folder / RECORD), RECORD)
        blobs = {item.text("attachment"): item.text("sha256") for item in record.objects("blobs")}
        if not all(DIGEST.fullmatch(digest) for digest in blobs.values()):
            message = f"{RECORD}.blobs: expected SHA-256 digests"
            raise RepresentationError(message)
        return record.time("fetched_at"), blobs

    def read(self, document: FetchedDocument | Listed) -> StoredSnapshot:
        """Read the stored snapshot of this document at this revision."""
        document_class = document.document_class if isinstance(document, Listed) else type(document)
        return self._read(document_class, self.folder(document))

    def _read(self, document_class: type[FetchedDocument], folder: Path) -> StoredSnapshot:
        fetched_at, blobs = self._read_record(folder)
        snapshot = REPRESENTATIONS[document_class].snapshot(self.responses(folder))
        # Only the snapshot's own attachments: a key of anything else names no file here.
        known = {attachment.id for attachment in snapshot.attachments}
        own = {key: digest for key, digest in blobs.items() if key in known}
        return StoredSnapshot(folder=folder, snapshot=snapshot, fetched_at=fetched_at, blobs=own)

    def latest(self, document_class: type[FetchedDocument]) -> Iterator[StoredSnapshot | Problem]:
        """Yield the newest stored snapshot of each document of a type, or why it is not.

        A snapshot that its adapter now refuses is yielded as ``Problem``, and the
        others still follow.
        """
        for item in _named(
            self.root / self.source / document_class.document_type.plural, IDENTIFIER
        ):
            revisions = _named(item, REVISION)
            if not revisions:
                continue
            try:
                yield self._read(document_class, revisions[-1])
            except UNREADABLE as error:
                yield Problem(where=str(revisions[-1].relative_to(self.root)), reason=reason(error))

    @staticmethod
    def responses(folder: Path) -> dict[str, object]:
        """Read the responses of a snapshot as received, by file name, for adapters."""
        return {
            path.name: _decode(path)
            for path in _named(folder, RESPONSE_NAME)
            if path.name != RECORD
        }

    def _space(self, space_id: str) -> Path:
        return self.root / self.source / "spaces" / _identifier(space_id, "space id")

    def put_space(
        self,
        space: object,
        pages: list[object],
        blog_posts: list[object],
        folders: list[object],
        *,
        listed_at: datetime | None = None,
    ) -> None:
        """Replace a space's listings, each as received, and say when they were listed.

        They are the space itself and every result of every page of the listings of its
        pages, blog posts and folders. ``listed_at`` lets the mirror prefer the freshest
        of two listings that name one document, as after a move.
        """
        self._check_writing()
        space_folder = self._space(Fields(space, "space").text("id"))
        for name, value in (
            (PAGE.plural, pages),
            (BLOGPOST.plural, blog_posts),
            ("folders", folders),
        ):
            if type(value) is not list:
                message = f"{name}: expected a list"
                raise ValueError(message)
            _replace_synced(space_folder / f"{name}.json", _encode(value))
        _replace_synced(space_folder / "space.json", _encode(space))
        if listed_at is not None:
            moment = {"listed_at": listed_at.astimezone(UTC).isoformat()}
            _replace_synced(space_folder / LISTED_AT, _encode(moment))

    def was_listed(self, space_id: str) -> bool:
        """Say whether a space's listings are stored, by an earlier run."""
        return (self._space(space_id) / f"{PAGE.plural}.json").exists()

    def listed_at(self, space_id: str) -> datetime | None:
        """Say when a space was last listed, or None when no run said so."""
        path = self._space(space_id) / LISTED_AT
        if not path.exists():
            return None
        return Fields(_decode(path), LISTED_AT).time("listed_at")

    def spaces(self) -> list[Space | Problem]:
        """Read every space ever listed."""
        spaces: list[Space | Problem] = []
        for folder in _named(self.root / self.source / "spaces", IDENTIFIER):
            where = str((folder / "space.json").relative_to(self.root))
            try:
                spaces.append(confluence_v2.space(Fields(_decode(folder / "space.json"), where)))
            except UNREADABLE as error:
                spaces.append(Problem(where=where, reason=reason(error)))
        return spaces

    def listed(
        self, space_id: str, document_class: type[Page | BlogPost]
    ) -> list[Page | BlogPost | Problem]:
        """Read the pages, or the blog posts, last listed in a space."""
        path = self._space(space_id) / f"{document_class.document_type.plural}.json"
        return self._entries(path, partial(confluence_v2.document, document_class=document_class))

    def listed_ids(self, space_id: str, document_class: type[Page | BlogPost]) -> set[str]:
        """Return the ids that a space's last listing names, read by id alone.

        An entry whose other fields the adapter would refuse still names its document,
        so that deletions follow every document that a fetch fetched. A listing that
        cannot be read at all names none.
        """
        path = self._space(space_id) / f"{document_class.document_type.plural}.json"
        try:
            return confluence_v2.entry_ids(_decode(path)) if path.exists() else set()
        except UNREADABLE:
            return set()

    def folders(self, space_id: str) -> list[Folder | Problem]:
        """Read the folders last listed in a space."""
        return self._entries(self._space(space_id) / "folders.json", confluence_v2.folder)

    def put_users(self, users: list[object]) -> None:
        """Merge site users, as received, into those kept from earlier runs, by account id."""
        self._check_writing()
        path = self.root / USERS
        kept = _decode(path) if path.exists() else []
        if type(kept) is not list or type(users) is not list:
            message = "users: expected a list"
            raise RepresentationError(message)
        merged: dict[str, object] = {}
        for name, entries in (("users.json", kept), ("users", users)):
            for index, user in enumerate(entries):
                merged[Fields(user, f"{name}[{index}]").text("accountId")] = user
        _replace_synced(path, _encode([merged[key] for key in sorted(merged)]))

    def users(self) -> list[SiteUser | Problem]:
        """Read every site user kept."""
        return self._entries(self.root / USERS, confluence_v2.person)

    def _entries[T](self, path: Path, read: Callable[[Fields], T]) -> list[T | Problem]:
        if not path.exists():
            return []
        where = str(path.relative_to(self.root))
        try:
            entries = Fields.each(_decode(path), where)
        except UNREADABLE as error:
            return [Problem(where=where, reason=reason(error))]
        results: list[T | Problem] = []
        for index, entry in enumerate(entries):
            try:
                results.append(read(entry))
            except UNREADABLE as error:
                results.append(Problem(where=f"{where}[{index}]", reason=reason(error)))
        return results

    def stored_ids(self, document_class: type[FetchedDocument]) -> set[str]:
        """Return the ids of the documents of a type that have a stored snapshot."""
        folders = _named(self.root / self.source / document_class.document_type.plural, IDENTIFIER)
        return {folder.name for folder in folders if _named(folder, REVISION)}

    def coverage(self) -> Coverage:
        """Read each scope's coverage, none when never written: its period, and more if given.

        Whether it is exact, its as-of time and the time of its last whole read. An entry
        without ``type``, as every entry was before plan 056, is of its connector's one
        scope type; one without ``exact``, as before plan 034, is not exact; one without a
        time has none.
        """
        path = self.root / COVERAGE
        if not path.exists():
            return Coverage()
        periods: dict[Scope, Period] = {}
        exact: set[Scope] = set()
        times: dict[str, dict[Scope, datetime]] = {name: {} for name in COVERAGE_TIMES}
        for item in Fields.each(_record_json(path), COVERAGE):
            with item.refusals():
                source = item.text("source")
                named = item.optional_text("type", absent=True) or FORMER_TYPES.get(source, "")
                if named not in SCOPE_TYPES:
                    message = "type: not a scope type of Confluence or Jira"
                    raise RefusedError(message)
                scope = Scope(source=source, type=SCOPE_TYPES[named], key=item.text("key"))
            try:
                periods[scope] = Period(item.time("start"), item.time("end"))
            except PeriodError:
                message = f"{item.path}: a period that ends before it starts"
                raise RepresentationError(message) from None
            if "exact" in item.value and item.flag("exact"):
                exact.add(scope)
            for name in COVERAGE_TIMES:
                if item.optional_text(name, absent=True):
                    times[name][scope] = item.time(name)
        return Coverage(periods=periods, exact=frozenset(exact), **times)

    def put_coverage(self, coverage: Coverage) -> None:
        """Replace the record of coverage, whole; each entry with what it holds beside its period.

        Its scope type, whether it is exact, and its times. The keys of plan 034's record
        keep their meaning, so that its versions still read the record.
        """
        self._check_writing()
        times = {name: getattr(coverage, name) for name in COVERAGE_TIMES}
        entries = [
            {
                "source": scope.source,
                "type": scope.type.name,
                "key": scope.key,
                "start": covered.start.astimezone(UTC).isoformat(),
                "end": covered.end.astimezone(UTC).isoformat(),
                **({"exact": True} if scope in coverage.exact else {}),
                **{
                    name: held[scope].astimezone(UTC).isoformat()
                    for name, held in times.items()
                    if scope in held
                },
            }
            for scope, covered in sorted(
                coverage.periods.items(),
                key=lambda item: (item[0].source, item[0].type.name, item[0].key),
            )
        ]
        _replace_synced(self.root / COVERAGE, _encode(entries))

    def tombstones(self) -> dict[DocumentKey, Tombstone]:
        """Read the documents that answered as gone, by source, document type and id.

        An entry written before plan 056 names the plural of its type as ``kind``, and
        its space by id as ``space``: it is Confluence's, and of the space that Confluence's
        view of the store lists under that id, whichever view reads it.
        """
        path = self.root / TOMBSTONES
        if not path.exists():
            return {}
        stones: dict[DocumentKey, Tombstone] = {}
        keys: dict[str, str] = {}  # each space's key by its id, for an entry of before 056
        for item in Fields.each(_record_json(path), TOMBSTONES):
            former = "kind" in item.value
            if former and not keys:
                spaces = RawStore(self.root, CONFLUENCE).spaces()
                keys = {each.id: each.key for each in spaces if isinstance(each, Space)}
            with item.refusals():
                if former:
                    source, named = CONFLUENCE, FORMER_KINDS.get(item.text("kind"), "")
                    scope_key = keys.get(item.text("space"), "")
                else:
                    source, named, scope_key = (
                        item.text(key) for key in ("source", "type", "scope")
                    )
                if named not in HELD_IN:
                    message = "type: not a document type of Confluence or Jira"
                    raise RefusedError(message)
                first_gone = item.time("first_gone") if item.optional_text("first_gone") else None
                stone = Tombstone(
                    scope=Scope(source=source, type=HELD_IN[named], key=scope_key),
                    type=named,
                    id=_identifier(item.text("id"), "id"),
                    first_gone=first_gone,
                    confirmed=item.flag("confirmed"),
                )
            stones[stone.key] = stone
        return stones

    def put_tombstones(self, tombstones: Iterable[Tombstone]) -> None:
        """Replace the record of tombstones, whole."""
        self._check_writing()
        entries = [
            {
                "source": stone.scope.source,
                "type": stone.type,
                "id": stone.id,
                "scope": stone.scope.key,
                "first_gone": stone.first_gone.astimezone(UTC).isoformat()
                if stone.first_gone
                else None,
                "confirmed": stone.confirmed,
            }
            for stone in sorted(tombstones, key=lambda each: each.key)
        ]
        _replace_synced(self.root / TOMBSTONES, _encode(entries))

    def blob(self, digest: str) -> Path:
        """Return where the file with this SHA-256 is, or would be."""
        if not DIGEST.fullmatch(digest):
            message = "not a SHA-256 digest"
            raise ValueError(message)
        return self.root / "blobs" / digest[:2] / digest

    def put_blob(self, data: bytes) -> str:
        """Store a file under its SHA-256, once, and return the digest."""
        self._check_writing()
        digest = hashlib.sha256(data).hexdigest()
        path = self.blob(digest)
        if not path.exists():
            _replace_synced(path, data)
        return digest
