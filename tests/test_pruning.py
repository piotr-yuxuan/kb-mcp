"""Pruning the vector store to what the indexes on disk read (plan 023)."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import pytest
from structlog.testing import capture_logs

from atlassian_offline_mcp.search.adapters import vector_store
from atlassian_offline_mcp.search.adapters.sqlite_index import indexes_in
from atlassian_offline_mcp.search.app.indexing import Embedding, build_index
from tests.endpoint import tiny
from tests.mirrors import MOMENT, fillers
from tests.test_vectors import Counting

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from _pytest.monkeypatch import MonkeyPatch

    from atlassian_offline_mcp.search.adapters.embedding import Embedder

FILLER_PAGES = 5
# SQLite's auto_vacuum mode in which a store gives free pages back when told to.
INCREMENTAL = 2
# How long a test waits for another thread or process to reach a point, in seconds.
PATIENCE_S = 10.0


def test_the_indexes_under_a_folder_leave_builds_out(tmp_path: Path) -> None:
    """Indexes at any depth, in order; a build's empty file, a WAL and others are not."""
    folder = tmp_path / "indexes"
    wanted = [folder / "sections" / "tiny.sqlite", folder / "tiny.sqlite"]
    others = [folder / "windows" / ".index-1234.sqlite", folder / "windows" / "tiny.sqlite-wal"]
    for path in [*wanted, *others, folder / "notes.txt"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    assert indexes_in(folder) == sorted(wanted)
    assert indexes_in(tmp_path / "missing") == []


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """Give a data directory whose mirror has a few pages."""
    fillers(tmp_path / "data" / "docs", FILLER_PAGES)
    return tmp_path / "data"


def built(data: Path, embedder: Embedder | None = None) -> None:
    """Build the data directory's index by meaning, with its vector store."""
    embedding = Embedding(embedder or tiny(), data / "v.db")
    build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)


def events_named(events: list[MutableMapping[str, Any]], name: str) -> list[dict[str, Any]]:
    """Give the captured events of this name, each without its event."""
    named = (each for each in events if each["event"] == name)
    return [{key: value for key, value in each.items() if key != "event"} for each in named]


def test_a_build_holds_the_lock_until_its_index_is_in_place(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """While the build renames its index in, no prune takes the lock; once it is in, one can."""
    rename = Path.replace
    held_at_rename: list[bool] = []

    def watched(self: Path, target: Path) -> Path:
        with vector_store.exclusive(data / "v.db") as held:
            held_at_rename.append(held)
        return rename(self, target)

    monkeypatch.setattr(Path, "replace", watched)
    built(data)
    assert held_at_rename == [False]
    with vector_store.exclusive(data / "v.db") as held:
        assert held


def test_a_build_started_during_a_prune_waits_then_embeds_nothing_kept(data: Path) -> None:
    """It says it waits for the lock, then builds from the vectors that the store kept."""
    built(data)
    embedder = Counting(tiny())
    with capture_logs() as events:
        with vector_store.exclusive(data / "v.db") as held:
            assert held
            build = threading.Thread(target=built, args=(data, embedder))
            build.start()
            deadline = time.monotonic() + PATIENCE_S
            while not events_named(events, "vectors.lock_wait") and time.monotonic() < deadline:
                time.sleep(0.01)
        build.join(PATIENCE_S)
    assert not build.is_alive()
    lock = str(data / "v.db.lock")
    assert events_named(events, "vectors.lock_wait") == [{"lock": lock, "log_level": "info"}]
    assert events_named(events, "index.built")
    assert embedder.texts == []


def test_a_build_waits_for_a_prune_at_most_wait_s_then_names_the_lock(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Past the wait, the build gives up, its index not built, naming the lock it waited on."""
    monkeypatch.setattr(vector_store, "WAIT_S", 0.3)
    lock = re.escape(str(data / "v.db.lock"))
    with vector_store.exclusive(data / "v.db") as held:
        assert held
        with pytest.raises(TimeoutError, match=lock):
            built(data)
    assert not (data / "index.sqlite").exists()


def test_a_build_killed_while_it_holds_the_lock_leaves_it_free(data: Path) -> None:
    """The kernel releases a killed process's lock: no stale holder defers a prune."""
    # A build's process, in the data directory, holding the lock of the store v.db shared.
    with subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import fcntl, time; file = open('v.db.lock', 'a');"
                " fcntl.flock(file, fcntl.LOCK_SH); print('held', flush=True); time.sleep(60)"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        cwd=data,
    ) as child:
        assert child.stdout is not None
        assert child.stdout.readline() == "held\n"
        with vector_store.exclusive(data / "v.db") as held:
            assert not held
        child.kill()
        child.wait(PATIENCE_S)
    with vector_store.exclusive(data / "v.db") as held:
        assert held


def modes(path: Path) -> tuple[int, str]:
    """Give a store's auto_vacuum mode and journal mode, as SQLite numbers and names them."""
    with closing(sqlite3.connect(path)) as connection:
        vacuum = connection.execute("PRAGMA auto_vacuum").fetchone()[0]
        return vacuum, connection.execute("PRAGMA journal_mode").fetchone()[0]


def made_before_023(path: Path) -> None:
    """Make an empty store as ``opened`` made one before plan 023: WAL, then the table."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(vector_store.CREATE)
        connection.commit()


def test_a_new_store_gives_space_back_and_an_older_one_keeps_its_mode(tmp_path: Path) -> None:
    """Incremental for a store made now, WAL either way; one made before 023 stays as it was."""
    with vector_store.opened(tmp_path / "new.db"):
        pass
    made_before_023(tmp_path / "old.db")
    with vector_store.opened(tmp_path / "old.db"):
        pass
    assert modes(tmp_path / "new.db") == (INCREMENTAL, "wal")
    assert modes(tmp_path / "old.db") == (0, "wal")


def seeded(path: Path, count: int) -> list[str]:
    """Fill a store with vectors the size of 1,024 float32, whose pages a prune can free.

    The fakes' 16 dimensions fit inside B-tree pages, so that deleting some of them frees
    no whole page. Return the keys, in the order put.
    """
    keys = [vector_store.key("fingerprint", f"text {number}") for number in range(count)]
    with vector_store.opened(path) as store:
        store.put({key: os.urandom(4 * 1024) for key in keys})
    return keys


def freelist(path: Path) -> int:
    """Give how many pages of a store are free, in its file and not given back."""
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("PRAGMA freelist_count").fetchone()[0]


def test_a_prune_deletes_what_is_not_kept_and_gives_its_pages_back(tmp_path: Path) -> None:
    """Half the vectors deleted give back about half the store; none of the kept is lost."""
    keys = seeded(tmp_path / "v.db", 2000)
    with vector_store.opened(tmp_path / "v.db") as store:
        swept = store.prune(keys[::2])
        assert store.get(keys) == store.get(keys[::2])
        assert len(store.get(keys)) == len(keys[::2])
    assert swept.deleted == len(keys[1::2])
    assert swept.shrinks
    assert swept.unreclaimed == ""
    assert swept.bytes_after < 0.6 * swept.bytes_before
    assert freelist(tmp_path / "v.db") == 0
    assert not (tmp_path / "v.db-wal").exists()


def test_a_store_made_before_023_is_pruned_but_keeps_its_size(tmp_path: Path) -> None:
    """Its rows go; its pages stay free in the file, for later writes to reuse."""
    made_before_023(tmp_path / "v.db")
    keys = seeded(tmp_path / "v.db", 2000)
    with vector_store.opened(tmp_path / "v.db") as store:
        swept = store.prune(keys[::2])
    assert swept.deleted == len(keys[1::2])
    assert not swept.shrinks
    assert swept.bytes_after == swept.bytes_before
    assert freelist(tmp_path / "v.db") > 0


class InterruptedAtCommit(sqlite3.Connection):
    """A connection interrupted when it commits, as Ctrl-C could."""

    @override
    def commit(self) -> None:
        raise KeyboardInterrupt


class InterruptedAtVacuum(sqlite3.Connection):
    """A connection interrupted when it is told to give pages back, its deletions committed."""

    @override
    def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
        if sql == "PRAGMA incremental_vacuum":
            raise KeyboardInterrupt
        return super().execute(sql, parameters)


class FailingAtVacuum(sqlite3.Connection):
    """A connection whose vacuum fails, as a full disk could make it."""

    @override
    def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
        if sql == "PRAGMA incremental_vacuum":
            message = "database or disk is full"
            raise sqlite3.OperationalError(message)
        return super().execute(sql, parameters)


def test_a_prune_interrupted_before_its_commit_deletes_nothing(tmp_path: Path) -> None:
    """The deletions are one transaction: interrupted, it rolls back whole."""
    keys = seeded(tmp_path / "v.db", 200)
    with (
        closing(sqlite3.connect(tmp_path / "v.db", factory=InterruptedAtCommit)) as connection,
        pytest.raises(KeyboardInterrupt),
    ):
        vector_store.VectorStore(connection).prune(keys[:10])
    with vector_store.opened(tmp_path / "v.db") as store:
        assert len(store.get(keys)) == len(keys)


def test_a_prune_interrupted_before_its_vacuum_is_finished_by_the_next(tmp_path: Path) -> None:
    """Its deletions stand, their pages free; the next prune, deleting nothing, frees them."""
    keys = seeded(tmp_path / "v.db", 2000)
    with (
        closing(sqlite3.connect(tmp_path / "v.db", factory=InterruptedAtVacuum)) as connection,
        pytest.raises(KeyboardInterrupt),
    ):
        vector_store.VectorStore(connection).prune(keys[::2])
    assert freelist(tmp_path / "v.db") > 0
    with vector_store.opened(tmp_path / "v.db") as store:
        assert len(store.get(keys)) == len(keys[::2])
        swept = store.prune(keys[::2])
    assert swept.deleted == 0
    assert freelist(tmp_path / "v.db") == 0


def test_a_vacuum_that_fails_leaves_the_deletions_and_says_why(tmp_path: Path) -> None:
    """The space stays in the file; the vectors not kept are gone all the same."""
    keys = seeded(tmp_path / "v.db", 2000)
    with closing(sqlite3.connect(tmp_path / "v.db", factory=FailingAtVacuum)) as connection:
        swept = vector_store.VectorStore(connection).prune(keys[::2])
    assert swept.deleted == len(keys[1::2])
    assert swept.unreclaimed == "database or disk is full"
    assert freelist(tmp_path / "v.db") > 0
    with vector_store.opened(tmp_path / "v.db") as store:
        assert len(store.get(keys)) == len(keys[::2])


def test_a_reader_keeps_its_snapshot_while_a_prune_runs(tmp_path: Path) -> None:
    """A read transaction opened before sees the store as it was, others the deletions."""
    keys = seeded(tmp_path / "v.db", 2000)
    seen: list[int] = []
    count = "SELECT count(*) FROM vectors"
    with closing(sqlite3.connect(tmp_path / "v.db", autocommit=False)) as reader:
        before = reader.execute(count).fetchone()[0]

        class Watched(sqlite3.Connection):
            """A connection that lets the readers read just before it gives pages back."""

            @override
            def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
                if sql == "PRAGMA incremental_vacuum":
                    seen.append(reader.execute(count).fetchone()[0])
                    with closing(sqlite3.connect(tmp_path / "v.db")) as other:
                        seen.append(other.execute(count).fetchone()[0])
                return super().execute(sql, parameters)

        with closing(sqlite3.connect(tmp_path / "v.db", factory=Watched)) as connection:
            vector_store.VectorStore(connection).prune(keys[::2])
        seen.append(reader.execute(count).fetchone()[0])
    assert seen == [before, len(keys[::2]), before]
    assert before == len(keys)
