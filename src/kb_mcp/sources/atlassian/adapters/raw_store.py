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

from kb_mcp.kernel.content import BlogPost, Folder, Issue, Listed, Page, Person, Snapshot, Space
from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.kernel.names import IDENTIFIER, REVISION, RefusedError, require
from kb_mcp.kernel.record import Record
from kb_mcp.sources.atlassian.adapters import confluence_v2, jira_v3
from kb_mcp.sources.atlassian.domain.coverage import Coverage, Target
from kb_mcp.sources.atlassian.domain.deletions import Tombstone
from kb_mcp.sources.atlassian.domain.period import Period, PeriodError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from kb_mcp.kernel.content import Document

# The store's own file in a snapshot, beside the responses.
RECORD = "store.json"
# The store's own records of what runs covered, and of documents that answered as gone.
COVERAGE = "coverage.json"
TOMBSTONES = "tombstones.json"
# The store's own record, beside a space's listings, of when they were listed.
LISTED_AT = "listed_at.json"
# The file name of a response: one safe path part, then .json.
RESPONSE_NAME = re.compile(r"[A-Za-z0-9_-]+\.json")
DIGEST = re.compile(r"[0-9a-f]{64}")
# What a failed read is reported by: the field's path, or the error's class alone.
UNREADABLE = (ValueError, OSError)


class Representation(Record):
    """How the snapshots of one kind of document are read.

    ``files`` names the responses that a snapshot of the kind must have. ``identity``
    reads only what names the folder (id and revision), so that a response whose other
    fields have changed is still kept, to be read once its adapter is fixed;
    ``snapshot`` reads it all.
    """

    files: tuple[str, ...]
    identity: Callable[[Mapping[str, object]], tuple[str, str]]
    snapshot: Callable[[Mapping[str, object]], Snapshot]


CONFLUENCE_FILES = (confluence_v2.DOCUMENT, confluence_v2.VIEW, confluence_v2.ATTACHMENTS)
REPRESENTATIONS: dict[type[Document], Representation] = {
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


class Stored(Record):
    """A stored snapshot, read into the domain, with the store's record of it.

    ``blobs`` maps each downloaded attachment's id to its file's SHA-256; an attachment
    of the snapshot that it lacks was not downloaded.
    """

    folder: Path
    snapshot: Snapshot
    fetched_at: datetime
    blobs: Mapping[str, str]


class Unreadable(Record):
    """Something stored that its adapter refuses: where it is, and why, without content."""

    where: str  # the path within the store, with an index for an entry of a listing
    reason: str


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
    # A record the store wrote and cannot read back is a changed shape, named by its file.
    try:
        return _decode(path)
    except ValueError:
        message = f"{path.name}: not JSON"
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
    """Responses kept as received, by document and revision, and files by SHA-256.

    A snapshot is the folder ``<root>/<source>/<kind>/<id>/<revision>/``, one JSON file
    per response plus the store's record. It is written whole into a hidden folder and
    renamed into place, so it is either complete or absent, and its responses never
    change. A space's listings are ``<root>/confluence/spaces/<id>/*.json``, each
    replaced whole; users are ``<root>/confluence/users.json``, merged. A file is
    ``<root>/blobs/<digest[:2]>/<digest>``. One run at a time writes, inside ``writing``.
    """

    def __init__(self, root: Path) -> None:
        """Use ``root`` as the store, creating its folders as they are needed."""
        self.root = root
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

    def folder(self, document: Document | Listed) -> Path:
        """Return where the snapshot of this document at this revision is, or would be."""
        return self.root / document.source / document.kind / document.id / document.revision

    def has(self, document: Document | Listed) -> bool:
        """Say whether this document's revision is stored."""
        return self.folder(document).is_dir()

    def put(
        self,
        kind: type[Document],
        responses: Mapping[str, object],
        fetched_at: datetime,
        blobs: Mapping[str, str],
    ) -> Path:
        """Store a snapshot as received, and return its folder.

        Every response the kind needs must be there, since a stored revision is never
        written again; only the id and the revision are read, by the kind's adapter.
        Every file that ``blobs`` names must be stored first, with ``put_blob``. A
        revision stored already keeps its responses, and records the new blobs.
        """
        self._check_writing()
        representation = REPRESENTATIONS[kind]
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
        target = self.root / kind.source / kind.kind / identifier / revision
        if not target.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            hidden = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=target.parent))
            try:
                for name, response in responses.items():
                    _write_synced(hidden / name, _encode(response))
                _write_synced(hidden / RECORD, self._record(fetched_at, {}))
                hidden.rename(target)
            except OSError:
                if not target.is_dir():  # not another writer's snapshot, landed first
                    raise
            finally:
                shutil.rmtree(hidden, ignore_errors=True)
        self._merge_blobs(target, blobs)
        return target

    def add_blobs(self, document: Document | Listed, blobs: Mapping[str, str]) -> None:
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

    def read(self, document: Document | Listed) -> Stored:
        """Read the stored snapshot of this document at this revision."""
        kind = document.type if isinstance(document, Listed) else type(document)
        return self._read(kind, self.folder(document))

    def _read(self, kind: type[Document], folder: Path) -> Stored:
        fetched_at, blobs = self._read_record(folder)
        snapshot = REPRESENTATIONS[kind].snapshot(self.responses(folder))
        # Only the snapshot's own attachments: a key of anything else names no file here.
        known = {attachment.id for attachment in snapshot.attachments}
        own = {key: digest for key, digest in blobs.items() if key in known}
        return Stored(folder=folder, snapshot=snapshot, fetched_at=fetched_at, blobs=own)

    def latest(self, kind: type[Document]) -> Iterator[Stored | Unreadable]:
        """Yield the newest stored snapshot of each document of a kind, or why it is not.

        A snapshot that its adapter now refuses is yielded as ``Unreadable``, and the
        others still follow.
        """
        for item in _named(self.root / kind.source / kind.kind, IDENTIFIER):
            revisions = _named(item, REVISION)
            if not revisions:
                continue
            try:
                yield self._read(kind, revisions[-1])
            except UNREADABLE as error:
                yield Unreadable(
                    where=str(revisions[-1].relative_to(self.root)), reason=reason(error)
                )

    @staticmethod
    def responses(folder: Path) -> dict[str, object]:
        """Read the responses of a snapshot as received, by file name, for adapters."""
        return {
            path.name: _decode(path)
            for path in _named(folder, RESPONSE_NAME)
            if path.name != RECORD
        }

    def _space(self, space_id: str) -> Path:
        return self.root / "confluence" / "spaces" / _identifier(space_id, "space id")

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
        target = self._space(Fields(space, "space").text("id"))
        for name, value in (("pages", pages), ("blogposts", blog_posts), ("folders", folders)):
            if type(value) is not list:
                message = f"{name}: expected a list"
                raise ValueError(message)
            _replace_synced(target / f"{name}.json", _encode(value))
        _replace_synced(target / "space.json", _encode(space))
        if listed_at is not None:
            moment = {"listed_at": listed_at.astimezone(UTC).isoformat()}
            _replace_synced(target / LISTED_AT, _encode(moment))

    def listed_at(self, space_id: str) -> datetime | None:
        """Say when a space was last listed, or None when no run said so."""
        path = self._space(space_id) / LISTED_AT
        if not path.exists():
            return None
        return Fields(_decode(path), LISTED_AT).time("listed_at")

    def spaces(self) -> list[Space | Unreadable]:
        """Read every space ever listed."""
        spaces: list[Space | Unreadable] = []
        for folder in _named(self.root / "confluence" / "spaces", IDENTIFIER):
            where = str((folder / "space.json").relative_to(self.root))
            try:
                spaces.append(confluence_v2.space(Fields(_decode(folder / "space.json"), where)))
            except UNREADABLE as error:
                spaces.append(Unreadable(where=where, reason=reason(error)))
        return spaces

    def listed(
        self, space_id: str, kind: type[Page | BlogPost]
    ) -> list[Page | BlogPost | Unreadable]:
        """Read the pages, or the blog posts, last listed in a space."""
        path = self._space(space_id) / f"{kind.kind}.json"
        return self._entries(path, partial(confluence_v2.document, kind=kind))

    def listed_ids(self, space_id: str, kind: type[Page | BlogPost]) -> set[str]:
        """Return the ids that a space's last listing names, read by id alone.

        An entry whose other fields the adapter would refuse still names its document,
        so that deletions follow every document a download fetched. A listing that
        cannot be read at all names none.
        """
        path = self._space(space_id) / f"{kind.kind}.json"
        try:
            return confluence_v2.entry_ids(_decode(path)) if path.exists() else set()
        except UNREADABLE:
            return set()

    def folders(self, space_id: str) -> list[Folder | Unreadable]:
        """Read the folders last listed in a space."""
        return self._entries(self._space(space_id) / "folders.json", confluence_v2.folder)

    def put_users(self, users: list[object]) -> None:
        """Merge users, as received, into those kept from earlier runs, by account id."""
        self._check_writing()
        path = self.root / "confluence" / "users.json"
        kept = _decode(path) if path.exists() else []
        if type(kept) is not list or type(users) is not list:
            message = "users: expected a list"
            raise RepresentationError(message)
        merged: dict[str, object] = {}
        for name, entries in (("users.json", kept), ("users", users)):
            for index, user in enumerate(entries):
                merged[Fields(user, f"{name}[{index}]").text("accountId")] = user
        _replace_synced(path, _encode([merged[key] for key in sorted(merged)]))

    def users(self) -> list[Person | Unreadable]:
        """Read every user kept."""
        return self._entries(self.root / "confluence" / "users.json", confluence_v2.person)

    def _entries[T](self, path: Path, read: Callable[[Fields], T]) -> list[T | Unreadable]:
        if not path.exists():
            return []
        where = str(path.relative_to(self.root))
        try:
            entries = Fields.each(_decode(path), where)
        except UNREADABLE as error:
            return [Unreadable(where=where, reason=reason(error))]
        results: list[T | Unreadable] = []
        for index, entry in enumerate(entries):
            try:
                results.append(read(entry))
            except UNREADABLE as error:
                results.append(Unreadable(where=f"{where}[{index}]", reason=reason(error)))
        return results

    def stored_ids(self, kind: type[Document]) -> set[str]:
        """Return the ids of the documents of a kind that have a stored snapshot."""
        folders = _named(self.root / kind.source / kind.kind, IDENTIFIER)
        return {folder.name for folder in folders if _named(folder, REVISION)}

    def coverage(self) -> Coverage:
        """Read each target's covered period, none when never written, and which are exact.

        An entry without ``exact``, as every entry was before plan 034, is not; nor is a
        space's, whatever it says, since a space is listed whole.
        """
        path = self.root / COVERAGE
        if not path.exists():
            return Coverage()
        periods: dict[Target, Period] = {}
        exact: set[Target] = set()
        for item in Fields.each(_record_json(path), COVERAGE):
            with item.refusals():
                target = Target(source=item.text("source"), key=item.text("key"))
            try:
                periods[target] = Period(item.time("start"), item.time("end"))
            except PeriodError:
                message = f"{item.path}: a period that ends before it starts"
                raise RepresentationError(message) from None
            if target.searched_by_time and "exact" in item.value and item.flag("exact"):
                exact.add(target)
        return Coverage(periods=periods, exact=frozenset(exact))

    def put_coverage(self, coverage: Coverage) -> None:
        """Replace the record of coverage, whole; an exact entry says so, beside the rest.

        The other keys are as before plan 034, so that its versions still read the record.
        """
        self._check_writing()
        entries = [
            {
                "source": target.source,
                "key": target.key,
                "start": covered.start.astimezone(UTC).isoformat(),
                "end": covered.end.astimezone(UTC).isoformat(),
                **({"exact": True} if target in coverage.exact else {}),
            }
            for target, covered in sorted(
                coverage.periods.items(), key=lambda item: (item[0].source, item[0].key)
            )
        ]
        _replace_synced(self.root / COVERAGE, _encode(entries))

    def tombstones(self) -> dict[tuple[str, str], Tombstone]:
        """Read the documents that answered as gone, by kind and id."""
        path = self.root / TOMBSTONES
        if not path.exists():
            return {}
        stones: dict[tuple[str, str], Tombstone] = {}
        for item in Fields.each(_record_json(path), TOMBSTONES):
            with item.refusals():
                kind, identifier = item.text("kind"), _identifier(item.text("id"), "id")
                if kind not in {Page.kind, BlogPost.kind}:
                    message = f"{item.path}.kind: not a kind of Confluence document"
                    raise RepresentationError(message)
                first_gone = item.time("first_gone") if item.optional_text("first_gone") else None
                stone = Tombstone(
                    kind=kind,
                    id=identifier,
                    space_id=item.text("space"),
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
                "kind": stone.kind,
                "id": stone.id,
                "space": stone.space_id,
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
