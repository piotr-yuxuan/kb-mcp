"""The search index: one SQLite file with FTS5, its schema, its build and its queries.

Only this module knows SQL. ``building`` writes a new index beside the old one and
renames it into place once complete; ``reading`` opens one read-only for one use, so
that a replaced file is read from the next use on.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from atlassian_offline_mcp.domain.mirror import FrontMatter
from atlassian_offline_mcp.domain.search import Entry, Filters, Passage, Score, Summary

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from atlassian_offline_mcp.domain.search import Section

SCHEMA = "1"
COLUMNS = ("title", "labels", "breadcrumb", "heading", "body")
# Weights of bm25 per full-text column, to score documents, then to find the best
# section of one, by its own words alone.
WEIGHTS = dict(zip(COLUMNS, (10.0, 3.0, 2.0, 5.0, 1.0), strict=True))
SECTION_WEIGHTS = dict(zip(COLUMNS, (0.0, 0.0, 0.0, 5.0, 1.0), strict=True))
# The best documents that one expression scores, after filters.
PER_EXPRESSION = 5000
SNIPPET_TOKENS = 24
CREATE = """
CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (
  rowid INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL, type TEXT NOT NULL, id TEXT NOT NULL, key TEXT,
  title TEXT NOT NULL, space TEXT, project TEXT, status TEXT NOT NULL, issue_type TEXT,
  labels TEXT NOT NULL, author TEXT, assignee TEXT, created TEXT NOT NULL,
  updated TEXT NOT NULL, version INTEGER, revision TEXT NOT NULL, url TEXT,
  breadcrumb TEXT NOT NULL, fetched_at TEXT NOT NULL,
  length INTEGER NOT NULL, first_section INTEGER NOT NULL, last_section INTEGER NOT NULL,
  UNIQUE (source, id)
);
CREATE INDEX documents_key ON documents (key);
CREATE TABLE labels (document INTEGER NOT NULL, label TEXT NOT NULL);
CREATE TABLE sections (
  rowid INTEGER PRIMARY KEY,
  document INTEGER NOT NULL, number INTEGER NOT NULL, start INTEGER NOT NULL,
  head TEXT NOT NULL, title TEXT NOT NULL, labels TEXT NOT NULL, breadcrumb TEXT NOT NULL,
  heading TEXT NOT NULL, body TEXT NOT NULL
);
CREATE INDEX sections_document ON sections (document, number);
CREATE VIRTUAL TABLE chunks USING fts5(
  title, labels, breadcrumb, heading, body,
  content = 'sections', content_rowid = 'rowid',
  tokenize = 'unicode61 remove_diacritics 2'
);
"""
# The documents that pass a search's filters, as a JSON list of rowids.
KEPT = """
SELECT json_group_array(d.rowid) FROM documents d
WHERE (:source IS NULL OR d.source = :source)
  AND (:space IS NULL OR d.space = :space)
  AND (:project IS NULL OR d.project = :project)
  AND (:status IS NULL OR d.status = :status)
  AND (:label IS NULL
       OR EXISTS (SELECT 1 FROM labels l WHERE l.document = d.rowid AND l.label = :label))
  AND (:after IS NULL OR d.updated >= :after)
  AND (:before IS NULL OR d.updated < :before)
"""
# bm25 cannot be grouped where it is computed, hence the materialised subquery.
SCORES = """
WITH matched AS MATERIALIZED (
  SELECT rowid AS section,
         -bm25(chunks, :title, :labels, :breadcrumb, :heading, :body) AS relevance
  FROM chunks WHERE chunks MATCH :expression
)
SELECT d.path, d.updated, max(m.relevance) AS relevance
FROM matched m JOIN sections s ON s.rowid = m.section JOIN documents d ON d.rowid = s.document
WHERE :kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept))
GROUP BY d.rowid ORDER BY relevance DESC, d.path LIMIT :limit
"""
PASSAGE = """
SELECT s.number, s.heading, snippet(chunks, 4, '', '', '…', :tokens) AS snippet
FROM chunks JOIN sections s ON s.rowid = chunks.rowid
WHERE chunks MATCH :match
  AND chunks.rowid BETWEEN (SELECT first_section FROM documents WHERE path = :path)
                       AND (SELECT last_section FROM documents WHERE path = :path)
ORDER BY bm25(chunks, :title, :labels, :breadcrumb, :heading, :body), s.number LIMIT 1
"""
ENTRIES = """
SELECT d.* FROM documents d
WHERE (d.path IN (SELECT value FROM json_each(:paths))
       OR d.key IN (SELECT value FROM json_each(:keys))
       OR (d.source = 'confluence' AND d.id IN (SELECT value FROM json_each(:ids))))
  AND (:kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept)))
"""
RECENT = """
SELECT d.* FROM documents d
WHERE :kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept))
ORDER BY d.updated DESC, d.path LIMIT :limit OFFSET :offset
"""
COUNT = """
SELECT count(*) FROM documents d
WHERE :kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept))
"""
LISTING = """
SELECT d.* FROM documents d
WHERE :kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept))
ORDER BY d.path
"""
BOUNDS = """
SELECT s.start, coalesce(lead(s.start) OVER (ORDER BY s.number), d.length) AS end
FROM sections s JOIN documents d ON d.rowid = s.document
WHERE d.path = :path
ORDER BY s.number
"""
TEXT = """
SELECT s.start, s.head || s.body AS text FROM sections s JOIN documents d ON d.rowid = s.document
WHERE d.path = :path AND s.start < :end AND s.start + length(s.head) + length(s.body) > :start
ORDER BY s.number
"""
# Each value that a filter can take, with how many documents have it, the most used first.
VALUES = {
    "source": "SELECT source, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC, 1",
    "space": "SELECT space, count(*) FROM documents WHERE space IS NOT NULL"
    " GROUP BY 1 ORDER BY 2 DESC, 1",
    "project": "SELECT project, count(*) FROM documents WHERE project IS NOT NULL"
    " GROUP BY 1 ORDER BY 2 DESC, 1",
    "status": "SELECT status, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC, 1",
    "label": "SELECT label, count(*) FROM labels GROUP BY 1 ORDER BY 2 DESC, 1",
    "type": "SELECT type, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC, 1",
}


class UnavailableIndexError(Exception):
    """No index to read, or one that this version cannot read; the message says why."""


class DuplicateDocumentError(ValueError):
    """A document whose source and id the index holds already."""


def moment(value: datetime) -> str:
    """Write a time as the index stores it: ISO 8601 in UTC, to the second, so it sorts."""
    return value.astimezone(UTC).isoformat(timespec="seconds")


class Writer:
    """Adds documents to an index being built."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Write through a connection whose schema is created."""
        self._connection = connection
        self._next_section = 1
        self.skipped = 0

    def add(self, path: str, front: FrontMatter, sections: list[Section]) -> None:
        """Add a document and its sections; refuse a source and id held already."""
        values = {name: getattr(front, name) for name in FrontMatter.__dataclass_fields__}
        values |= {
            "labels": json.dumps(front.labels, ensure_ascii=False),
            "breadcrumb": json.dumps(front.breadcrumb, ensure_ascii=False),
            "created": moment(front.created),
            "updated": moment(front.updated),
            "fetched_at": moment(front.fetched_at),
            "path": path,
            "length": sum(len(section.text) for section in sections),
            "first_section": self._next_section,
            "last_section": self._next_section + len(sections) - 1,
        }
        try:
            cursor = self._connection.execute(
                "INSERT INTO documents (path, source, type, id, key, title, space, project,"
                " status, issue_type, labels, author, assignee, created, updated, version,"
                " revision, url, breadcrumb, fetched_at, length, first_section, last_section)"
                " VALUES (:path, :source, :type, :id, :key, :title, :space, :project, :status,"
                " :issue_type, :labels, :author, :assignee, :created, :updated, :version,"
                " :revision, :url, :breadcrumb, :fetched_at, :length, :first_section,"
                " :last_section)",
                values,
            )
        except sqlite3.IntegrityError:
            message = f"{path}: another document has the same source and id"
            raise DuplicateDocumentError(message) from None
        document = cursor.lastrowid
        self._connection.executemany(
            "INSERT INTO labels (document, label) VALUES (?, ?)",
            [(document, label) for label in front.labels],
        )
        # The title, labels and breadcrumb go with the first section alone, so that FTS5,
        # which counts rows, counts a document's words once; the first section's heading,
        # when it is the title, is not counted again.
        about = (front.title, " ".join(front.labels), " / ".join(front.breadcrumb))
        rows = [
            (
                self._next_section + index,
                *(about if index == 0 else ("", "", "")),
                "" if index == 0 and section.heading == front.title else section.heading,
                section.body,
            )
            for index, section in enumerate(sections)
        ]
        self._connection.executemany(
            "INSERT INTO sections (rowid, document, number, start, head, title, labels,"
            " breadcrumb, heading, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (row[0], document, section.number, section.start, section.head, *row[1:])
                for row, section in zip(rows, sections, strict=True)
            ],
        )
        self._connection.executemany(
            "INSERT INTO chunks (rowid, title, labels, breadcrumb, heading, body)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._next_section += len(sections)

    def skip(self) -> None:
        """Count a file of the mirror that could not be indexed."""
        self.skipped += 1


@contextmanager
def building(path: Path, built_at: datetime) -> Iterator[Writer]:
    """Build a new index at ``path``, in one transaction, into a file beside it.

    The file is renamed into place once complete. On any failure the index already at
    ``path`` stays, and the new file is removed.
    """
    descriptor, name = tempfile.mkstemp(prefix=".index-", suffix=".sqlite", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        connection = sqlite3.connect(temporary, autocommit=False)
        try:
            connection.executescript(CREATE)
            writer = Writer(connection)
            yield writer
            connection.execute("INSERT INTO chunks (chunks) VALUES ('optimize')")
            connection.executemany(
                "INSERT INTO meta (name, value) VALUES (?, ?)",
                [
                    ("schema", SCHEMA),
                    ("built_at", moment(built_at)),
                    ("skipped", str(writer.skipped)),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def entry(row: sqlite3.Row) -> Entry:
    """Read a row of ``documents`` back into the front matter it was written from."""
    front = FrontMatter(
        source=row["source"],
        type=row["type"],
        id=row["id"],
        key=row["key"],
        title=row["title"],
        space=row["space"],
        project=row["project"],
        status=row["status"],
        issue_type=row["issue_type"],
        labels=tuple(json.loads(row["labels"])),
        author=row["author"],
        assignee=row["assignee"],
        created=datetime.fromisoformat(row["created"]),
        updated=datetime.fromisoformat(row["updated"]),
        version=row["version"],
        revision=row["revision"],
        url=row["url"],
        breadcrumb=tuple(json.loads(row["breadcrumb"])),
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )
    sections = row["last_section"] - row["first_section"] + 1
    return Entry(path=row["path"], front=front, length=row["length"], sections=sections)


class Reader:
    """Queries of one open index.

    A list is bounded by a limit, or else by what one space, project or filter holds.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Read through an open, read-only connection."""
        self._connection = connection
        self._kept: dict[Filters, str | None] = {}

    def kept(self, filters: Filters) -> str | None:
        """Name the documents that pass the filters, or None when nothing is filtered."""
        if filters == Filters():
            return None
        if filters not in self._kept:
            after, before = filters.updated_after, filters.updated_before
            parameters = {
                "source": filters.source,
                "space": filters.space,
                "project": filters.project,
                "status": filters.status,
                "label": filters.label,
                "after": None if after is None else moment(after),
                "before": None if before is None else moment(before),
            }
            self._kept[filters] = self._connection.execute(KEPT, parameters).fetchone()[0]
        return self._kept[filters]

    def scores(
        self, expression: str, filters: Filters, *, every: bool = False
    ) -> tuple[dict[str, Score], bool]:
        """Score each document by its best section for one expression.

        Only the PER_EXPRESSION best documents are kept, unless ``every`` is asked; the
        flag says whether every document that matches is there.
        """
        parameters = {
            **WEIGHTS,
            "expression": expression,
            "kept": self.kept(filters),
            "limit": -1 if every else PER_EXPRESSION,  # SQLite reads -1 as no limit
        }
        found = {
            row["path"]: Score(row["relevance"], datetime.fromisoformat(row["updated"]))
            for row in self._connection.execute(SCORES, parameters)
        }
        return found, every or len(found) < PER_EXPRESSION

    def passage(self, path: str, match: str) -> Passage | None:
        """Find the section of a document that best matches, with a snippet of its body.

        Sections are judged by their heading and body alone: a match on the title alone
        gives the first section.
        """
        parameters = {**SECTION_WEIGHTS, "match": match, "path": path, "tokens": SNIPPET_TOKENS}
        row = self._connection.execute(PASSAGE, parameters).fetchone()
        return None if row is None else Passage(row["number"], row["heading"], row["snippet"])

    def entries(
        self,
        *,
        paths: Iterable[str] = (),
        keys: Iterable[str] = (),
        ids: Iterable[str] = (),
        filters: Filters | None = None,
    ) -> list[Entry]:
        """Find the documents of these paths, issue keys and page ids, in no given order."""
        parameters = {
            "paths": json.dumps(list(paths)),
            "keys": json.dumps(list(keys)),
            "ids": json.dumps(list(ids)),
            "kept": self.kept(filters or Filters()),
        }
        return [entry(row) for row in self._connection.execute(ENTRIES, parameters)]

    def recent(self, filters: Filters, offset: int, limit: int) -> tuple[int, list[Entry]]:
        """Count the documents that pass the filters, and list a page of them, newest first."""
        kept = self.kept(filters)
        total = self._connection.execute(COUNT, {"kept": kept}).fetchone()[0]
        parameters = {"kept": kept, "offset": offset, "limit": limit}
        return total, [entry(row) for row in self._connection.execute(RECENT, parameters)]

    def listing(self, filters: Filters) -> list[Entry]:
        """List every document that passes the filters, such as those of one space."""
        rows = self._connection.execute(LISTING, {"kept": self.kept(filters)})
        return [entry(row) for row in rows]

    def bounds(self, path: str) -> list[tuple[int, int]]:
        """Give where each section of a document starts and ends, in order."""
        rows = self._connection.execute(BOUNDS, {"path": path})
        return [(row["start"], row["end"]) for row in rows]

    def text(self, path: str, start: int, end: int) -> str:
        """Give the characters of a document's body from ``start`` to ``end``."""
        parameters = {"path": path, "start": start, "end": end}
        rows = self._connection.execute(TEXT, parameters).fetchall()
        if not rows:
            return ""
        joined = "".join(row["text"] for row in rows)
        first = rows[0]["start"]
        return joined[start - first : end - first]

    def values(self, name: str) -> list[tuple[str, int]]:
        """Give each value that a filter or count can take, the most used first."""
        return [(row[0], row[1]) for row in self._connection.execute(VALUES[name])]

    def built_at(self) -> datetime:
        """Say when the index was built."""
        row = self._connection.execute("SELECT value FROM meta WHERE name = 'built_at'").fetchone()
        return datetime.fromisoformat(row[0])

    def summary(self) -> Summary:
        """Say what the index holds and when it was built."""
        meta = dict(self._connection.execute("SELECT name, value FROM meta").fetchall())
        newest = self._connection.execute("SELECT max(fetched_at) FROM documents").fetchone()[0]
        sections = self._connection.execute("SELECT count(*) FROM sections").fetchone()[0]
        return Summary(
            built_at=self.built_at(),
            skipped=int(meta["skipped"]),
            types=dict(self.values("type")),
            spaces=dict(self.values("space")),
            projects=dict(self.values("project")),
            sections=sections,
            newest_fetch=None if newest is None else datetime.fromisoformat(newest),
        )


@contextmanager
def reading(path: Path) -> Iterator[Reader]:
    """Open the index at ``path`` read-only, for one use; never write to it.

    Raise UnavailableIndexError when there is none, or when this version cannot read it.
    """
    hint = "build it with `atlassian-offline-mcp index`"
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        message = f"no index at {path}: {hint}"
        raise UnavailableIndexError(message) from None
    try:
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute("SELECT value FROM meta WHERE name = 'schema'").fetchone()
        except sqlite3.DatabaseError:
            row = None
        if row is None or row[0] != SCHEMA:
            message = f"{path} is not an index that this version reads: {hint}"
            raise UnavailableIndexError(message)
        yield Reader(connection)
    finally:
        connection.close()
