"""The search index: one SQLite file with FTS5, its schema, its build and its queries.

Only this module knows SQL. ``building`` writes a new index beside the old one and
renames it into place once complete; ``reading`` opens one read-only for one use, so
that a replaced file is read from the next use on. An index built with a model also
holds the vector of each piece of each section, with its key in the vector store, and
names the model.
"""

from __future__ import annotations

import errno
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from opentelemetry import trace

from atlassian_offline_mcp.kernel.chunking import CHUNKINGS
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter, Link, PersonRole
from atlassian_offline_mcp.search.adapters import vector_store
from atlassian_offline_mcp.search.domain import people
from atlassian_offline_mcp.search.domain.search import (
    Activity,
    Embedded,
    Entry,
    Filters,
    Passage,
    Persons,
    Pieces,
    Score,
    Summary,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from atlassian_offline_mcp.kernel.chunking import Chunking
    from atlassian_offline_mcp.search.domain.search import Section, Sort

TRACER = trace.get_tracer(__name__)
# What the file of a build begins with, beside its index, until it is renamed into place.
BUILDING = ".index-"
# Why a link among indexes is not followed: a cycle of them would not end.
LINK = "a link, which is not followed"
# 1 from plan 006; 3 from plan 011, with vectors and a build id; 4 from plan 041, with
# people in place of the author and the assignee; 5 from plan 042, with links; 6 from
# plan 043, with persons.
SCHEMA = "6"
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
  labels TEXT NOT NULL, people TEXT NOT NULL, links TEXT NOT NULL, created TEXT NOT NULL,
  updated TEXT NOT NULL, version INTEGER, revision TEXT NOT NULL, url TEXT,
  breadcrumb TEXT NOT NULL, fetched_at TEXT NOT NULL,
  length INTEGER NOT NULL, first_section INTEGER NOT NULL, last_section INTEGER NOT NULL,
  UNIQUE (source, id)
);
CREATE INDEX documents_key ON documents (key);
CREATE TABLE labels (document INTEGER NOT NULL, label TEXT NOT NULL);
CREATE TABLE people (
  document INTEGER NOT NULL, role TEXT NOT NULL, name TEXT NOT NULL, account TEXT, at TEXT,
  person TEXT
);
CREATE INDEX people_role_name ON people (role, name);
CREATE INDEX people_person_role ON people (person, role);
CREATE TABLE persons (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE person_names (
  person TEXT NOT NULL, name TEXT NOT NULL, key TEXT NOT NULL, joined TEXT NOT NULL
);
CREATE INDEX person_names_key ON person_names (key);
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
CREATE TABLE pieces (
  rowid INTEGER PRIMARY KEY,
  section INTEGER NOT NULL, start INTEGER NOT NULL, stop INTEGER NOT NULL,
  key TEXT NOT NULL, vector BLOB NOT NULL
);
"""
# The documents that pass a search's filters, as a JSON list of rowids. A person is
# given by their id, in any role or in the role of the filter.
KEPT = """
SELECT json_group_array(d.rowid) FROM documents d
WHERE (:source IS NULL OR d.source = :source)
  AND (:space IS NULL OR d.space = :space)
  AND (:project IS NULL OR d.project = :project)
  AND (:status IS NULL OR d.status = :status)
  AND (:label IS NULL
       OR EXISTS (SELECT 1 FROM labels l WHERE l.document = d.rowid AND l.label = :label))
  AND (:issue_type IS NULL OR d.issue_type = :issue_type)
  AND (:person IS NULL OR d.rowid IN (SELECT p.document FROM people p WHERE p.person = :person))
  AND (:author IS NULL OR d.rowid IN
       (SELECT p.document FROM people p WHERE p.role = 'author' AND p.person = :author))
  AND (:creator IS NULL OR d.rowid IN
       (SELECT p.document FROM people p WHERE p.role = 'creator' AND p.person = :creator))
  AND (:assignee IS NULL OR d.rowid IN
       (SELECT p.document FROM people p WHERE p.role = 'assignee' AND p.person = :assignee))
  AND (:participant IS NULL OR d.rowid IN
       (SELECT p.document FROM people p
        WHERE p.role = 'participant' AND p.person = :participant))
  AND (:updated_after IS NULL OR d.updated >= :updated_after)
  AND (:updated_before IS NULL OR d.updated < :updated_before)
  AND (:created_after IS NULL OR d.created >= :created_after)
  AND (:created_before IS NULL OR d.created < :created_before)
  AND ((:commenter IS NULL AND :commented_after IS NULL AND :commented_before IS NULL)
       OR d.rowid IN (
         SELECT p.document FROM people p WHERE p.role = 'commenter'
           AND (:commenter IS NULL OR p.person = :commenter)
           AND (:commented_after IS NULL OR p.at >= :commented_after)
           AND (:commented_before IS NULL OR p.at < :commented_before)))
"""
# bm25 cannot be grouped where it is computed, hence the materialised subquery.
SCORES = """
WITH matched AS MATERIALIZED (
  SELECT rowid AS section,
         -bm25(chunks, :title, :labels, :breadcrumb, :heading, :body) AS relevance
  FROM chunks WHERE chunks MATCH :expression
)
SELECT d.path, d.updated, d.created, max(m.relevance) AS relevance
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
       OR (d.source IN ('confluence', 'worklog') AND d.id IN (SELECT value FROM json_each(:ids))))
  AND (:kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept)))
"""
RECENT = """
SELECT d.* FROM documents d
WHERE :kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept))
ORDER BY CASE WHEN :by = 'created' THEN d.created ELSE d.updated END DESC, d.updated DESC, d.path
LIMIT :limit OFFSET :offset
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
# Every piece with its document, its section, and its span within the document's body.
PIECES = """
SELECT d.rowid AS document, d.path, d.updated, s.number,
       s.start + length(s.head) + p.start AS offset,
       s.start + length(s.head) + p.stop AS finish, p.vector
FROM pieces p JOIN sections s ON s.rowid = p.section JOIN documents d ON d.rowid = s.document
ORDER BY p.rowid
"""
TEXT = """
SELECT s.start, s.head || s.body AS text FROM sections s JOIN documents d ON d.rowid = s.document
WHERE d.path = :path AND s.start < :end AND s.start + length(s.head) + length(s.body) > :start
ORDER BY s.number
"""
# What ``reading`` checks before it reads an index.
META = "SELECT name, value FROM meta WHERE name IN ('schema', 'chunking')"
# What the join reads: each row of people, with when its document was updated; and each
# transcript's meetings, as its summary links name them, by rowid. A link to anything
# but a meeting names none, as a file edited by hand may hold. CROSS JOIN keeps SQLite's
# order, each transcript, its links, then the meeting by its source and id, so that the
# work grows with the links, not with the square of one source's documents.
PEOPLE_ROWS = """
SELECT p.rowid, p.document, p.role, p.name, p.account, d.updated
FROM people p JOIN documents d ON d.rowid = p.document
"""
SUMMARIES = """
SELECT t.rowid, m.rowid
FROM documents t CROSS JOIN json_each(t.links) l CROSS JOIN documents m
WHERE t.type = 'transcript' AND json_extract(l.value, '$.relation') = 'summary'
  AND m.source = t.source AND m.id = json_extract(l.value, '$.ref') AND m.type = 'meeting'
"""
# A person's documents per role, then per source with the newest update, the most first.
PERSON_ROLES = """
SELECT role, count(DISTINCT document) FROM people WHERE person = :person
GROUP BY 1 ORDER BY 2 DESC, 1
"""
PERSON_SOURCES = """
SELECT d.source, count(DISTINCT d.rowid), max(d.updated)
FROM people p JOIN documents d ON d.rowid = p.document WHERE p.person = :person
GROUP BY 1 ORDER BY 2 DESC, 1
"""
# A person's roles on each of some documents: the rows of each, a commenter's one per
# comment, and the time of the last comment.
PERSON_HELD = """
SELECT d.path, p.role, count(*), max(p.at)
FROM people p JOIN documents d ON d.rowid = p.document
WHERE p.person = :person AND d.path IN (SELECT value FROM json_each(:paths))
GROUP BY 1, 2 ORDER BY 1, 2
"""
# What status says of persons: how many, by name alone, in more than one source; and
# each name of two accounts or more, with the persons holding its key.
PERSON_COUNTS = """
SELECT count(*), count(*) FILTER (WHERE id NOT IN
  (SELECT person FROM person_names WHERE joined = 'account'))
FROM persons
"""
ACROSS = """
SELECT count(*) FROM (
  SELECT p.person FROM people p JOIN documents d ON d.rowid = p.document
  GROUP BY p.person HAVING count(DISTINCT d.source) > 1
)
"""
SHARED = """
SELECT min(n.name), (SELECT count(DISTINCT m.person) FROM person_names m WHERE m.key = n.key)
FROM person_names n WHERE n.joined = 'account'
GROUP BY n.key HAVING count(DISTINCT n.person) > 1
ORDER BY 2 DESC, 1
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
    "issue_type": "SELECT issue_type, count(*) FROM documents WHERE issue_type IS NOT NULL"
    " GROUP BY 1 ORDER BY 2 DESC, 1",
    # By the documents other than transcripts first, as participant's below.
    "person": "SELECT p.name, count(DISTINCT p.document) FROM people p"
    " JOIN documents d ON d.rowid = p.document"
    " GROUP BY 1 ORDER BY count(DISTINCT p.document) FILTER (WHERE d.type <> 'transcript') DESC,"
    " 2 DESC, 1",
    "author": "SELECT name, count(DISTINCT document) FROM people WHERE role = 'author'"
    " GROUP BY 1 ORDER BY 2 DESC, 1",
    "creator": "SELECT name, count(DISTINCT document) FROM people WHERE role = 'creator'"
    " GROUP BY 1 ORDER BY 2 DESC, 1",
    "assignee": "SELECT name, count(DISTINCT document) FROM people WHERE role = 'assignee'"
    " GROUP BY 1 ORDER BY 2 DESC, 1",
    "commenter": "SELECT name, count(DISTINCT document) FROM people WHERE role = 'commenter'"
    " GROUP BY 1 ORDER BY 2 DESC, 1",
    # By the meetings naming them first: a transcript's speakers You and Unverified, the
    # caption tool's, would otherwise lead.
    "participant": "SELECT p.name, count(DISTINCT p.document) FROM people p"
    " JOIN documents d ON d.rowid = p.document WHERE p.role = 'participant'"
    " GROUP BY 1 ORDER BY count(DISTINCT p.document) FILTER (WHERE d.type = 'meeting') DESC,"
    " 2 DESC, 1",
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

    def add(self, path: str, front: FrontMatter, sections: list[Section]) -> int:
        """Add a document and its sections; refuse a source and id held already.

        Return the rowid of its first section; the others follow it.
        """
        values = {name: getattr(front, name) for name in FrontMatter.__dataclass_fields__}
        values |= {
            "labels": json.dumps(front.labels, ensure_ascii=False),
            "people": json.dumps(
                [asdict(person) for person in front.people], ensure_ascii=False, default=moment
            ),
            "links": json.dumps([asdict(link) for link in front.links], ensure_ascii=False),
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
                " status, issue_type, labels, people, links, created, updated, version,"
                " revision, url, breadcrumb, fetched_at, length, first_section, last_section)"
                " VALUES (:path, :source, :type, :id, :key, :title, :space, :project, :status,"
                " :issue_type, :labels, :people, :links, :created, :updated, :version,"
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
        # One row per person and role, and a commenter's one per comment.
        self._connection.executemany(
            "INSERT INTO people (document, role, name, account, at) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    document,
                    person.role,
                    person.name,
                    person.account,
                    None if at is None else moment(at),
                )
                for person in front.people
                for at in person.at or (None,)
            ],
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
        first = self._next_section
        self._next_section += len(sections)
        return first

    def add_pieces(self, pieces: Iterable[tuple[int, int, int, str, bytes]]) -> None:
        """Add pieces: each its section's rowid, its span in the section's body, its vector.

        Each vector comes with its key in the vector store, which only pruning reads.
        """
        self._connection.executemany(
            "INSERT INTO pieces (section, start, stop, key, vector) VALUES (?, ?, ?, ?, ?)",
            pieces,
        )

    def skip(self) -> None:
        """Count a file of the mirror that could not be indexed."""
        self.skipped += 1

    @TRACER.start_as_current_span("index.join")
    def join(self, aliases: Mapping[str, str]) -> people.Outcome:
        """Join the people of the documents added into persons, as ``people.joined`` rules.

        Once the last document is added: every row of ``people`` is given its person, and
        ``persons`` and ``person_names`` hold each person and each of its spellings, with
        how it joined. A transcript's meetings are the meetings that its ``summary`` links
        name: no other document, so that each is joined before the transcript.
        ``aliases`` gives each alias's name and target, as the alias file's reader checks
        them. Give back how many persons there are, and what the join left apart: the
        names that could be several persons, and the aliases that changed nothing; each
        row's person stays here. The span ``index.join`` holds it.
        """
        rows = {
            rowid: people.Row(document, role, name, account, datetime.fromisoformat(updated))
            for rowid, document, role, name, account, updated in self._connection.execute(
                PEOPLE_ROWS
            )
        }
        meetings: dict[int, set[int]] = {}
        for transcript, meeting in self._connection.execute(SUMMARIES):
            meetings.setdefault(transcript, set()).add(meeting)
        found = people.joined(rows.values(), meetings, aliases)
        self._connection.executemany(
            "UPDATE people SET person = ? WHERE rowid = ?",
            [(found.of[row], rowid) for rowid, row in rows.items()],
        )
        self._connection.executemany(
            "INSERT INTO persons (id, name) VALUES (?, ?)",
            [(person.id, person.name) for person in found.persons],
        )
        self._connection.executemany(
            "INSERT INTO person_names (person, name, key, joined) VALUES (?, ?, ?, ?)",
            [
                (person.id, spelling.name, spelling.key, spelling.how)
                for person in found.persons
                for spelling in person.names
            ],
        )
        return people.Outcome(len(found.persons), found.ambiguous, found.unused)


def indexes_in(folder: Path) -> list[Path]:
    """List the indexes under a folder, at any depth, in order; none if it does not exist.

    A prune must see each, or it deletes the vectors that it reads: a folder that cannot
    be reached or listed, an entry below the folder that is a link, which is not
    followed, and a parent that is a dangling link, as to a disk away, raise OSError
    naming it; the folder itself and its parent may be links. Only regular files are
    indexes, and the file of a build is none: ``building`` makes it empty, renames it
    into place once complete, and a build killed before its end leaves it behind.
    """
    try:
        folder.lstat()
    except FileNotFoundError:
        if folder.parent.is_symlink() and not folder.parent.exists():
            raise
        return []
    errors: list[OSError] = []
    found: list[Path] = []
    for root, _folders, names in folder.walk(on_error=errors.append):
        paths = [root / name for name in names]
        errors += [OSError(errno.ELOOP, LINK, str(path)) for path in paths if path.is_symlink()]
        found += [path for path in paths if path.suffix == ".sqlite" and path.is_file()]
    if errors:
        raise errors[0]
    return sorted(path for path in found if not path.name.startswith(BUILDING))


@contextmanager
def building(path: Path, built_at: datetime, embedded: Embedded | None = None) -> Iterator[Writer]:
    """Build a new index at ``path``, in one transaction, into a file beside it.

    ``embedded`` names the model of its pieces' vectors, if any. The file is renamed
    into place once complete. On any failure the index already at ``path`` stays, and
    the new file is removed.
    """
    descriptor, name = tempfile.mkstemp(prefix=BUILDING, suffix=".sqlite", dir=path.parent)
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
                    ("build", uuid.uuid4().hex),
                    ("model", embedded.model if embedded else ""),
                    ("fingerprint", embedded.fingerprint if embedded else ""),
                    ("dimensions", str(embedded.dimensions) if embedded else ""),
                    ("chunking", embedded.chunking if embedded else ""),
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
        people=tuple(
            PersonRole(
                role=person["role"],
                name=person["name"],
                account=person["account"],
                at=tuple(datetime.fromisoformat(at) for at in person["at"]),
            )
            for person in json.loads(row["people"])
        ),
        links=tuple(
            Link(relation=link["relation"], ref=link["ref"]) for link in json.loads(row["links"])
        ),
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
            parameters = {
                name: moment(value) if isinstance(value, datetime) else value
                for name, value in asdict(filters).items()
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
            row["path"]: Score(
                row["relevance"],
                datetime.fromisoformat(row["updated"]),
                datetime.fromisoformat(row["created"]),
            )
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
        """Find the documents of these paths, issue keys, and page or work-log ids, in no order.

        An issue's id is never looked up, since a page may have the same.
        """
        parameters = {
            "paths": json.dumps(list(paths)),
            "keys": json.dumps(list(keys)),
            "ids": json.dumps(list(ids)),
            "kept": self.kept(filters or Filters()),
        }
        return [entry(row) for row in self._connection.execute(ENTRIES, parameters)]

    def recent(
        self, filters: Filters, by: Sort, offset: int, limit: int
    ) -> tuple[int, list[Entry]]:
        """Count the documents that pass the filters, and list a page of them, newest first.

        Newest by created date, or else by update; ties go to the newest update, then the
        path.
        """
        kept = self.kept(filters)
        total = self._connection.execute(COUNT, {"kept": kept}).fetchone()[0]
        parameters = {"kept": kept, "by": by, "offset": offset, "limit": limit}
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

    def persons(self, key: str, joined: str | None = None) -> list[str]:
        """Give the ids of the persons with a name of this key, as ``name_key`` gives it, sorted.

        ``joined``, if given, keeps the names that joined so, such as ``people.ACCOUNT``.
        """
        rows = self._connection.execute(
            "SELECT DISTINCT person FROM person_names"
            " WHERE key = :key AND (:joined IS NULL OR joined = :joined) ORDER BY person",
            {"key": key, "joined": joined},
        )
        return [row[0] for row in rows]

    def person(self, person: str) -> Activity | None:
        """Give the person of this id, with their documents by role and by source; else None.

        Their spellings in the order that ``people.Person`` has them.
        """
        found = self._connection.execute("SELECT name FROM persons WHERE id = ?", (person,))
        name = found.fetchone()
        if name is None:
            return None
        rows = self._connection.execute(
            "SELECT name, key, joined FROM person_names WHERE person = ?"
            " ORDER BY name, key, joined",
            (person,),
        )
        spellings = tuple(people.Spelling(*row) for row in rows)
        roles = self._connection.execute(PERSON_ROLES, {"person": person})
        sources = self._connection.execute(PERSON_SOURCES, {"person": person}).fetchall()
        return Activity(
            person=people.Person(person, name[0], spellings),
            roles={row[0]: row[1] for row in roles},
            sources={row[0]: row[1] for row in sources},
            last=max(datetime.fromisoformat(row[2]) for row in sources),
        )

    def roles(
        self, person: str, paths: Iterable[str]
    ) -> dict[str, list[tuple[str, int, datetime | None]]]:
        """Give a person's roles on each of these documents where they hold one, by path.

        Each role with the count of its rows, a commenter's being their comments, and the
        time of the last comment, None for any other role.
        """
        parameters = {"person": person, "paths": json.dumps(list(paths))}
        held: dict[str, list[tuple[str, int, datetime | None]]] = {}
        for path, role, count, at in self._connection.execute(PERSON_HELD, parameters):
            last = None if at is None else datetime.fromisoformat(at)
            held.setdefault(path, []).append((role, count, last))
        return held

    def built_at(self) -> datetime:
        """Say when the index was built."""
        row = self._connection.execute("SELECT value FROM meta WHERE name = 'built_at'").fetchone()
        return datetime.fromisoformat(row[0])

    def build(self) -> str:
        """Name this build of the index, unlike any other, even one of the same second."""
        row = self._connection.execute("SELECT value FROM meta WHERE name = 'build'").fetchone()
        return row[0]

    def embedded(self) -> Embedded | None:
        """Name the model of the index's vectors, or None when it was built without one."""
        meta = dict(self._connection.execute("SELECT name, value FROM meta").fetchall())
        if not meta["model"]:
            return None
        # Indexes of 011 and 018 have no chunking: their pieces were cut by sections.
        chunking = cast("Chunking", meta.get("chunking", "sections"))
        return Embedded(meta["model"], meta["fingerprint"], int(meta["dimensions"]), chunking)

    def keys(self) -> set[str]:
        """Give the vector store's keys of the pieces' vectors: what the index reads of it.

        An index built by words alone names no vector, and one of this schema built before
        pieces recorded their keys reads as any other: neither can say which vectors a
        prune must keep, so raise UnavailableIndexError.
        """
        columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(pieces)")}
        model = self._connection.execute("SELECT value FROM meta WHERE name = 'model'").fetchone()
        if not model or not model[0] or "key" not in columns:
            message = "built by words alone, or before pieces recorded their keys"
            raise UnavailableIndexError(message)
        return {row[0] for row in self._connection.execute("SELECT DISTINCT key FROM pieces")}

    def pieces(self) -> Pieces:
        """Read every piece's vector, with where the piece is: what meaning searches."""
        rows = self._connection.execute(PIECES).fetchall()
        dimensions = len(rows[0]["vector"]) // vector_store.LAYOUT.itemsize if rows else 0
        matrix = np.frombuffer(b"".join(row["vector"] for row in rows), dtype=vector_store.LAYOUT)
        return Pieces(
            documents=tuple(row["document"] for row in rows),
            paths={row["document"]: row["path"] for row in rows},
            updated={row["path"]: datetime.fromisoformat(row["updated"]) for row in rows},
            sections=tuple(row["number"] for row in rows),
            offsets=tuple(row["offset"] for row in rows),
            ends=tuple(row["finish"] for row in rows),
            matrix=matrix.astype(np.float32).reshape(len(rows), dimensions),
        )

    def heading(self, path: str, number: int) -> str:
        """Give the heading of a document's section."""
        row = self._connection.execute(
            "SELECT s.heading FROM sections s JOIN documents d ON d.rowid = s.document"
            " WHERE d.path = :path AND s.number = :number",
            {"path": path, "number": number},
        ).fetchone()
        return "" if row is None else row[0]

    def summary(self) -> Summary:
        """Say what the index holds and when it was built."""
        meta = dict(self._connection.execute("SELECT name, value FROM meta").fetchall())
        newest = self._connection.execute("SELECT max(fetched_at) FROM documents").fetchone()[0]
        sections = self._connection.execute("SELECT count(*) FROM sections").fetchone()[0]
        pieces = self._connection.execute("SELECT count(*) FROM pieces").fetchone()[0]
        persons, alone = self._connection.execute(PERSON_COUNTS).fetchone()
        across = self._connection.execute(ACROSS).fetchone()[0]
        shared = tuple((row[0], row[1]) for row in self._connection.execute(SHARED))
        embedded = self.embedded()
        return Summary(
            built_at=self.built_at(),
            skipped=int(meta["skipped"]),
            types=dict(self.values("type")),
            spaces=dict(self.values("space")),
            projects=dict(self.values("project")),
            sections=sections,
            newest_fetch=None if newest is None else datetime.fromisoformat(newest),
            people=Persons(persons, across, alone, shared),
            model=meta["model"] or None,
            pieces=pieces,
            chunking=embedded.chunking if embedded else None,
        )


@contextmanager
def reading(path: Path) -> Iterator[Reader]:
    """Open the index at ``path`` read-only, for one use; never write to it.

    Raise UnavailableIndexError when there is none, or when this version cannot read it.
    Another schema names ``sync``, or ``mirror`` then ``index`` where no source is
    configured, not ``index`` alone: a new schema can come with a new format of the
    mirror's files, which ``index`` would skip, and those write them first.
    """
    unread = f"{path} is not an index that this version reads: rebuild it with"
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        message = f"no index at {path}: build it with `atlassian-offline-mcp index`"
        raise UnavailableIndexError(message) from None
    try:
        connection.row_factory = sqlite3.Row
        try:
            meta = dict(connection.execute(META).fetchall())
        except sqlite3.DatabaseError:
            meta = {}
        if meta.get("schema") != SCHEMA:
            message = (
                f"{unread} `atlassian-offline-mcp sync`, or, where no source is configured,"
                " `atlassian-offline-mcp mirror` then `atlassian-offline-mcp index`, which"
                " write the mirror again first"
            )
            raise UnavailableIndexError(message)
        # A chunking that this version lacks would be cut as no table says.
        if meta.get("chunking", "") not in {"", *CHUNKINGS}:
            message = f"{unread} `atlassian-offline-mcp index`"
            raise UnavailableIndexError(message)
        yield Reader(connection)
    finally:
        connection.close()
