"""The vectors embedded so far, kept across index builds, in one SQLite file.

A vector is keyed by its model's fingerprint and its text, never reused for another model.
Its lock, beside it, is held shared by each build and exclusive by a prune; ``flock``
releases it when its file is closed or its process ends, killed included.
"""

from __future__ import annotations

import fcntl
import hashlib
import itertools
import json
import sqlite3
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import numpy as np
import structlog

from kb_mcp.kernel.records import Record
from kb_mcp.mirror.adapters.conversions import WAIT_S
from kb_mcp.observability.progress import task

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

# Vectors are stored as little-endian float32.
LAYOUT = np.dtype("<f4")
# Texts embedded, then committed, at a time: what an interruption may lose at most.
BATCH = 256
# How often a build waiting for a prune asks for the lock again, in seconds.
POLL_S = 0.1
CREATE = "CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)"
# The auto_vacuum mode in which a store gives free pages back when told: a new store's.
INCREMENTAL = 2
# The store's size as its pages count it, its WAL aside.
SIZE = "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"


def vector_key(fingerprint: str, text: str) -> str:
    """Name the vector of a text embedded by the model of this fingerprint."""
    return hashlib.sha256(f"{fingerprint}\0{text}".encode()).hexdigest()


def as_bytes(vector: NDArray[np.float32]) -> bytes:
    """Write a vector as the store and the index hold it."""
    return vector.astype(LAYOUT).tobytes()


class Swept(Record):
    """What a prune of the store did: the vectors deleted and those left, and its size.

    ``shrinks`` says whether the store gives freed pages back at all; ``unreclaimed``, why
    this prune's stayed in the file, empty when they did not.
    """

    deleted: int
    kept: int
    bytes_before: int
    bytes_after: int
    shrinks: bool
    converted: bool = False
    unreclaimed: str = ""


class VectorCache:
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
        embed: Callable[[Sequence[str]], Sequence[NDArray[np.float32] | None]],
    ) -> tuple[dict[str, bytes], int]:
        """Give the vector of each text, by key, embedding and keeping those the store lacks.

        Texts are embedded BATCH at a time, each batch committed before the next; a text
        that ``embed`` gives None for has no vector. Also return how many were embedded.
        """
        found = self.get(texts)
        missing = sorted((each for each in texts if each not in found), key=lambda k: len(texts[k]))
        embedded = 0
        with task("texts to embed", len(missing)) as embedding:
            for start in range(0, len(missing), BATCH):
                chosen = missing[start : start + BATCH]
                vectors = embed([texts[each] for each in chosen])
                batch = {
                    each: as_bytes(vector)
                    for each, vector in zip(chosen, vectors, strict=True)
                    if vector is not None
                }
                self.put(batch)
                found |= batch
                embedded += len(batch)
                embedding.advance(len(chosen))
        return found, embedded

    def prune(self, kept: Iterable[str]) -> Swept:
        """Delete every vector whose key is not kept, then give the pages freed back.

        The deletions commit first, as no vacuum runs in a transaction: when they fail,
        sqlite3.Error is raised and nothing is deleted. A store of another mode is converted
        once, by a ``VACUUM`` that needs about the kept vectors' size free.
        ``incremental_vacuum`` is read to its end, as each of its steps frees one page. A
        vacuum that fails leaves the deletions standing, and says why.
        """
        connection = self._connection
        before = connection.execute(SIZE).fetchone()[0]
        deleted = connection.execute(
            "DELETE FROM vectors WHERE key NOT IN (SELECT value FROM json_each(?))",
            (json.dumps(list(kept)),),
        ).rowcount
        connection.commit()
        converted, unreclaimed = False, ""
        try:
            if connection.execute("PRAGMA auto_vacuum").fetchone()[0] != INCREMENTAL:
                connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
                connection.execute("VACUUM")
                converted = True
            connection.execute("PRAGMA incremental_vacuum").fetchall()
        except sqlite3.Error as error:
            unreclaimed = str(error)
        kept = connection.execute("SELECT count(*) FROM vectors").fetchone()[0]
        after = connection.execute(SIZE).fetchone()[0]
        shrinks = connection.execute("PRAGMA auto_vacuum").fetchone()[0] == INCREMENTAL
        return Swept(
            deleted=deleted,
            kept=kept,
            bytes_before=before,
            bytes_after=after,
            shrinks=shrinks,
            converted=converted,
            unreclaimed=unreclaimed,
        )

    def count(self, keys: Iterable[str]) -> int:
        """Count the vectors that the store holds for these keys."""
        return self._connection.execute(
            "SELECT count(*) FROM vectors WHERE key IN (SELECT value FROM json_each(?))",
            (json.dumps(list(keys)),),
        ).fetchone()[0]


@contextmanager
def opened(path: Path) -> Iterator[VectorCache]:
    """Open the store at ``path``, creating it when there is none; close it after use.

    In WAL mode two runs may use it at once, a write waiting for the other's. Setting its
    mode takes the write lock: opening waits for another run's write, and refuses a
    read-only file, which every run that opens the store writes to anyway. Only a
    ``VACUUM`` changes an existing store's mode, which its first prune runs.
    """
    connection = sqlite3.connect(path, timeout=WAIT_S)
    try:
        # Before WAL, whose first write fixes a new store's mode for good.
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(CREATE)
        connection.commit()
        yield VectorCache(connection)
    finally:
        connection.close()


def lock_of(store: Path) -> Path:
    """Name the lock of the store at ``store``, beside it; an index's lock is named alike."""
    return store.with_name(f"{store.name}.lock")


@contextmanager
def locked(lock: Path, operation: int, event: str, holder: str) -> Iterator[None]:
    """Hold a lock file by ``flock``'s ``operation``, shared or exclusive, waiting for it.

    A lock found held is logged once as ``event``; raise TimeoutError, naming the lock and
    ``holder``, after WAIT_S seconds.
    """
    with lock.open("a") as file:
        for attempt in itertools.count():
            try:
                fcntl.flock(file, operation | fcntl.LOCK_NB)
            except BlockingIOError:
                if attempt == 0:
                    structlog.get_logger().info(event, lock=str(lock))
                if attempt * POLL_S >= WAIT_S:
                    message = f"{lock}: {holder} held it for {WAIT_S} s"
                    raise TimeoutError(message) from None
                time.sleep(POLL_S)
            else:
                break
        yield


@contextmanager
def shared(store: Path) -> Iterator[None]:
    """Hold the store's lock shared, as a build does from its start until its index is in.

    Wait for a prune; raise TimeoutError, naming the lock, after WAIT_S seconds.
    """
    with locked(lock_of(store), fcntl.LOCK_SH, "vectors.lock_wait", "a prune of the vector cache"):
        yield


@contextmanager
def exclusive(store: Path) -> Iterator[bool]:
    """Hold the store's lock exclusive, as a prune does, unless a build holds it.

    Never wait: say whether the lock is held.
    """
    with lock_of(store).open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held = False
        else:
            held = True
        yield held
