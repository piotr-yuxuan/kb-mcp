"""Pandoc's conversions so far, kept across prepares by their input, in one SQLite file.

The layout and the replacement of a damaged file: docs/reference/data-layout.md, section
"Pandoc's conversions". A key holds the whole of pandoc's input, which ``--sandbox``
limits to the HTML, so its row cannot go stale; a converter's name stands for one
function, as two functions under one name would share rows.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator
    from pathlib import Path

# How long a write to a store of SQLite waits for another run's, in seconds: about one
# batch's embedding, for the vector cache's.
WAIT_S = 60
CREATE = (
    "CREATE TABLE IF NOT EXISTS conversions (source TEXT NOT NULL, key TEXT NOT NULL,"
    " markdown TEXT NOT NULL, PRIMARY KEY (source, key))"
)
# The columns that a run reads: a schema whose text names others, which CREATE TABLE IF NOT
# EXISTS leaves as it is, fails here, at opening, and not at the run's first lookup.
COLUMNS = "SELECT source, key, markdown FROM conversions LIMIT 0"
# The columns of a file whose rows name no source, and how its rows become a row of each
# source given, as a JSON list.
FORMER = ["key", "markdown"]
ADOPT = (
    "INSERT INTO conversions (source, key, markdown)"
    " SELECT sources.value, former.key, former.markdown FROM former, json_each(?) AS sources"
)
# Every run may write: the write lock, taken first, finds a file that SQLite can read but
# may not write, such as one whose header names a later format; once in WAL mode, a
# connection finds it only at its first write.
SETUP = (
    f"BEGIN IMMEDIATE; {CREATE}; {COLUMNS}; COMMIT; "
    "PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL"
)
# SQLite's primary result codes for a damaged file, and for one that is no database.
DAMAGED = frozenset({sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB})
# The codes, exactly, that opening a file also gives when SQLite cannot read its format, or
# may not write the file, as when its header names a later format. Their extended codes say
# nothing of the file's content, such as SQLITE_READONLY_DIRECTORY for a folder not writable.
UNUSABLE = frozenset({sqlite3.SQLITE_ERROR, sqlite3.SQLITE_READONLY})
# An extended result code, such as SQLITE_CORRUPT_INDEX, holds its primary code in its low byte.
PRIMARY = 0xFF
# The files of a store in WAL mode, by what each adds to the store's name.
SUFFIXES = ("", "-wal", "-shm")


def damaged(error: sqlite3.DatabaseError) -> bool:
    """Say whether an error of SQLite's is that of a damaged file, not of its use or its disk.

    An error of the sqlite3 module's own, such as text that it cannot decode, has no code.
    """
    return (getattr(error, "sqlite_errorcode", 0) & PRIMARY) in DAMAGED


class Conversions:
    """One source's Markdown by key, in an open file, and what this run converted and reused.

    ``converted`` counts the conversions run, ``reused`` those the file gave.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        source: str,
        converter: Callable[[], str],
        convert: Callable[[str], str],
    ) -> None:
        """Use an open connection whose table exists, the rows of ``source``, and a converter.

        The converter is named by ``converter``.
        """
        self._connection = connection
        self._source = source
        self._converter = converter
        self._convert = convert
        self._name: str | None = None
        self._used: set[str] = set()
        self.converted = 0
        self.reused = 0

    def markdown(self, html: str) -> str:
        """Give the Markdown of ``html``: from the file, or converted, then kept and committed.

        The converter is named at the first conversion of a run, then that name is kept;
        when naming it raises, so does this conversion, and the next asks again. A
        conversion that raises keeps no row.
        """
        if self._name is None:
            self._name = self._converter()
        key = hashlib.sha256(f"{self._name}\0{html}".encode()).hexdigest()
        self._used.add(key)
        row = self._connection.execute(
            "SELECT markdown FROM conversions WHERE source = ? AND key = ?", (self._source, key)
        ).fetchone()
        if row is not None:
            self.reused += 1
            return row[0]
        markdown = self._convert(html)
        self._connection.execute(
            "INSERT OR REPLACE INTO conversions (source, key, markdown) VALUES (?, ?, ?)",
            (self._source, key, markdown),
        )
        self._connection.commit()
        self.converted += 1
        return markdown

    def drop_unused(self, *, remove: bool) -> int:
        """Delete every row of the source that this run did not use, unless ``remove`` is false.

        Return how many rows were deleted. Another source's rows stay.
        """
        if not remove:
            return 0
        deleted = self._connection.execute(
            "DELETE FROM conversions"
            " WHERE source = ? AND key NOT IN (SELECT value FROM json_each(?))",
            (self._source, json.dumps(list(self._used))),
        ).rowcount
        self._connection.commit()
        return deleted


def delete(path: Path) -> None:
    """Delete the store at ``path``, with its ``-wal`` and ``-shm``."""
    for suffix in SUFFIXES:
        path.with_name(f"{path.name}{suffix}").unlink(missing_ok=True)


@contextmanager
def opened(
    path: Path,
    converter: Callable[[], str],
    convert: Callable[[str], str],
    *,
    source: str,
    adopted: Collection[str],
) -> Iterator[Conversions]:
    """Open the file at ``path`` for the rows of ``source``; close it after use.

    A file whose rows name no source is first adopted, each row a row of each source of
    ``adopted``. A damaged or unusable file is replaced with an empty one; damage found
    during use deletes the file and re-raises.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=WAIT_S)
    try:
        try:
            # The write lock first, as SETUP takes it, then the former layout adopted under it.
            connection.execute("BEGIN IMMEDIATE")
            held = [row[1] for row in connection.execute("PRAGMA table_info(conversions)")]
            if held == FORMER:
                connection.execute("ALTER TABLE conversions RENAME TO former")
                connection.execute(CREATE)
                connection.execute(ADOPT, (json.dumps(list(adopted)),))
                taken = connection.execute("SELECT count(*) FROM former").fetchone()[0]
                connection.execute("DROP TABLE former")
                structlog.get_logger().info(
                    "prepare.cache_adopted", sources=list(adopted), rows=taken
                )
            connection.commit()
            connection.executescript(SETUP)
            checked = connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as error:
            if error.sqlite_errorcode not in UNUSABLE and not damaged(error):
                raise
            damage = error.sqlite_errorname
        except UnicodeDecodeError:
            # SQLite's report, an error or the check's, quotes a name from the file's schema
            # that is no longer UTF-8 text, which SQLite never writes from these statements.
            damage = "UnicodeDecodeError"
        else:
            damage = None if checked == [("ok",)] else "integrity_check"
        if damage is not None:
            connection.close()
            delete(path)
            structlog.get_logger().warning("prepare.cache_replaced", reason=damage)
            connection = sqlite3.connect(path, timeout=WAIT_S)
            connection.executescript(SETUP)
        try:
            yield Conversions(connection, source, converter, convert)
        except sqlite3.DatabaseError as error:
            if damaged(error):
                connection.close()
                delete(path)
            raise
    finally:
        connection.close()
