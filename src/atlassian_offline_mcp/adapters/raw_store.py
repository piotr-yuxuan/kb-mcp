"""The raw store: responses as the site returned them, and attached files by digest."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from atlassian_offline_mcp.domain.content import Document

# The store's own file in a snapshot: the digest of each downloaded attachment, by id.
BLOBS = "blobs.json"


def _write_synced(path: Path, data: bytes) -> None:
    with path.open("wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


class RawStore:
    """Responses kept as received, by document and revision, and files by SHA-256.

    A snapshot is the folder ``<root>/<source>/<kind>/<id>/<revision>/``, one JSON file
    per response. It is written whole into a hidden folder and renamed into place, so
    it is either complete or absent. A file is ``<root>/blobs/<digest[:2]>/<digest>``.
    """

    def __init__(self, root: Path) -> None:
        """Use ``root`` as the store, creating its folders as they are needed."""
        self.root = root

    def folder(self, document: Document) -> Path:
        """Return where the snapshot of this document at this revision is, or would be."""
        return self.root / document.source / document.kind / document.id / document.revision

    def put(self, document: Document, responses: Mapping[str, object]) -> Path:
        """Store a snapshot, by file name, unless this revision is already stored."""
        target = self.folder(document)
        if target.is_dir():
            return target
        if any(Path(name).name != name or not name.endswith(".json") for name in responses):
            message = f"not plain JSON file names: {sorted(responses)}"
            raise ValueError(message)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = Path(tempfile.mkdtemp(prefix=f".{document.revision}.", dir=target.parent))
        try:
            for name, response in responses.items():
                _write_synced(partial / name, json.dumps(response, ensure_ascii=False).encode())
            partial.rename(target)
        finally:
            shutil.rmtree(partial, ignore_errors=True)
        return target

    def latest(self, source: str, kind: str) -> Iterator[Path]:
        """Yield the newest complete snapshot of each stored document of one kind."""
        base = self.root / source / kind
        if not base.is_dir():
            return
        for item in sorted(base.iterdir()):
            revisions = sorted(path for path in item.iterdir() if not path.name.startswith("."))
            if revisions:
                yield revisions[-1]

    @staticmethod
    def responses(snapshot: Path) -> dict[str, object]:
        """Read every response of a snapshot, by file name."""
        return {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(snapshot.glob("*.json"))
        }

    def blob(self, digest: str) -> Path:
        """Return where the file with this SHA-256 is, or would be."""
        return self.root / "blobs" / digest[:2] / digest

    def put_blob(self, data: bytes) -> str:
        """Store a file under its SHA-256, once, and return the digest."""
        digest = hashlib.sha256(data).hexdigest()
        path = self.blob(digest)
        if path.exists():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, partial = tempfile.mkstemp(prefix=f".{digest}.", dir=path.parent)
        os.close(handle)
        try:
            _write_synced(Path(partial), data)
            Path(partial).replace(path)
        finally:
            Path(partial).unlink(missing_ok=True)
        return digest
