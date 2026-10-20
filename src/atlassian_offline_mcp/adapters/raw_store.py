"""The raw store: responses as the site returned them, and attached files by digest."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters import confluence_v2, jira_v3
from atlassian_offline_mcp.adapters.fields import Fields, RepresentationError
from atlassian_offline_mcp.domain.content import BlogPost, Issue, Page

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from datetime import datetime

    from atlassian_offline_mcp.domain.content import Document, Snapshot

# How the snapshots of each kind are read, by (source, kind): the store refuses
# responses that its kind's adapter cannot read, and never stores another kind.
READERS: dict[tuple[str, str], Callable[[Mapping[str, object]], Snapshot]] = {
    (Page.source, Page.kind): partial(confluence_v2.snapshot, Page),
    (BlogPost.source, BlogPost.kind): partial(confluence_v2.snapshot, BlogPost),
    (Issue.source, Issue.kind): jira_v3.snapshot,
}
SOURCES = frozenset(source for source, _ in READERS)
# The store's own file in a snapshot, beside the responses.
RECORD = "store.json"
# A listing's name, and a response's file name, are one safe path part.
NAME = re.compile(r"[A-Za-z0-9_-]+")
DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Stored:
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
    handle, partial_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(handle)
    try:
        _write_synced(Path(partial_path), data)
        Path(partial_path).replace(path)
    finally:
        Path(partial_path).unlink(missing_ok=True)


def _record(fetched_at: datetime, blobs: Mapping[str, str]) -> bytes:
    moment = fetched_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = [{"attachment": key, "sha256": blobs[key]} for key in sorted(blobs)]
    return json.dumps({"fetched_at": moment, "blobs": entries}).encode()


def _visible_folders(folder: Path) -> list[Path]:
    # A crash leaves hidden folders, and Finder its .DS_Store: neither is stored data.
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


class RawStore:
    """Responses kept as received, by document and revision, and files by SHA-256.

    A snapshot is the folder ``<root>/<source>/<kind>/<id>/<revision>/``, one JSON file
    per response plus the store's record. It is written whole into a hidden folder and
    renamed into place, so it is either complete or absent, and its responses never
    change. A listing is ``<root>/<source>/listings/<name>.json``, replaced whole. A file
    is ``<root>/blobs/<digest[:2]>/<digest>``.
    """

    def __init__(self, root: Path) -> None:
        """Use ``root`` as the store, creating its folders as they are needed."""
        self.root = root

    def folder(self, document: Document) -> Path:
        """Return where the snapshot of this document at this revision is, or would be."""
        return self.root / document.source / document.kind / document.id / document.revision

    def put(
        self,
        source: str,
        kind: str,
        responses: Mapping[str, object],
        fetched_at: datetime,
        blobs: Mapping[str, str],
    ) -> Stored:
        """Store a snapshot, unless its revision is stored already; return what is stored.

        The responses are read by their kind's adapter first, so that nothing unreadable
        is stored, and the document they describe names the folder. Every file in
        ``blobs`` must be stored before the snapshot that names it.
        """
        snapshot = READERS[source, kind](responses)
        target = self.folder(snapshot.document)
        if target.is_dir():
            return self.read(snapshot.document)
        if RECORD in responses or not all(
            name.endswith(".json") and NAME.fullmatch(name.removesuffix(".json"))
            for name in responses
        ):
            message = "not plain JSON file names of responses"
            raise ValueError(message)
        self._check_blobs(snapshot, blobs)
        target.parent.mkdir(parents=True, exist_ok=True)
        hidden = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        try:
            for name, response in responses.items():
                _write_synced(hidden / name, json.dumps(response, ensure_ascii=False).encode())
            _write_synced(hidden / RECORD, _record(fetched_at, blobs))
            hidden.rename(target)
        except OSError:
            if not target.is_dir():
                raise
        finally:
            shutil.rmtree(hidden, ignore_errors=True)
        return self.read(snapshot.document)

    def read(self, document: Document) -> Stored:
        """Read the stored snapshot of this document at this revision."""
        return self._read(self.folder(document), READERS[document.source, document.kind])

    def _read(self, folder: Path, reader: Callable[[Mapping[str, object]], Snapshot]) -> Stored:
        record = Fields(json.loads((folder / RECORD).read_text(encoding="utf-8")), RECORD)
        blobs = {item.text("attachment"): item.text("sha256") for item in record.objects("blobs")}
        if not all(DIGEST.fullmatch(digest) for digest in blobs.values()):
            message = f"{RECORD}.blobs: expected SHA-256 digests"
            raise RepresentationError(message)
        return Stored(folder, reader(self.responses(folder)), record.time("fetched_at"), blobs)

    def _check_blobs(self, snapshot: Snapshot, blobs: Mapping[str, str]) -> None:
        known = {attachment.id for attachment in snapshot.attachments}
        if not set(blobs) <= known or not all(self.blob(d).is_file() for d in blobs.values()):
            message = "blobs: not attachments of this snapshot with stored files"
            raise ValueError(message)

    def has(self, document: Document) -> bool:
        """Say whether this document's revision is stored."""
        return self.folder(document).is_dir()

    def add_blobs(self, document: Document, blobs: Mapping[str, str]) -> Stored:
        """Record files downloaded after their snapshot was stored, such as on a retry."""
        stored = self.read(document)
        merged = {**stored.blobs, **blobs}
        self._check_blobs(stored.snapshot, merged)
        _replace_synced(stored.folder / RECORD, _record(stored.fetched_at, merged))
        return self.read(document)

    def latest(self, source: str, kind: str) -> Iterator[Stored]:
        """Yield the newest stored snapshot of each document of one kind."""
        reader = READERS[source, kind]
        for item in _visible_folders(self.root / source / kind):
            revisions = _visible_folders(item)
            if revisions:
                yield self._read(revisions[-1], reader)

    @staticmethod
    def responses(folder: Path) -> dict[str, object]:
        """Read the responses of a snapshot, as received, by file name."""
        return {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(folder.glob("*.json"))
            if path.name != RECORD
        }

    def put_listing(self, source: str, name: str, results: list[object]) -> Path:
        """Replace a listing: every result of a paged list, as one JSON list."""
        path = self._listing_path(source, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        _replace_synced(path, json.dumps(results, ensure_ascii=False).encode())
        return path

    def listing(self, source: str, name: str) -> list[Fields] | None:
        """Read a listing's results, or None when it was never stored."""
        path = self._listing_path(source, name)
        if not path.exists():
            return None
        return Fields.each(json.loads(path.read_text(encoding="utf-8")), path.name)

    def _listing_path(self, source: str, name: str) -> Path:
        if source not in SOURCES or not NAME.fullmatch(name):
            message = "not a source and a listing name"
            raise ValueError(message)
        return self.root / source / "listings" / f"{name}.json"

    def blob(self, digest: str) -> Path:
        """Return where the file with this SHA-256 is, or would be."""
        if not DIGEST.fullmatch(digest):
            message = "not a SHA-256 digest"
            raise ValueError(message)
        return self.root / "blobs" / digest[:2] / digest

    def put_blob(self, data: bytes) -> str:
        """Store a file under its SHA-256, once, and return the digest."""
        digest = hashlib.sha256(data).hexdigest()
        path = self.blob(digest)
        if path.exists():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        _replace_synced(path, data)
        return digest
