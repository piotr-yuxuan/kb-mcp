"""The vectors embedded so far, kept across index builds, in one SQLite file.

A vector is keyed by the SHA-256 of its model's fingerprint and the text embedded, so a
text is embedded once per model however often the index is rebuilt, and a vector is
never reused for another model or another version of one. Each ``put`` commits, so an
interrupted build keeps what it embedded, until a prune finds that no index reads it.
Deleting the file costs a full embedding of the mirror by the model, and downloads
nothing.

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

from kb_mcp.kernel.record import Record
from kb_mcp.observability.adapters.progress import task

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
# The auto_vacuum mode in which a store gives free pages back when told: a new store's.
INCREMENTAL = 2
# The store's size as its pages count it, its WAL aside.
SIZE = "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"


def key(fingerprint: str, text: str) -> str:
    """Name the vector of a text embedded by the model of this fingerprint."""
    return hashlib.sha256(f"{fingerprint}\0{text}".encode()).hexdigest()


def as_bytes(vector: NDArray[np.float32]) -> bytes:
    """Write a vector as the store and the index hold it."""
    return vector.astype(LAYOUT).tobytes()


class Swept(Record):
    """What a prune of the store did: the vectors deleted and those left, and its size.

    ``shrinks`` says whether the store gives freed pages back to the file system, as one
    made before plan 023 does only once converted; ``converted``, whether this prune
    converted it; ``unreclaimed``, why this prune's pages stayed in the file, empty when
    they did not.
    """

    deleted: int
    kept: int
    bytes_before: int
    bytes_after: int
    shrinks: bool
    converted: bool = False
    unreclaimed: str = ""


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

    def prune(self, kept: Iterable[str]) -> Swept:
        """Delete every vector whose key is not kept, then give the pages freed back.

        The deletions are one transaction, committed first, as the vacuum refuses to run
        in one; when they fail, sqlite3.Error is raised, and nothing is deleted. Then
        ``incremental_vacuum`` gives back every free page, those an earlier prune left
        included, read to its end in one call, as each of its steps frees one page. A
        store made before plan 023 is first converted, once: its mode set, then one
        ``VACUUM``, which rewrites the vectors kept and needs about their size free, in
        SQLite's temporary folder and beside the store. A vacuum that fails leaves the
        deletions standing, and says why; the next prune tries again.
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
def opened(path: Path) -> Iterator[VectorStore]:
    """Open the store at ``path``, creating it when there is none; close it after use.

    Two runs may use the store at once, an index and an evaluation: in WAL mode, reads
    hold no lock and leave no transaction open, and a write waits for the other's. A new
    store can give the pages that a prune frees back to the file system; one made before
    plan 023 can only once converted, as only a ``VACUUM`` changes its mode, which its
    first prune runs.
    Setting the mode on an existing store in that mode takes the write lock, so that
    opening it waits for another run's write, and a read-only file is refused: every run
    that opens the store writes to it anyway.
    """
    connection = sqlite3.connect(path, timeout=WAIT_S)
    try:
        # Before WAL, whose first write fixes a new store's mode for good.
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
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
