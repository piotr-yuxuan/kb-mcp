"""The vectors embedded so far, kept across index builds, in one SQLite file.

A vector is keyed by the SHA-256 of its model's fingerprint and the text embedded, so a
text is embedded once per model however often the index is rebuilt, and a vector is
never reused for another model or another version of one. Each ``put`` commits, so an
interrupted build keeps what it embedded. The store only grows; deleting the file costs
a full embedding, and nothing else.

Its lock, beside it, keeps a prune from deleting what a build in progress embeds: each
build holds it shared, a prune exclusive. ``flock`` locks an open file, so the kernel
releases the lock when the file is closed or its process ends, killed included.
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

from atlassian_offline_mcp.observability.adapters.progress import task

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

# Vectors are stored as little-endian float32.
LAYOUT = np.dtype("<f4")
# Texts embedded, then committed, at a time: what an interruption may lose at most.
BATCH = 256
# How long a write waits for another run's, in seconds: about one batch's embedding.
WAIT_S = 60
# How often a build waiting for a prune asks for the lock again, in seconds.
POLL_S = 0.1
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
        embed: Callable[[Sequence[str]], Sequence[NDArray[np.float32] | None]],
    ) -> tuple[dict[str, bytes], int]:
        """Give the vector of each text, by key, embedding and keeping those the store lacks.

        Texts are embedded BATCH at a time, those of like length together, each batch
        committed before the next, as the task ``texts to embed`` reports.
        A text that ``embed`` gives None for has no vector, here or in the store, so the
        next build asks again. Also return how many texts were embedded.
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


@contextmanager
def opened(path: Path) -> Iterator[VectorStore]:
    """Open the store at ``path``, creating it when there is none; close it after use.

    Two runs may use the store at once, an index and an evaluation: in WAL mode, reads
    hold no lock and leave no transaction open, and a write waits for the other's.
    """
    connection = sqlite3.connect(path, timeout=WAIT_S)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(CREATE)
        connection.commit()
        yield VectorStore(connection)
    finally:
        connection.close()


def lock_of(store: Path) -> Path:
    """Name the lock of the store at ``store``, beside it."""
    return store.with_name(f"{store.name}.lock")


@contextmanager
def shared(store: Path) -> Iterator[None]:
    """Hold the store's lock shared, as a build does from its start until its index is in.

    A prune holds it exclusive for seconds: a build that starts meanwhile says so,
    ``vectors.lock_wait``, then waits, and raises TimeoutError, naming the lock, once
    WAIT_S seconds have passed.
    """
    lock = lock_of(store)
    with lock.open("a") as file:
        for attempt in itertools.count():
            try:
                fcntl.flock(file, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                if attempt == 0:
                    structlog.get_logger().info("vectors.lock_wait", lock=str(lock))
                if attempt * POLL_S >= WAIT_S:
                    message = f"{lock}: a prune of the vector store held it for {WAIT_S} s"
                    raise TimeoutError(message) from None
                time.sleep(POLL_S)
            else:
                break
        yield


@contextmanager
def exclusive(store: Path) -> Iterator[bool]:
    """Hold the store's lock exclusive, as a prune does, unless a build holds it.

    Never waits: say whether the lock is held, so that a prune that finds a build in
    progress can be deferred.
    """
    with lock_of(store).open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held = False
        else:
            held = True
        yield held
