"""Pandoc's conversions so far, kept across mirrors by their input, in one SQLite file.

A conversion is keyed by the SHA-256 of the UTF-8 bytes of its converter's name, a NUL,
then the HTML converted. With ``--sandbox``, pandoc reads nothing but that HTML, and the
converter's name holds pandoc's version line and arguments: so a key holds the whole of
pandoc's input, and its row cannot go stale. A name stands for one function: two
functions under one name would share rows.
Each conversion is committed at once, so that an interrupted run keeps all it made; in
WAL mode with ``synchronous = NORMAL``, a power cut may lose the last few, never the
file. Deleting the file costs one conversion of everything, and downloads nothing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

# How long a write waits for another run's, in seconds, as the vector store's do.
WAIT_S = 60
CREATE = "CREATE TABLE IF NOT EXISTS conversions (key TEXT PRIMARY KEY, markdown TEXT NOT NULL)"
# SQLite's result codes for a damaged file, and for one that is no database.
DAMAGED = frozenset({sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB})
# The files of a store in WAL mode, by what each adds to the store's name.
SUFFIXES = ("", "-wal", "-shm")


class Conversions:
    """Pandoc's Markdown by key, in an open file, and what this run converted and reused.

    ``converted`` counts the conversions run, ``reused`` those the file gave.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        converter: Callable[[], str],
        convert: Callable[[str], str],
    ) -> None:
        """Use an open connection whose table exists, and a converter, named by ``converter``."""
        self._connection = connection
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
            "SELECT markdown FROM conversions WHERE key = ?", (key,)
        ).fetchone()
        if row is not None:
            self.reused += 1
            return row[0]
        markdown = self._convert(html)
        self._connection.execute(
            "INSERT OR REPLACE INTO conversions (key, markdown) VALUES (?, ?)", (key, markdown)
        )
        self._connection.commit()
        self.converted += 1
        return markdown

    def prune(self, *, remove: bool) -> int:
        """Delete every row that this run did not use, unless ``remove`` is false.

        Return how many rows were deleted.
        """
        if not remove:
            return 0
        deleted = self._connection.execute(
            "DELETE FROM conversions WHERE key NOT IN (SELECT value FROM json_each(?))",
            (json.dumps(list(self._used)),),
        ).rowcount
        self._connection.commit()
        return deleted


@contextmanager
def opened(
    path: Path, converter: Callable[[], str], convert: Callable[[str], str]
) -> Iterator[Conversions]:
    """Open the file at ``path``, creating it, or replacing a damaged one; close it after use.

    ``PRAGMA quick_check`` judges the file. When it reports damage, or SQLite finds the
    file damaged or no database at all, the file and its ``-wal`` and ``-shm`` are
    deleted, ``mirror.cache_replaced`` says why, by SQLite's error name or
    ``quick_check``, and an empty file takes its place. A file locked past the wait is
    not damaged: it raises, as any write that waits too long does, and stays. Damage
    found after the check raises too.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=WAIT_S)
    try:
        try:
            checked = connection.execute("PRAGMA quick_check").fetchall()
        except sqlite3.DatabaseError as error:
            if error.sqlite_errorcode not in DAMAGED:
                raise
            damage = error.sqlite_errorname
        else:
            damage = None if checked == [("ok",)] else "quick_check"
        if damage is not None:
            connection.close()
            for suffix in SUFFIXES:
                path.with_name(f"{path.name}{suffix}").unlink(missing_ok=True)
            structlog.get_logger().warning("mirror.cache_replaced", reason=damage)
            connection = sqlite3.connect(path, timeout=WAIT_S)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(CREATE)
        connection.commit()
        yield Conversions(connection, converter, convert)
    finally:
        connection.close()
