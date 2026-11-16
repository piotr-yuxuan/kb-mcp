"""The work log's copy store: what one work log's fetch keeps, in one JSON file of its own.

The layout: docs/reference/data-layout.md, section "The work log's copy store". This
module alone reads and writes it, through ``kernel.fields.Fields`` for its reading: a
field missing, of another type or refused by the domain is named by its path, never its
value.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.sources.worklog.fetch.domain.copies import Copies, WorklogCopy

if TYPE_CHECKING:
    from collections.abc import Iterator

# The store's file, and its writers' lock, in the source's folder.
COPIES = "copies.json"
LOCK = ".lock"
# Where a problem of the store as a whole lies, as its fetch and its prepare say it.
STORE = "copy store"


class CopyStoreBusyError(RuntimeError):
    """Another run is writing the work log's copy store."""


class CopyStore:
    """One work log's copy store: the folder ``<root>/<source>/``, its file and its lock.

    The file is replaced whole, through a hidden file renamed into place, so that a reader
    finds the last write whole or the one before it. One run at a time writes, inside
    ``writing``.
    """

    def __init__(self, root: Path, source: str) -> None:
        """Use the folder of ``source`` under ``root``, which the first write makes."""
        self.folder = root / source
        self.source = source
        self._lock: int | None = None

    @contextmanager
    def writing(self) -> Iterator[None]:
        """Hold the store's lock while writing; raise ``CopyStoreBusyError`` if it is held."""
        self.folder.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.folder / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(handle)
            raise CopyStoreBusyError from None
        self._lock = handle
        try:
            yield
        finally:
            self._lock = None
            os.close(handle)  # closing the descriptor releases the lock

    def read(self) -> Copies | None:
        """Read what the store holds, or None when it was never written.

        Raises RepresentationError, naming the file from the stores' root and the field,
        for a file that cannot be read, is not JSON, or holds a field missing, of another
        type, or refused.
        """
        where = f"{self.source}/{COPIES}"
        try:
            data = (self.folder / COPIES).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            message = f"{where}: not read: {type(error).__name__}"
            raise RepresentationError(message) from None
        try:
            fields = Fields(json.loads(data), where)
        except ValueError as error:
            # Not UTF-8 or not JSON, whose messages may quote the file; or not an object.
            reason = str(error) if isinstance(error, RepresentationError) else f"{where}: not JSON"
            raise RepresentationError(reason) from None
        migrated = fields.object("migrated")
        documents: dict[str, WorklogCopy] = {}
        for entry in fields.objects("documents"):
            links = tuple(
                (link.text("relation"), link.text("document")) for link in entry.objects("links")
            )
            with entry.refusals():
                each = WorklogCopy(
                    type=entry.text("type"),
                    id=entry.text("id"),
                    title=entry.text("title"),
                    status=entry.text("status"),
                    labels=entry.texts("labels"),
                    breadcrumb=entry.texts("breadcrumb"),
                    people=entry.texts("people"),
                    links=links,
                    created=entry.time("created"),
                    updated=entry.time("updated"),
                    file=entry.text("file"),
                    text=entry.text("text"),
                )
            if each.id in documents:
                message = f"{entry.path}: id: given twice"
                raise RepresentationError(message)
            documents[each.id] = each
        with fields.refusals():
            return Copies(
                documents=documents,
                migrated={key: migrated.time(key) for key in migrated.value},
                as_of=None if fields.optional_text("as_of") is None else fields.time("as_of"),
            )

    def put(self, copies: Copies) -> None:
        """Replace what the store holds, whole; only inside ``writing``."""
        if self._lock is None:
            message = "the copy store is written only inside CopyStore.writing()"
            raise RuntimeError(message)
        value = {
            "as_of": None if copies.as_of is None else copies.as_of.isoformat(),
            "migrated": {key: moment.isoformat() for key, moment in copies.migrated.items()},
            "documents": [
                {
                    "type": each.type,
                    "id": each.id,
                    "title": each.title,
                    "status": each.status,
                    "labels": list(each.labels),
                    "breadcrumb": list(each.breadcrumb),
                    "people": list(each.people),
                    "links": [
                        {"relation": relation, "document": other} for relation, other in each.links
                    ],
                    "created": each.created.isoformat(),
                    "updated": each.updated.isoformat(),
                    "file": each.file,
                    "text": each.text,
                }
                for each in copies.documents.values()
            ],
        }
        handle, hidden = tempfile.mkstemp(prefix=f".{COPIES}.", dir=self.folder)
        try:
            with os.fdopen(handle, "wb") as file:
                # ASCII escapes, so that any text read is stored, whatever it holds.
                file.write(json.dumps(value).encode())
                file.flush()
                os.fsync(file.fileno())
            Path(hidden).replace(self.folder / COPIES)
        finally:
            Path(hidden).unlink(missing_ok=True)
