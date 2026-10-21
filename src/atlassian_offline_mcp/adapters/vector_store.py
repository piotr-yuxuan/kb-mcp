"""The vectors embedded so far, kept across index builds, in one SQLite file.

A vector is keyed by the SHA-256 of its model's fingerprint and the text embedded, so a
text is embedded once per model however often the index is rebuilt, and a vector is
never reused for another model or another version of one. Each ``put`` commits, so an
interrupted build keeps what it embedded. The store only grows; deleting the file costs
a full embedding, and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

# Vectors are stored as little-endian float32.
LAYOUT = np.dtype("<f4")
# Texts embedded, then committed, at a time: what an interruption may lose at most.
BATCH = 256
CREATE = "CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)"


def key(fingerprint: str, text: str) -> str:
    """Name the vector of a text embedded by the model of this fingerprint."""
    return hashlib.sha256(f"{fingerprint}\0{text}".encode()).hexdigest()


def as_bytes(vector: NDArray[np.float32]) -> bytes:
    """Write a vector as the store and the index hold it."""
    return vector.astype(LAYOUT).tobytes()


class VectorStore:
    """Vectors by key, in an open store."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Use an open connection whose table exists."""
        self._connection = connection

    def get(self, keys: Iterable[str]) -> dict[str, bytes]:
        """Give the vectors that the store holds for these keys."""
        rows = self._connection.execute(
            "SELECT key, vector FROM vectors WHERE key IN (SELECT value FROM json_each(?))",
            (json.dumps(list(keys)),),
        )
        return dict(rows.fetchall())

    def put(self, vectors: Mapping[str, bytes]) -> None:
        """Keep these vectors, and commit them at once."""
        self._connection.executemany(
            "INSERT OR REPLACE INTO vectors (key, vector) VALUES (?, ?)", vectors.items()
        )
        self._connection.commit()

    def vectors(
        self,
        texts: Mapping[str, str],
        embed: Callable[[Sequence[str]], NDArray[np.float32]],
        progress: Callable[[int, int], None],
    ) -> tuple[dict[str, bytes], int]:
        """Give the vector of each text, by key, embedding and keeping those the store lacks.

        Texts are embedded BATCH at a time, those of like length together, each batch
        committed before the next; ``progress`` hears how many of the missing are done.
        Also return how many texts were embedded.
        """
        found = self.get(texts)
        missing = sorted((each for each in texts if each not in found), key=lambda k: len(texts[k]))
        for start in range(0, len(missing), BATCH):
            chosen = missing[start : start + BATCH]
            vectors = embed([texts[each] for each in chosen])
            batch = {each: as_bytes(vector) for each, vector in zip(chosen, vectors, strict=True)}
            self.put(batch)
            found |= batch
            progress(start + len(chosen), len(missing))
        return found, len(missing)


@contextmanager
def opened(path: Path) -> Iterator[VectorStore]:
    """Open the store at ``path``, creating it when there is none; close it after use."""
    connection = sqlite3.connect(path, autocommit=False)
    try:
        connection.execute(CREATE)
        connection.commit()
        yield VectorStore(connection)
    finally:
        connection.close()
