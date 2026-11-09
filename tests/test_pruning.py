"""Pruning the vector store to what the indexes on disk read (plan 023)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from copy import replace
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import pytest
from pydantic_core import to_json
from structlog.testing import capture_logs

from kb_mcp.cli.commands import embed as embed_command
from kb_mcp.cli.main import main
from kb_mcp.config.domain.settings import Settings
from kb_mcp.evaluation.app.evaluation import Target, evaluate
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.search.adapters import vector_store
from kb_mcp.search.adapters.sqlite_index import indexes_in, reading
from kb_mcp.search.app.indexing import (
    Embedding,
    Indexing,
    build_index,
    fill_and_prune,
    update_index,
)
from kb_mcp.search.app.pruning import (
    DEFERRED,
    NO_DOCUMENT,
    SKIPPED,
    UNLISTED,
    UNREADABLE,
    Pruned,
    Written,
    prune,
)
from tests.endpoint import Scripted, scripted, serving, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.test_evaluate import GOLDEN, golden, ticking
from tests.test_observed import said
from tests.test_vectors import BODY, Counting

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

    import numpy as np
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from numpy.typing import NDArray

    from kb_mcp.kernel.chunking import Chunking
    from kb_mcp.search.adapters.embedding import Embedder
    from kb_mcp.search.app.indexing import Filled
    from tests.conftest import InMemory

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


@pytest.mark.parametrize("target", ["sections", "sections/tiny.sqlite", "gone"])
def test_a_link_below_the_folder_is_named_and_not_followed(tmp_path: Path, target: str) -> None:
    """To a folder, to an index, dangling: each raises, naming the link, lest a cycle not end."""
    folder = tmp_path / "indexes"
    (folder / "sections").mkdir(parents=True)
    (folder / "sections" / "tiny.sqlite").write_bytes(b"")
    (folder / "linked").symlink_to(folder / target)
    with pytest.raises(OSError, match="a link, which is not followed") as raised:
        indexes_in(folder)
    assert raised.value.filename == str(folder / "linked")


def test_the_folder_and_its_parent_may_be_links_but_not_dangling_ones(tmp_path: Path) -> None:
    """Reached through links, the indexes are listed; a parent whose target is gone raises."""
    disk = tmp_path / "disk"
    (disk / "indexes" / "sections").mkdir(parents=True)
    (disk / "indexes" / "sections" / "tiny.sqlite").write_bytes(b"")
    (tmp_path / "eval").symlink_to(disk)
    listed = [tmp_path / "eval" / "indexes" / "sections" / "tiny.sqlite"]
    assert indexes_in(tmp_path / "eval" / "indexes") == listed
    (tmp_path / "top").symlink_to(disk / "indexes")
    assert indexes_in(tmp_path / "top") == [tmp_path / "top" / "sections" / "tiny.sqlite"]
    (disk / "indexes").rename(disk / "elsewhere")
    assert indexes_in(tmp_path / "eval" / "indexes") == []
    disk.rename(tmp_path / "away")
    with pytest.raises(FileNotFoundError):
        indexes_in(tmp_path / "eval" / "indexes")


def test_only_regular_files_are_indexes(tmp_path: Path) -> None:
    """A FIFO named as an index is none: reading it would block the prune, and the lock."""
    folder = tmp_path / "indexes"
    folder.mkdir()
    os.mkfifo(folder / "x.sqlite")
    (folder / "tiny.sqlite").write_bytes(b"")
    assert indexes_in(folder) == [folder / "tiny.sqlite"]


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
    keys = [vector_store.vector_key("fingerprint", f"text {number}") for number in range(count)]
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
    assert (swept.deleted, swept.kept) == (len(keys[1::2]), len(keys[::2]))
    assert swept.shrinks
    assert swept.unreclaimed == ""
    assert swept.bytes_after < 0.6 * swept.bytes_before
    assert freelist(tmp_path / "v.db") == 0
    assert not (tmp_path / "v.db-wal").exists()


def test_a_store_made_before_023_is_converted_at_its_first_prune(tmp_path: Path) -> None:
    """Its rows deleted, it is rewritten once to give space back; the next prune does not."""
    made_before_023(tmp_path / "v.db")
    keys = seeded(tmp_path / "v.db", 2000)
    with vector_store.opened(tmp_path / "v.db") as store:
        swept = store.prune(keys[::2])
        again = store.prune(keys[::2])
    assert (swept.deleted, swept.converted, swept.shrinks) == (len(keys[1::2]), True, True)
    assert swept.bytes_after < 0.6 * swept.bytes_before
    assert (again.converted, again.deleted) == (False, 0)
    assert modes(tmp_path / "v.db") == (INCREMENTAL, "wal")
    assert freelist(tmp_path / "v.db") == 0


class FailingAtConversion(sqlite3.Connection):
    """A connection whose VACUUM fails, as one without the space for its copy would."""

    @override
    def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
        if sql == "VACUUM":
            message = "database or disk is full"
            raise sqlite3.OperationalError(message)
        return super().execute(sql, parameters)


def test_a_conversion_that_fails_keeps_the_deletions_and_is_tried_again(
    tmp_path: Path,
) -> None:
    """Not converted, the store says why; its deletions stand; the next prune converts it."""
    made_before_023(tmp_path / "v.db")
    keys = seeded(tmp_path / "v.db", 2000)
    with closing(sqlite3.connect(tmp_path / "v.db", factory=FailingAtConversion)) as connection:
        swept = vector_store.VectorStore(connection).prune(keys[::2])
    assert (swept.deleted, swept.converted, swept.shrinks) == (len(keys[1::2]), False, False)
    assert swept.unreclaimed == "database or disk is full"
    with vector_store.opened(tmp_path / "v.db") as store:
        assert len(store.get(keys)) == len(keys[::2])
        again = store.prune(keys[::2])
    assert (again.deleted, again.converted, again.shrinks) == (0, True, True)


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


def indexing(data: Path) -> Indexing:
    """Say how index builds the data directory's index by meaning, with the scripted model."""
    return Indexing(
        docs=data / "docs",
        index=data / "index.sqlite",
        vectors=data / "vectors.sqlite",
        evaluation_indexes=data / "eval" / "indexes",
        aliases=data / "aliases.toml",
        model="tiny",
        chunking="sections",
        endpoint=scripted,
    )


def refreshed(indexing: Indexing) -> Filled | None:
    """Update the index, as ``kb-mcp index`` does; then fill and prune, as ``embed`` does."""
    update_index(indexing, MOMENT)
    return fill_and_prune(indexing)


def evaluated(data: Path, store: Path, chunking: Chunking) -> Path:
    """Build an evaluation's index of the mirror as eval lays it out, with ``store``."""
    index = data / "eval" / "indexes" / chunking / "tiny.sqlite"
    index.parent.mkdir(parents=True, exist_ok=True)
    build_index(data / "docs", index, MOMENT, Embedding(tiny(), store, chunking))
    return index


def stored(store: Path) -> set[str]:
    """Give the keys of the vectors that a store holds."""
    with closing(sqlite3.connect(store)) as connection:
        return {row[0] for row in connection.execute("SELECT key FROM vectors")}


def read_by(index: Path) -> set[str]:
    """Give the keys of the vectors that an index reads."""
    with reading(index) as reader:
        return reader.keys()


def pruned(indexed: Filled | None) -> Pruned:
    """Give what the prune that followed a fill did; there must have been a fill."""
    assert indexed is not None
    assert indexed.pruned is not None
    return indexed.pruned


# Two pages of two sections, whose second the test writes, under a page that only the
# chunking section-paths embeds, so that no evaluation's index shares their sections' texts.
GONE = "# Gone\n\nThe page to delete.\n\n## Why\n\n"
EDITED = "# Edited\n\nThe page to edit.\n\n## Change\n\n"
HOME = ("Home",)
# What then no index reads: another model's vector, the deleted page's two sections, the
# edited section's old text.
ORPHANS = 4


def test_a_prune_keeps_what_the_indexes_read_and_nothing_else(
    data: Path, telemetry: InMemory
) -> None:
    """The index's and two evaluation indexes' vectors stay; the others go, counted.

    The vectors kept equal those of the same three indexes built into a fresh store: the
    evaluation's from the mirror as it was, the index from the mirror as it is. Those
    deleted are another model's, and the texts of a deleted page and an edited one that
    no index reads any more.
    """
    gone = (
        data
        / "docs"
        / write(data / "docs", page("100", "Gone", breadcrumb=HOME), f"{GONE}It is old.\n")
    )
    write(data / "docs", page("200", "Edited", breadcrumb=HOME), f"{EDITED}The text before.\n")
    store, fresh = data / "vectors.sqlite", data.parent / "fresh.db"
    pruned(refreshed(indexing(data)))
    for each in (store, fresh):
        evaluated(data, each, "windows")
        evaluated(data, each, "section-paths")
    other = vector_store.vector_key("another model", "a text")
    with vector_store.opened(store) as opened:
        opened.put({other: bytes(64)})
    gone.unlink()
    write(data / "docs", page("200", "Edited", breadcrumb=HOME), f"{EDITED}The text after.\n")
    (data / "eval" / "indexes" / "windows" / ".index-1234.sqlite").write_bytes(b"")
    build_index(data / "docs", data.parent / "fresh.sqlite", MOMENT, Embedding(tiny(), fresh))
    before = stored(store)
    telemetry.spans.clear()
    telemetry.measured()
    indexed = refreshed(indexing(data))
    done = pruned(indexed)
    assert stored(store) == stored(fresh)
    alone = stored(fresh) - read_by(data / "index.sqlite")
    deleted = len(before | stored(fresh)) - len(stored(fresh))
    assert other not in stored(store)
    assert deleted == ORPHANS
    assert done == Pruned(
        outcome="pruned",
        kept=len(stored(fresh)),
        kept_for_evaluation=len(alone),
        deleted=deleted,
        bytes_before=done.bytes_before,
        bytes_after=done.bytes_after,
        seconds=done.seconds,
        shrinks=True,
        reclaimed=True,
    )
    assert done.bytes_after <= done.bytes_before
    [span] = [each for each in telemetry.spans.get_finished_spans() if each.name == "index.prune"]
    assert span.attributes == {"kb_mcp.outcome": "pruned", "kb_mcp.deleted": deleted}
    measured = telemetry.measured()
    points = measured["kb_mcp.vectors"].data.data_points
    counts = {
        point.attributes["kb_mcp.outcome"]: point.value for point in points if point.attributes
    }
    assert counts == {"kept": len(stored(fresh)), "pruned": deleted}
    [size] = measured["kb_mcp.vectors.bytes"].data.data_points
    assert size.value == done.bytes_after
    assert json.loads(to_json(indexed))["pruned"] == done.model_dump()
    assert f"vectors pruned: {deleted}\nvector store: " in embed_command.text(indexed, "short")
    detailed = embed_command.text(indexed, "detailed")
    assert f"kept {len(stored(fresh))} vectors ({len(alone)} for the evaluation alone)" in detailed
    assert f", pruned {deleted}; the vector store from " in detailed


def test_a_second_index_with_nothing_changed_embeds_and_deletes_nothing(data: Path) -> None:
    """Then, an evaluation's index deleted, the next deletes the vectors that it alone read."""
    pruned(refreshed(indexing(data)))
    windows = evaluated(data, data / "vectors.sqlite", "windows")
    again = refreshed(indexing(data))
    assert again is not None
    assert (again.embedded, again.unchanged) == (0, True)
    assert pruned(again).deleted == 0
    alone = read_by(windows) - read_by(data / "index.sqlite")
    windows.unlink()
    assert pruned(refreshed(indexing(data))).deleted == len(alone) > 0


def test_a_real_evaluation_s_vectors_outlive_the_next_index(tmp_path: Path) -> None:
    """The evaluation writes its indexes where the prune looks: their vectors all stay."""
    data = tmp_path / "data"
    evaluable(data)
    settings = Settings(data_dir=data, model="tiny")
    chunkings: tuple[Chunking, ...] = ("windows", "section-paths")
    targets = [Target(tiny(), chunking) for chunking in chunkings]
    evaluate(settings, golden(data), targets, ticking(), MOMENT)
    pruned(refreshed(indexing(data)))
    for chunking in chunkings:
        assert read_by(settings.evaluation_indexes / chunking / "tiny.sqlite") <= stored(
            settings.vectors
        )


def held_back(data: Path, capsys: CaptureFixture[str]) -> tuple[int, dict[str, Any], str]:
    """Index by meaning, as the command does; give its exit status, its prune, its stderr.

    A vector of another model is put in the store first, which no index reads.
    """
    with vector_store.opened(data / "vectors.sqlite") as opened:
        opened.put({vector_store.vector_key("another model", "a text"): bytes(64)})
    status, result, err = command(data, capsys)
    assert vector_store.vector_key("another model", "a text") in stored(data / "vectors.sqlite")
    return status, result["pruned"], err


def command(
    data: Path, capsys: CaptureFixture[str], mode: str = "hybrid"
) -> tuple[int, dict[str, Any], str]:
    """Run index in ``mode`` with the tiny model, then embed but in the lexical mode.

    Give the status, the JSON and the stderr of the last; what earlier steps of the test
    wrote is left out.
    """
    config = data.parent / "config.toml"
    with serving(Scripted()) as url:
        settings = f'model = "tiny"\nembedding_url = {json.dumps(url)}\nsearch_mode = "{mode}"\n'
        config.write_text(settings, encoding="utf-8")
        options = ["--yes", "--format", "json", "--config", str(config), "--data-dir", str(data)]
        main(["index", *options])
        capsys.readouterr()
        status = main(["index", *options]) if mode == "lexical" else main(["embed", *options])
    out, err = capsys.readouterr()
    return status, json.loads(out), err


def test_an_evaluation_index_without_keys_holds_the_prune_back(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Built before pieces recorded their keys: nothing deleted, the file named, exit 0."""
    windows = evaluated(data, data / "vectors.sqlite", "windows")
    with closing(sqlite3.connect(windows)) as connection:
        connection.execute("ALTER TABLE pieces DROP COLUMN key")
        connection.commit()
    status, result, err = held_back(data, capsys)
    assert (status, result["outcome"], result["file"]) == (0, "held back", str(windows))
    assert result["reason"] == UNREADABLE
    assert ("warning", "index.prune_skipped") in said(err)


def test_a_file_that_is_no_index_holds_the_prune_back(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Random bytes named as an index under the evaluation's folder: nothing deleted."""
    stray = data / "eval" / "indexes" / "x.sqlite"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(os.urandom(512))
    status, result, err = held_back(data, capsys)
    assert (status, result["outcome"], result["file"]) == (0, "held back", str(stray))
    assert ("warning", "index.prune_skipped") in said(err)


def test_a_build_that_skipped_a_file_holds_the_prune_back(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Its index lacks a document of the mirror, whose vectors stay; exit 1, as without it."""
    broken = data / "docs" / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    status, result, err = held_back(data, capsys)
    assert (status, result["outcome"], result["file"], result["reason"]) == (
        1,
        "held back",
        None,
        SKIPPED,
    )
    assert ("warning", "index.prune_skipped") in said(err)


def test_a_mirror_with_no_document_holds_the_prune_back(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """An empty mirror would leave nothing to keep: the store stays whole; exit 0."""
    for file in (data / "docs").rglob("*.md"):
        file.unlink()
    status, result, err = held_back(data, capsys)
    assert (status, result["outcome"], result["reason"]) == (0, "held back", NO_DOCUMENT)
    assert ("warning", "index.prune_skipped") in said(err)


def test_words_alone_leave_the_store_untouched(data: Path, capsys: CaptureFixture[str]) -> None:
    """The lexical mode never opens the store: same bytes, same time, no prune, no line."""
    command(data, capsys)
    store = data / "vectors.sqlite"
    before = (store.read_bytes(), store.stat().st_mtime_ns)
    status, result, err = command(data, capsys, "lexical")
    assert (status, result["pruned"]) == (0, None)
    assert (store.read_bytes(), store.stat().st_mtime_ns) == before
    assert "the vector store keeps only" not in err


def test_the_summary_says_the_prune_before_the_question_by_meaning(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """By meaning, a line of the summary says that the store is then pruned."""
    _, result, err = command(data, capsys)
    assert "then: the vector store keeps only the vectors that the index and eval's read" in err
    assert result["pruned"]["outcome"] == "pruned"


@dataclass
class Paused(Counting):
    """A counting embedder that, once asked, waits until told to go on."""

    inside: threading.Event = field(default_factory=threading.Event)
    resume: threading.Event = field(default_factory=threading.Event)

    @override
    def documents(self, texts: Sequence[str]) -> list[NDArray[np.float32] | None]:
        self.inside.set()
        self.resume.wait(PATIENCE_S)
        return super().documents(texts)


def test_a_prune_during_a_build_is_deferred_and_done_by_the_next(data: Path) -> None:
    """While an evaluation's build embeds, nothing is deleted; once it is in, its vectors stay."""
    pruned(refreshed(indexing(data)))
    other = vector_store.vector_key("another model", "a text")
    with vector_store.opened(data / "vectors.sqlite") as opened:
        opened.put({other: bytes(64)})
    paused, windows = Paused(tiny()), data / "eval" / "indexes" / "windows" / "tiny.sqlite"
    windows.parent.mkdir(parents=True)
    embedding = Embedding(paused, data / "vectors.sqlite", "windows")
    build = threading.Thread(target=build_index, args=(data / "docs", windows, MOMENT, embedding))
    build.start()
    assert paused.inside.wait(PATIENCE_S)
    indexed = refreshed(indexing(data))
    paused.resume.set()
    build.join(PATIENCE_S)
    deferred = pruned(indexed)
    assert (deferred.outcome, deferred.deleted, deferred.reason) == ("deferred", 0, DEFERRED)
    assert indexed is not None
    assert embed_command.text(indexed, "short").endswith("vectors pruned: none, deferred\n")
    said_fully = embed_command.text(indexed, "detailed")
    assert said_fully.endswith(f"vector store not pruned, deferred: {DEFERRED}\n")
    assert other in stored(data / "vectors.sqlite")
    done = pruned(refreshed(indexing(data)))
    assert (done.outcome, done.deleted) == ("pruned", 1)
    assert read_by(windows) <= stored(data / "vectors.sqlite")


def test_a_store_that_cannot_delete_fails_the_prune_not_the_index(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Its error is the reason, nothing is deleted, and the index is in place."""

    def locked(*_: object) -> vector_store.Swept:
        message = "database is locked"
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(vector_store.VectorStore, "prune", locked)
    indexed = refreshed(indexing(data))
    assert indexed is not None
    assert indexed.whole
    assert pruned(indexed) == Pruned(
        outcome="failed", seconds=pruned(indexed).seconds, reason="database is locked"
    )


def test_an_index_interrupted_while_it_prunes_is_in_place(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Ctrl-C during the prune: the filled index stays, as it was renamed in before."""
    pruned(refreshed(indexing(data)))
    write(data / "docs", page("200", "Edited", breadcrumb=HOME), f"{EDITED}The text after.\n")
    update_index(indexing(data), MOMENT)
    with reading(data / "index.sqlite") as reader:
        (updated, awaiting) = (reader.build(), reader.index_status().awaiting)

    def interrupted(*_: object) -> vector_store.Swept:
        raise KeyboardInterrupt

    monkeypatch.setattr(vector_store.VectorStore, "prune", interrupted)
    with pytest.raises(KeyboardInterrupt):
        fill_and_prune(indexing(data))
    assert awaiting == 1
    with reading(data / "index.sqlite") as reader:
        assert (reader.build() != updated, reader.index_status().awaiting) == (True, 0)


def kept_whole(data: Path) -> str:
    """Put in the store a vector that no index reads; give its key, which a prune deletes."""
    other = vector_store.vector_key("another model", "a text")
    with vector_store.opened(data / "vectors.sqlite") as opened:
        opened.put({other: bytes(64)})
    return other


def test_a_damaged_evaluation_index_holds_the_prune_back(data: Path) -> None:
    """A page of its pieces overwritten: the file is named, and nothing is deleted."""
    pruned(refreshed(indexing(data)))
    windows = evaluated(data, data / "vectors.sqlite", "windows")
    with closing(sqlite3.connect(windows)) as connection:
        root = connection.execute("SELECT rootpage FROM sqlite_master WHERE name = 'pieces'")
        page_number = root.fetchone()[0]
        size = connection.execute("PRAGMA page_size").fetchone()[0]
    with windows.open("r+b") as file:
        file.seek((page_number - 1) * size)
        file.write(b"\xff" * size)
    other = kept_whole(data)
    done = pruned(refreshed(indexing(data)))
    assert (done.outcome, done.file, done.reason) == ("held back", str(windows), UNREADABLE)
    assert other in stored(data / "vectors.sqlite")


def test_a_link_among_the_evaluation_s_indexes_holds_the_prune_back(data: Path) -> None:
    """Not followed, lest a cycle of links never end: it is named, and nothing is deleted."""
    pruned(refreshed(indexing(data)))
    elsewhere = data.parent / "elsewhere"
    windows = evaluated(data, data / "vectors.sqlite", "windows")
    elsewhere.mkdir()
    windows.parent.rename(elsewhere / "windows")
    windows.parent.symlink_to(elsewhere / "windows")
    other = kept_whole(data)
    done = pruned(refreshed(indexing(data)))
    assert (done.outcome, done.file, done.reason) == ("held back", str(windows.parent), UNLISTED)
    assert other in stored(data / "vectors.sqlite")


def test_a_dangling_link_among_the_evaluation_s_indexes_holds_the_prune_back(
    data: Path,
) -> None:
    """Its target gone, as an unmounted disk's: it is named, and nothing is deleted."""
    pruned(refreshed(indexing(data)))
    folder = data / "eval" / "indexes"
    folder.mkdir(parents=True)
    (folder / "windows").symlink_to(data.parent / "unmounted" / "windows")
    other = kept_whole(data)
    done = pruned(refreshed(indexing(data)))
    assert (done.outcome, done.file) == ("held back", str(folder / "windows"))
    assert other in stored(data / "vectors.sqlite")


def test_an_evaluation_folder_on_a_disk_away_holds_the_prune_back(data: Path) -> None:
    """<data>/eval a link whose target is gone: its indexes unseen, nothing is deleted."""
    pruned(refreshed(indexing(data)))
    evaluated(data, data / "vectors.sqlite", "windows")
    (data / "eval").rename(data.parent / "disk")
    (data / "eval").symlink_to(data.parent / "disk")
    pruned(refreshed(indexing(data)))
    (data.parent / "disk").rename(data.parent / "away")
    other = kept_whole(data)
    done = pruned(refreshed(indexing(data)))
    assert (done.outcome, done.file, done.reason) == (
        "held back",
        str(data / "eval" / "indexes"),
        UNLISTED,
    )
    assert other in stored(data / "vectors.sqlite")


@pytest.mark.skipif(os.geteuid() == 0, reason="root lists every folder")
@pytest.mark.parametrize("closed", ["eval", "eval/indexes/windows"])
def test_a_folder_that_cannot_be_listed_holds_the_prune_back(data: Path, closed: str) -> None:
    """An index there would go unseen, and its vectors deleted: nothing is."""
    pruned(refreshed(indexing(data)))
    evaluated(data, data / "vectors.sqlite", "windows")
    other = kept_whole(data)
    (data / closed).chmod(0)
    try:
        done = pruned(refreshed(indexing(data)))
    finally:
        (data / closed).chmod(0o700)
    unseen = data / "eval" / "indexes" if closed == "eval" else data / closed
    assert (done.outcome, done.file, done.reason) == ("held back", str(unseen), UNLISTED)
    assert other in stored(data / "vectors.sqlite")


def test_an_evaluation_index_without_a_model_holds_the_prune_back(data: Path) -> None:
    """Its meta lacks the model: it cannot say what it reads, and the prune does not fail."""
    pruned(refreshed(indexing(data)))
    windows = evaluated(data, data / "vectors.sqlite", "windows")
    with closing(sqlite3.connect(windows)) as connection:
        connection.execute("DELETE FROM meta WHERE name IN ('model', 'fingerprint')")
        connection.commit()
    other = kept_whole(data)
    done = pruned(refreshed(indexing(data)))
    assert (done.outcome, done.file, done.reason) == ("held back", str(windows), UNREADABLE)
    assert other in stored(data / "vectors.sqlite")


def test_each_outcome_is_said_short_and_in_detail() -> None:
    """Deferred, held back with its file, failed: the outcome, and in detail why."""
    file = "/data/eval/indexes/x.sqlite"
    cases = {
        Pruned(outcome="deferred", reason=DEFERRED): f"deferred: {DEFERRED}",
        Pruned(
            outcome="held back", reason=UNREADABLE, file=file
        ): f"held back: {UNREADABLE} ({file})",
        Pruned(outcome="failed", reason="database is locked"): "failed: database is locked",
    }
    for done, why in cases.items():
        assert embed_command.prune_text(done, "short") == f"vectors pruned: none, {done.outcome}\n"
        assert embed_command.prune_text(done, "detailed") == f"vector store not pruned, {why}\n"
    assert embed_command.prune_text(None, "short") == ""


def test_an_index_by_words_alone_in_place_holds_the_prune_back(data: Path) -> None:
    """Renamed in by a lexical build since: it names no vector, so none is deleted."""
    pruned(refreshed(indexing(data)))
    other = kept_whole(data)
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    evaluation = data / "eval" / "indexes"
    written = Written(skipped=0, documents=1)
    done = prune(data / "vectors.sqlite", data / "index.sqlite", evaluation, written)
    assert (done.outcome, done.file) == ("held back", str(data / "index.sqlite"))
    assert other in stored(data / "vectors.sqlite")


def test_the_vectors_counted_kept_are_those_left_in_the_store(data: Path) -> None:
    """The store deleted since an evaluation: the index's vectors come back, not its own.

    They come back once the index is rebuilt whole, which holds none of them.
    """
    pruned(refreshed(indexing(data)))
    evaluated(data, data / "vectors.sqlite", "windows")
    (data / "vectors.sqlite").unlink()
    update_index(indexing(data), MOMENT, rebuild=True)
    done = pruned(fill_and_prune(indexing(data)))
    assert (done.kept, done.kept_for_evaluation) == (len(stored(data / "vectors.sqlite")), 0)
    assert done.kept == len(read_by(data / "index.sqlite"))


def test_a_store_made_before_023_is_converted_and_said_so_once(data: Path) -> None:
    """The first prune converts it and says so; the next one has nothing to convert."""
    made_before_023(data / "vectors.sqlite")
    indexed = refreshed(indexing(data))
    done = pruned(indexed)
    assert (done.outcome, done.converted, done.shrinks, done.reclaimed) == (
        "pruned",
        True,
        True,
        True,
    )
    assert indexed is not None
    assert embed_command.text(indexed, "detailed").endswith(f"{embed_command.CONVERTED}\n")
    assert not pruned(refreshed(indexing(data))).converted


def test_a_store_not_yet_converted_is_said_so_with_the_reason(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Its conversion failed for want of space: the summary says why, and that it is retried."""
    pruned(refreshed(indexing(data)))
    swept = vector_store.Swept(
        deleted=1,
        kept=10,
        bytes_before=8192,
        bytes_after=8192,
        shrinks=False,
        unreclaimed="disk is full",
    )
    monkeypatch.setattr(vector_store.VectorStore, "prune", lambda *_: swept)
    indexed = refreshed(indexing(data))
    assert indexed is not None
    said_fully = embed_command.text(indexed, "detailed")
    assert said_fully.endswith(f"{embed_command.SHRINKS_NOT.format('disk is full')}\n")


def test_a_vacuum_that_fails_is_said_with_its_reason(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Pruned, the space not reclaimed: the outcome holds why, and so does the summary."""
    pruned(refreshed(indexing(data)))
    swept = vector_store.Swept(
        deleted=1,
        kept=10,
        bytes_before=8192,
        bytes_after=8192,
        shrinks=True,
        unreclaimed="disk is full",
    )
    monkeypatch.setattr(vector_store.VectorStore, "prune", lambda *_: swept)
    indexed = refreshed(indexing(data))
    done = pruned(indexed)
    assert (done.outcome, done.reclaimed, done.reason) == ("pruned", False, "disk is full")
    assert indexed is not None
    assert "; space not reclaimed: disk is full\n" in embed_command.text(indexed, "detailed")


def test_pieces_that_the_endpoint_refused_do_not_hold_the_prune_back(data: Path) -> None:
    """They have no vector to keep: the build is whole enough, and the prune runs."""
    path = write(data / "docs", page("196845", "Rollback"), BODY)
    refused = Scripted(refused={"Rollback\nRelease\nThe deploy of the seller service."})
    indexed = refreshed(replace(indexing(data), endpoint=lambda: scripted(refused)))
    assert indexed is not None
    assert indexed.refused == [path]
    assert pruned(indexed).outcome == "pruned"


def test_a_prune_gives_the_space_of_what_it_deleted_back(data: Path) -> None:
    """2,000 vectors the size of 1,024 float32 that no index reads: the store shrinks."""
    pruned(refreshed(indexing(data)))
    orphans = seeded(data / "vectors.sqlite", 2000)
    done = pruned(refreshed(indexing(data)))
    assert done.deleted == len(orphans)
    assert done.bytes_after < done.bytes_before
    assert (done.shrinks, done.reclaimed) == (True, True)


def evaluable(data: Path) -> None:
    """Write the documents that the evaluation's golden questions name, and index them."""
    fillers(data / "docs", FILLER_PAGES)
    canteen = "# Holiday canteen\n\nLeave for a **meal**.\n"
    write(data / "docs", page("4002", "Holiday canteen"), canteen)
    write(data / "docs", page("4003", "Words"), "revert release\n")
    write(data / "docs", issue("PROJ-7", "Kafka upgrade"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)


def test_an_evaluation_that_waits_too_long_for_a_prune_is_not_evaluated(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    """Its build gives up on the lock past the wait: eval says so and exits 1."""
    data = tmp_path / "data"
    evaluable(data)
    golden_file = tmp_path / "golden.yaml"
    golden_file.write_text(GOLDEN, encoding="utf-8")
    monkeypatch.setattr(vector_store, "WAIT_S", 0.3)
    config = tmp_path / "config.toml"
    with serving(Scripted()) as url, vector_store.exclusive(data / "vectors.sqlite") as held:
        assert held
        config.write_text(f'model = "tiny"\nembedding_url = {json.dumps(url)}\n', encoding="utf-8")
        arguments = ["eval", str(golden_file), "--yes", "--chunking", "sections"]
        status = main([*arguments, "--config", str(config), "--data-dir", str(data)])
    assert status == ExitStatus.FAILED
    assert ("error", "eval.not_evaluated") in said(capsys.readouterr().err)


@pytest.mark.skipif(sys.platform == "darwin", reason="APFS refuses names that are not UTF-8")
def test_a_file_named_in_bytes_that_are_not_utf_8_is_said_all_the_same(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Held back by it, the prune names it, those bytes as U+FFFD, and the JSON is written."""
    folder = data / "eval" / "indexes"
    folder.mkdir(parents=True)
    (folder / os.fsdecode(b"w\xff\xfe.sqlite")).write_bytes(b"not an index")
    status, result, _ = held_back(data, capsys)
    assert (status, result["outcome"]) == (0, "held back")
    assert result["file"] == f"{folder}/w\ufffd\ufffd.sqlite"


def test_what_a_prune_says_to_run_is_what_prunes_and_what_has_vectors() -> None:
    """Plans 031 and 035: ``embed`` prunes; ``index --rebuild`` rebuilds, then ``embed`` fills."""
    assert "the next embed prunes it" in DEFERRED
    assert "rebuild the index with index --rebuild, then embed," in UNREADABLE
    assert "index prunes" not in DEFERRED
