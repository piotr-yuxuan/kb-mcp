"""The search index: one SQLite file with FTS5, its schema, its build and its queries.

Only this module knows SQL. ``building`` writes a new index beside the old one and
renames it into place once complete; ``reading`` opens one read-only for one use, so
that a replaced file is read from the next use on. An index built with a model also
holds the vector of each chunk of each section, with its key in the vector cache, and
names the model. ``SqliteIndex`` is one file as ``search.domain.indexes`` declares an
index: an update builds the new file beside it too, copying what it keeps of the old,
and a fill copies it whole beside it to add and remove chunks, each under a lock beside
it that only they take.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

import numpy as np
from opentelemetry import trace

from kb_mcp.kernel.chunking import CHUNKINGS
from kb_mcp.mirror.adapters.conversions import damaged
from kb_mcp.mirror.domain.mirror import FrontMatter, Link, Mention
from kb_mcp.search.adapters import vector_cache
from kb_mcp.search.domain import people
from kb_mcp.search.domain.chunking import CHUNKERS
from kb_mcp.search.domain.indexes import (
    DamagedIndexError,
    Held,
    IndexedBody,
    Skipped,
    UnavailableIndexError,
    Updated,
)
from kb_mcp.search.domain.search import (
    WORDS,
    Activity,
    Chunk,
    ChunkVectors,
    Embedded,
    Filters,
    IndexedDocument,
    IndexStatus,
    Passage,
    PersonCounts,
    Score,
    sections,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Mapping

    from numpy.typing import NDArray

    from kb_mcp.kernel.chunking import Chunking
    from kb_mcp.search.domain.indexes import Change, Put
    from kb_mcp.search.domain.search import Matched, Sort

TRACER = trace.get_tracer(__name__)
# What the file of a build begins with, beside its index, until it is renamed into place.
BUILDING = ".index-"
# Why a link among indexes is not followed: a cycle of them would not end.
LINK = "a link, which is not followed"
# Why a file is skipped whose document's source and id an earlier file by path holds.
DUPLICATE = "another document has the same source and id"
# Who holds the lock of an index that an update waits for.
WRITER = "another kb-mcp index or kb-mcp embed"
# 1 from plan 006; 3 from plan 011, with vectors and a build id; 4 from plan 041, with
# people in place of the author and the assignee; 5 from plan 042, with links; 6 from
# plan 043, with persons; 7 from plan 054, with the tables chunks, by body offsets, and
# section_words; 8 from plan 058, with identities.
SCHEMA = "8"
# The former schemas whose mirror's files this version reads as they are: rebuilding the
# index is enough, with no prepare first.
SAME_MIRROR = frozenset({"6"})
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
  path TEXT NOT NULL UNIQUE, digest TEXT NOT NULL,
  source TEXT NOT NULL, type TEXT NOT NULL, id TEXT NOT NULL, key TEXT,
  title TEXT NOT NULL, space TEXT, project TEXT, status TEXT NOT NULL, issue_type TEXT,
  labels TEXT NOT NULL, people TEXT NOT NULL, links TEXT NOT NULL, created TEXT NOT NULL,
  updated TEXT NOT NULL, version INTEGER, revision TEXT NOT NULL, url TEXT,
  breadcrumb TEXT NOT NULL, fetched_at TEXT NOT NULL,
  length INTEGER NOT NULL, first_section INTEGER NOT NULL, last_section INTEGER NOT NULL,
  UNIQUE (source, id)
);
CREATE INDEX documents_key ON documents (key);
CREATE TABLE skipped (path TEXT PRIMARY KEY, digest TEXT, reason TEXT NOT NULL);
CREATE TABLE labels (document INTEGER NOT NULL, label TEXT NOT NULL);
CREATE TABLE people (
  document INTEGER NOT NULL, role TEXT NOT NULL, name TEXT NOT NULL, identity TEXT, at TEXT,
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
CREATE VIRTUAL TABLE section_words USING fts5(
  title, labels, breadcrumb, heading, body,
  content = 'sections', content_rowid = 'rowid',
  tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE chunks (
  rowid INTEGER PRIMARY KEY,
  section INTEGER NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL,
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
         -bm25(section_words, :title, :labels, :breadcrumb, :heading, :body) AS relevance
  FROM section_words WHERE section_words MATCH :expression
)
SELECT d.path, d.updated, d.created, max(m.relevance) AS relevance
FROM matched m JOIN sections s ON s.rowid = m.section JOIN documents d ON d.rowid = s.document
WHERE :kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept))
GROUP BY d.rowid ORDER BY relevance DESC, d.path LIMIT :limit
"""
PASSAGE = """
SELECT s.number, s.heading, snippet(section_words, 4, '', '', '…', :tokens) AS snippet
FROM section_words JOIN sections s ON s.rowid = section_words.rowid
WHERE section_words MATCH :match
  AND section_words.rowid BETWEEN (SELECT first_section FROM documents WHERE path = :path)
                       AND (SELECT last_section FROM documents WHERE path = :path)
ORDER BY bm25(section_words, :title, :labels, :breadcrumb, :heading, :body), s.number LIMIT 1
"""
ENTRIES = """
SELECT d.* FROM documents d
WHERE (d.path IN (SELECT value FROM json_each(:paths))
       OR d.key IN (SELECT value FROM json_each(:keys))
       OR (d.source IN ('confluence', 'worklog') AND d.id IN (SELECT value FROM json_each(:ids))))
  AND (:kept IS NULL OR d.rowid IN (SELECT value FROM json_each(:kept)))
ORDER BY d.path
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
# Every chunk, where it is, with the columns asked: by what no rowid changes, so that an
# updated index and a whole build give one matrix. What a search reads, and what
# ``embed`` compares.
CHUNKS = """
SELECT d.path, s.number, p.start, p."end", {columns}
FROM chunks p JOIN sections s ON s.rowid = p.section JOIN documents d ON d.rowid = s.document
ORDER BY d.path, s.number, p.start
"""
# Each section's heading line and body, which give a document's body back in order.
BODIES = """
SELECT d.path, s.head || s.body FROM sections s JOIN documents d ON d.rowid = s.document
ORDER BY d.path, s.number
"""
# What a fill writes into its copy: a chunk, its section named by path and number, which
# the copy resolves to a rowid; or the removal of one.
FILL_ADD = """
INSERT INTO chunks (section, start, "end", key, vector)
SELECT s.rowid, :start, :end, :vector_key, :vector
FROM sections s JOIN documents d ON d.rowid = s.document
WHERE d.path = :path AND s.number = :number
"""
FILL_REMOVE = """
DELETE FROM chunks WHERE rowid IN (
  SELECT p.rowid FROM chunks p JOIN sections s ON s.rowid = p.section
  JOIN documents d ON d.rowid = s.document
  WHERE d.path = :path AND s.number = :number AND p.start = :start AND p."end" = :end
    AND p.key = :vector_key
)
"""
TEXT = """
SELECT s.start, s.head || s.body AS text FROM sections s JOIN documents d ON d.rowid = s.document
WHERE d.path = :path AND s.start < :end AND s.start + length(s.head) + length(s.body) > :start
ORDER BY s.number
"""
# What ``reading`` checks before it reads an index.
META = "SELECT name, value FROM meta WHERE name IN ('schema', 'chunking')"
# The documents that hold a section but no chunk: those that may await their vectors.
UNFILLED = """
SELECT d.* FROM documents d
WHERE d.last_section >= d.first_section
  AND d.rowid NOT IN (SELECT s.document FROM chunks p JOIN sections s ON s.rowid = p.section)
"""
# A document's body, as its sections' heading lines and bodies give it back in order.
BODY = "SELECT head || body FROM sections WHERE document = ? ORDER BY number"
# The documents of the index in place, attached as ``old``, that an update would copy
# and whose source and id one of :keys, a JSON list of pairs, holds.
HOLDERS = """
SELECT path, source, id FROM old.documents
WHERE path NOT IN (SELECT value FROM json_each(:left))
  AND (source, id) IN (SELECT value ->> 0, value ->> 1 FROM json_each(:keys))
"""
# What an update copies from the index in place, attached as ``old``, which has this
# schema and ``WORDS``: every document but those of :left, with its labels, people,
# sections and chunks, their rowids kept, so that each chunk still names its section.
# Each row's person is joined again.
COPY = (
    """
    INSERT INTO main.documents SELECT * FROM old.documents
    WHERE path NOT IN (SELECT value FROM json_each(:left))
    """,
    """
    INSERT INTO main.labels SELECT * FROM old.labels
    WHERE document IN (SELECT rowid FROM main.documents)
    """,
    """
    INSERT INTO main.people (document, role, name, identity, at)
    SELECT document, role, name, identity, at FROM old.people
    WHERE document IN (SELECT rowid FROM main.documents)
    """,
    """
    INSERT INTO main.sections SELECT * FROM old.sections
    WHERE document IN (SELECT rowid FROM main.documents)
    """,
    """
    INSERT INTO main.chunks SELECT p.* FROM old.chunks p
    JOIN main.sections s ON s.rowid = p.section
    """,
)
# What the join reads: each row of people, with when its document was updated; and the
# documents that each document's summary links name in its source, by rowid. A document
# that links by summary to another of its source itself is named by none, as a file
# edited by hand may hold: rule 4 needs the participants of each summary joined before
# those that it summarises.
# CROSS JOIN keeps SQLite's order, each document, its links, then the one linked by its
# source and id, and so for the links of that one, so that the work grows with the
# links, not with the square of one source's documents.
PEOPLE_ROWS = """
SELECT p.rowid, p.document, p.role, p.name, p.identity, d.updated
FROM people p JOIN documents d ON d.rowid = p.document
"""
# Each document's place by its path's text, which numbers it for the join: ties go to the
# first row, and by rowid to whichever file was not edited last.
BY_PATH = "SELECT rowid, row_number() OVER (ORDER BY path) FROM documents"
SUMMARY_LINKS = """
SELECT t.rowid, m.rowid
FROM documents t CROSS JOIN json_each(t.links) l CROSS JOIN documents m
WHERE json_extract(l.value, '$.relation') = 'summary'
  AND m.source = t.source AND m.id = json_extract(l.value, '$.ref')
  AND NOT EXISTS (
    SELECT 1 FROM json_each(m.links) n CROSS JOIN documents o
    WHERE json_extract(n.value, '$.relation') = 'summary'
      AND o.source = m.source AND o.id = json_extract(n.value, '$.ref')
  )
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
# What status says of persons: how many, by name alone, of no identity, in more than one
# source; and each name that the identities of two persons or more write, however they
# joined, with the persons holding its key.
PERSON_COUNTS = """
SELECT count(*), count(*) FILTER (WHERE id NOT IN
  (SELECT person FROM people WHERE identity IS NOT NULL))
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
FROM person_names n
WHERE EXISTS (
  SELECT 1 FROM people p
  WHERE p.person = n.person AND p.name = n.name AND p.identity IS NOT NULL
)
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


class DuplicateDocumentError(ValueError):
    """A document whose source and id the index holds already."""


def moment(value: datetime) -> str:
    """Write a time as the index stores it: ISO 8601 in UTC, to the second, so it sorts."""
    return value.astimezone(UTC).isoformat(timespec="seconds")


def awaiting(connection: sqlite3.Connection, chunking: Chunking) -> int:
    """Count the documents that hold no chunk and want one, as ``chunking`` cuts them.

    One whose body gives no text to embed by that chunking, such as a page of a title
    alone cut by sections, or of white space alone, wants none, and never awaits.
    """
    rows = connection.cursor()
    rows.row_factory = sqlite3.Row
    wanting = 0
    for row in rows.execute(UNFILLED).fetchall():
        body = "".join(text for (text,) in connection.execute(BODY, (row["rowid"],)))
        wanting += bool(CHUNKERS[chunking].cut(indexed_document(row).front, sections(body)))
    return wanting


class Writer:
    """Adds documents to an index being built."""

    def __init__(self, connection: sqlite3.Connection, embedded: Embedded | None = None) -> None:
        """Write through a connection whose schema is created; ``embedded`` names its model."""
        self._connection = connection
        self._next_section = 1
        self.embedded = embedded
        self.aliases = people.aliases_digest({})  # what the join read: no alias, yet
        self.build = uuid.uuid4().hex  # unlike any other build

    def add(self, put: Put) -> int:
        """Add a document and its sections; refuse a source and id held already.

        Return the rowid of its first section; the others follow it.
        """
        path, front, sections = put.path, put.front, put.sections
        values = {name: getattr(front, name) for name in FrontMatter.model_fields}
        values |= {
            "labels": json.dumps(front.labels, ensure_ascii=False),
            "people": json.dumps(
                [person.model_dump() for person in front.people], ensure_ascii=False, default=moment
            ),
            "links": json.dumps([link.model_dump() for link in front.links], ensure_ascii=False),
            "breadcrumb": json.dumps(front.breadcrumb, ensure_ascii=False),
            "created": moment(front.created),
            "updated": moment(front.updated),
            "fetched_at": moment(front.fetched_at),
            "path": path,
            "digest": put.digest,
            "length": sum(len(section.text) for section in sections),
            "first_section": self._next_section,
            "last_section": self._next_section + len(sections) - 1,
        }
        try:
            cursor = self._connection.execute(
                "INSERT INTO documents (path, digest, source, type, id, key, title, space,"
                " project, status, issue_type, labels, people, links, created, updated, version,"
                " revision, url, breadcrumb, fetched_at, length, first_section, last_section)"
                " VALUES (:path, :digest, :source, :type, :id, :key, :title, :space, :project,"
                " :status, :issue_type, :labels, :people, :links, :created, :updated, :version,"
                " :revision, :url, :breadcrumb, :fetched_at, :length, :first_section,"
                " :last_section)",
                values,
            )
        except sqlite3.IntegrityError:
            message = f"{path}: {DUPLICATE}"
            raise DuplicateDocumentError(message) from None
        document = cursor.lastrowid
        self._connection.executemany(
            "INSERT INTO labels (document, label) VALUES (?, ?)",
            [(document, label) for label in front.labels],
        )
        # One row per person and role, and a commenter's one per comment.
        self._connection.executemany(
            "INSERT INTO people (document, role, name, identity, at) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    document,
                    person.role,
                    person.name,
                    person.identity,
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
            "INSERT INTO section_words (rowid, title, labels, breadcrumb, heading, body)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        first = self._next_section
        self._next_section += len(sections)
        return first

    def add_chunks(self, chunks: Iterable[tuple[int, int, int, str, bytes]]) -> None:
        """Add chunks: each its section's rowid, its range in the body, its vector.

        Each vector comes with its key in the vector cache, which only pruning reads.
        """
        self._connection.executemany(
            'INSERT INTO chunks (section, start, "end", key, vector) VALUES (?, ?, ?, ?, ?)',
            chunks,
        )

    def skip(self, skipped: Skipped) -> None:
        """Record a file of the mirror that could not be indexed, with its digest and why."""
        self._connection.execute(
            "INSERT INTO skipped (path, digest, reason) VALUES (?, ?, ?)",
            (skipped.path, skipped.digest, skipped.reason),
        )

    @TRACER.start_as_current_span("index.join")
    def join(self, aliases: Mapping[str, str]) -> people.JoinOutcome:
        """Join the people of the documents added into persons, as ``people.joined`` rules.

        Once the last document is added: every row of ``people`` is given its person, and
        ``persons`` and ``person_names`` hold each person and each of its spellings, with
        how it joined. A document's summaries are the documents of its source that its
        ``summary`` links name, none of which links so to a document of its source.
        ``aliases`` gives each alias's name and value, as the alias file's reader checks
        them, and the build records their digest. Documents go to the join by the order
        of their paths, so that its ties go as in a whole build, whichever file was edited
        last. Give back how many persons there are, and what the join left apart: the
        names that could be several persons, and the aliases that changed nothing; each
        row's person stays here. The span ``index.join`` holds it.
        """
        self.aliases = people.aliases_digest(aliases)
        places = dict(self._connection.execute(BY_PATH))
        rows = {
            rowid: people.PersonRow(
                document=places[document],
                role=role,
                name=name,
                identity=identity,
                updated=datetime.fromisoformat(updated),
            )
            for rowid, document, role, name, identity, updated in self._connection.execute(
                PEOPLE_ROWS
            )
        }
        summaries: dict[int, set[int]] = {}
        for document, summary in self._connection.execute(SUMMARY_LINKS):
            summaries.setdefault(places[document], set()).add(places[summary])
        found = people.joined(rows.values(), summaries, aliases)
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
                (person.id, spelling.name, spelling.name_key, spelling.how)
                for person in found.persons
                for spelling in person.spellings
            ],
        )
        return people.JoinOutcome(
            count=len(found.persons), ambiguous=found.ambiguous, unused=found.unused
        )

    def update(self, change: Change, old: Path | None) -> Updated:
        """Write a change into this new index, copying from the index at ``old``, if any.

        Every document of ``old`` is copied but those that the change removes, puts or
        skips, and one whose source and id a file put earlier by the parts of its path
        holds, which is skipped. FTS5 indexes the sections copied, then the documents put
        are added in that order, so that of two of one source and id the first is held,
        and their sections are numbered after the largest copied. Persons are joined
        last, over every document.
        """
        connection = self._connection
        puts = sorted(change.put, key=lambda put: PurePosixPath(put.path))
        left = {
            *change.removed,
            *(put.path for put in puts),
            *(each.path for each in change.skipped),
        }
        skipped = list(change.skipped)
        held: dict[str, str] = {}  # each document of ``old``, and its digest
        if old is not None:
            connection.execute("ATTACH DATABASE ? AS old", (f"{old.as_uri()}?mode=ro",))
            held = dict(connection.execute("SELECT path, digest FROM old.documents"))
            keys = json.dumps([[put.front.source, put.front.id] for put in puts])
            parameters = {"keys": keys, "left": json.dumps(sorted(left))}
            holders = {(row[1], row[2]): row[0] for row in connection.execute(HOLDERS, parameters)}
            for put in puts:
                holder = holders.pop((put.front.source, put.front.id), None)
                if holder is not None and PurePosixPath(put.path) < PurePosixPath(holder):
                    left.add(holder)
                    skipped.append(Skipped(path=holder, digest=held[holder], reason=DUPLICATE))
            for statement in COPY:
                connection.execute(statement, {"left": json.dumps(sorted(left))})
            connection.execute("INSERT INTO section_words (section_words) VALUES ('rebuild')")
            self._next_section += (
                connection.execute("SELECT max(rowid) FROM sections").fetchone()[0] or 0
            )
        copied = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
        taken: set[str] = set()
        for put in puts:
            try:
                self.add(put)
            except DuplicateDocumentError:
                skipped.append(Skipped(path=put.path, digest=put.digest, reason=DUPLICATE))
            else:
                taken.add(put.path)
        for each in skipped:
            self.skip(each)
        persons = self.join(change.aliases)
        replaced = len(taken & held.keys())
        wanting = None if self.embedded is None else awaiting(connection, self.embedded.chunking)
        return Updated(
            build=self.build,
            copied=copied,
            added=len(taken) - replaced,
            replaced=replaced,
            removed=len(held) - copied - replaced,
            types=dict(connection.execute(VALUES["type"]).fetchall()),
            sections=connection.execute("SELECT count(*) FROM sections").fetchone()[0],
            awaiting=wanting,
            skipped=tuple(sorted(skipped, key=lambda each: each.path)),
            persons=persons,
        )


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
def aside(path: Path) -> Iterator[Path]:
    """Give a new, empty file beside ``path``, which replaces it once the block ends.

    On any failure the file at ``path`` stays, and the new file is removed. Its name
    begins with BUILDING, which readers and the prune skip.
    """
    descriptor, name = tempfile.mkstemp(prefix=BUILDING, suffix=".sqlite", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def building(path: Path, built_at: datetime, embedded: Embedded | None = None) -> Iterator[Writer]:
    """Build a new index at ``path``, in one transaction, into a file beside it.

    ``embedded`` names the model of its chunks' vectors, if any. The file is renamed
    into place once complete. On any failure the index already at ``path`` stays, and
    the new file is removed.
    """
    with aside(path) as temporary:
        # By its address, so that an update can attach the index in place read-only.
        connection = sqlite3.connect(temporary.as_uri(), autocommit=False, uri=True)
        try:
            connection.executescript(CREATE)
            writer = Writer(connection, embedded)
            yield writer
            connection.execute("INSERT INTO section_words (section_words) VALUES ('optimize')")
            skipped = connection.execute("SELECT count(*) FROM skipped").fetchone()[0]
            connection.executemany(
                "INSERT INTO meta (name, value) VALUES (?, ?)",
                [
                    ("schema", SCHEMA),
                    ("built_at", moment(built_at)),
                    ("skipped", str(skipped)),
                    ("words", WORDS),
                    ("aliases", writer.aliases),
                    ("build", writer.build),
                    ("model", embedded.model if embedded else ""),
                    ("fingerprint", embedded.fingerprint if embedded else ""),
                    ("dimensions", str(embedded.dimensions) if embedded else ""),
                    ("chunking", embedded.chunking if embedded else ""),
                ],
            )
            connection.commit()
        finally:
            connection.close()


def indexed_document(row: sqlite3.Row) -> IndexedDocument:
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
            Mention(
                role=person["role"],
                name=person["name"],
                identity=person["identity"],
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
    return IndexedDocument(path=row["path"], front=front, length=row["length"], sections=sections)


class Reader:
    """Queries of one open index.

    A list is bounded by a limit, or else by what one space, project or filter holds.
    """

    def __init__(
        self, connection: sqlite3.Connection, searched: Callable[[Reader], ChunkVectors]
    ) -> None:
        """Read through an open, read-only connection; ``searched`` gives what meaning searches."""
        self._connection = connection
        self._searched = searched
        self._kept: dict[Filters, str | None] = {}

    def kept(self, filters: Filters) -> str | None:
        """Name the documents that pass the filters, or None when nothing is filtered."""
        if filters == Filters():
            return None
        if filters not in self._kept:
            parameters = {
                name: moment(value) if isinstance(value, datetime) else value
                for name, value in filters.model_dump().items()
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
                relevance=row["relevance"],
                updated=datetime.fromisoformat(row["updated"]),
                created=datetime.fromisoformat(row["created"]),
            )
            for row in self._connection.execute(SCORES, parameters)
        }
        return found, every or len(found) < PER_EXPRESSION

    def snippet(self, path: str, match: str) -> Passage | None:
        """Find the section of a document that best matches, with a snippet of its body.

        Sections are judged by their heading and body alone: a match on the title alone
        gives the first section.
        """
        parameters = {**SECTION_WEIGHTS, "match": match, "path": path, "tokens": SNIPPET_TOKENS}
        row = self._connection.execute(PASSAGE, parameters).fetchone()
        return (
            None
            if row is None
            else Passage(number=row["number"], heading=row["heading"], text=row["snippet"])
        )

    def indexed_documents(
        self,
        *,
        paths: Iterable[str] = (),
        keys: Iterable[str] = (),
        ids: Iterable[str] = (),
        filters: Filters | None = None,
    ) -> list[IndexedDocument]:
        """Find the documents of these paths, issue keys, and page or work-log ids, by path.

        An issue's id is never looked up, since a page may have the same.
        """
        parameters = {
            "paths": json.dumps(list(paths)),
            "keys": json.dumps(list(keys)),
            "ids": json.dumps(list(ids)),
            "kept": self.kept(filters or Filters()),
        }
        return [indexed_document(row) for row in self._connection.execute(ENTRIES, parameters)]

    def recent(
        self, filters: Filters, by: Sort, offset: int, limit: int
    ) -> tuple[int, list[IndexedDocument]]:
        """Count the documents that pass the filters, and list a page of them, newest first.

        Newest by created date, or else by update; ties go to the newest update, then the
        path.
        """
        kept = self.kept(filters)
        total = self._connection.execute(COUNT, {"kept": kept}).fetchone()[0]
        parameters = {"kept": kept, "by": by, "offset": offset, "limit": limit}
        return total, [
            indexed_document(row) for row in self._connection.execute(RECENT, parameters)
        ]

    def listing(self, filters: Filters) -> list[IndexedDocument]:
        """List every document that passes the filters, such as those of one space."""
        rows = self._connection.execute(LISTING, {"kept": self.kept(filters)})
        return [indexed_document(row) for row in rows]

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

        ``joined``, if given, keeps the names that joined so, such as ``people.BY_IDENTITY``.
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
        spellings = tuple(
            people.Spelling(name=name, name_key=key, how=how) for name, key, how in rows
        )
        roles = self._connection.execute(PERSON_ROLES, {"person": person})
        sources = self._connection.execute(PERSON_SOURCES, {"person": person}).fetchall()
        return Activity(
            person=people.Person(id=person, name=name[0], spellings=spellings),
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

    def held(self) -> Held:
        """Say what the index holds of the mirror's files, by path, and what wrote it.

        One built before plan 035 records no ``words``, nor its files' digests: an update
        keeps nothing of it.
        """
        meta = dict(self._connection.execute("SELECT name, value FROM meta").fetchall())
        if "words" not in meta:
            return Held(build=meta["build"], words=None, aliases=None, documents={}, skipped={})
        documents = self._connection.execute("SELECT path, digest FROM documents").fetchall()
        skipped = self._connection.execute("SELECT path, digest, reason FROM skipped")
        return Held(
            build=meta["build"],
            words=meta["words"],
            aliases=meta["aliases"],
            documents=dict(documents),
            skipped={
                path: Skipped(path=path, digest=digest, reason=reason)
                for path, digest, reason in skipped
            },
        )

    def documents(self) -> list[IndexedBody]:
        """Give every document with its front matter and its body as put, by path.

        The body is each section's heading line and body, in order, which give it back.
        """
        bodies: dict[str, list[str]] = {}
        for path, text in self._connection.execute(BODIES):
            bodies.setdefault(path, []).append(text)
        rows = self._connection.execute("SELECT * FROM documents ORDER BY path")
        return [
            IndexedBody(
                path=row["path"],
                front=indexed_document(row).front,
                body="".join(bodies.get(row["path"], ())),
            )
            for row in rows
        ]

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
        # Indexes of 011 and 018 have no chunking: their chunks were cut by sections.
        chunking = cast("Chunking", meta.get("chunking", "sections"))
        return Embedded(
            model=meta["model"],
            fingerprint=meta["fingerprint"],
            dimensions=int(meta["dimensions"]),
            chunking=chunking,
        )

    def keys(self) -> set[str]:
        """Give the vector cache's keys of the chunks' vectors: what the index reads of it.

        An index built by words alone names no vector, and cannot say which vectors a prune
        must keep: raise UnavailableIndexError.
        """
        model = self._connection.execute("SELECT value FROM meta WHERE name = 'model'").fetchone()
        if not model or not model[0]:
            message = "built by words alone"
            raise UnavailableIndexError(message)
        return {row[0] for row in self._connection.execute("SELECT DISTINCT key FROM chunks")}

    def chunks(self) -> list[Chunk]:
        """Give every chunk that has its vector, by path, section number and start."""
        return [
            Chunk(path=path, number=number, start=start, end=end, vector_key=key)
            for path, number, start, end, key in self._connection.execute(
                CHUNKS.format(columns="p.key")
            )
        ]

    def vectors(self) -> ChunkVectors:
        """Read every chunk's vector, with where the chunk is: what meaning searches."""
        columns = "d.rowid AS document, d.updated, p.vector"
        rows = self._connection.execute(CHUNKS.format(columns=columns)).fetchall()
        dimensions = len(rows[0]["vector"]) // vector_cache.LAYOUT.itemsize if rows else 0
        matrix = np.frombuffer(b"".join(row["vector"] for row in rows), dtype=vector_cache.LAYOUT)
        return ChunkVectors(
            documents=tuple(row["document"] for row in rows),
            sections=tuple(row["number"] for row in rows),
            starts=tuple(row["start"] for row in rows),
            ends=tuple(row["end"] for row in rows),
            matrix=matrix.astype(np.float32).reshape(len(rows), dimensions),
            paths={row["document"]: row["path"] for row in rows},
            updated={row["path"]: datetime.fromisoformat(row["updated"]) for row in rows},
        )

    def nearest(
        self, vector: NDArray[np.float32], filters: Filters, depth: int
    ) -> dict[str, tuple[Score, Matched]]:
        """Give at most ``depth`` documents passing the filters, nearest a unit vector first.

        Each path comes with its score, then its best chunk.
        """
        kept = self.kept(filters)
        allowed = None if kept is None else set(json.loads(kept))
        return self._searched(self).nearest(vector, allowed, depth)

    def heading(self, path: str, number: int) -> str:
        """Give the heading of a document's section."""
        row = self._connection.execute(
            "SELECT s.heading FROM sections s JOIN documents d ON d.rowid = s.document"
            " WHERE d.path = :path AND s.number = :number",
            {"path": path, "number": number},
        ).fetchone()
        return "" if row is None else row[0]

    def index_status(self) -> IndexStatus:
        """Say what the index holds and when it was built."""
        meta = dict(self._connection.execute("SELECT name, value FROM meta").fetchall())
        newest = self._connection.execute("SELECT max(fetched_at) FROM documents").fetchone()[0]
        sections = self._connection.execute("SELECT count(*) FROM sections").fetchone()[0]
        chunks = self._connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        persons, alone = self._connection.execute(PERSON_COUNTS).fetchone()
        across = self._connection.execute(ACROSS).fetchone()[0]
        shared = tuple((row[0], row[1]) for row in self._connection.execute(SHARED))
        embedded = self.embedded()
        wanting = awaiting(self._connection, embedded.chunking) if embedded else 0
        return IndexStatus(
            built_at=self.built_at(),
            skipped=int(meta["skipped"]),
            types=dict(self.values("type")),
            spaces=dict(self.values("space")),
            projects=dict(self.values("project")),
            sections=sections,
            newest_fetch=None if newest is None else datetime.fromisoformat(newest),
            persons=PersonCounts(count=persons, across=across, alone=alone, shared=shared),
            model=meta["model"] or None,
            chunks=chunks,
            chunking=embedded.chunking if embedded else None,
            awaiting=wanting,
        )


@contextmanager
def reading(
    path: Path, searched: Callable[[Reader], ChunkVectors] = Reader.vectors
) -> Iterator[Reader]:
    """Open the index at ``path`` read-only, for one use; never write to it.

    ``searched`` gives ``Reader.nearest`` what it searches: by default, read at each search.
    Raise UnavailableIndexError when there is none, or when this version cannot read it.
    Another schema names ``prepare``, then ``index``, not ``index`` alone: a new schema
    can come with a new format of the mirror's files, which ``index`` would skip, and
    ``prepare`` writes them first; one of SAME_MIRROR names ``index`` alone.
    """
    unread = f"{path} is not an index that this version reads: rebuild it with"
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        message = f"no index at {path}: build it with `kb-mcp index`"
        raise UnavailableIndexError(message) from None
    try:
        connection.row_factory = sqlite3.Row
        try:
            meta = dict(connection.execute(META).fetchall())
        except sqlite3.DatabaseError:
            meta = {}
        if meta.get("schema") != SCHEMA:
            prepare = (
                ""
                if meta.get("schema") in SAME_MIRROR
                else " `kb-mcp prepare`, which writes the mirror again first, then"
            )
            message = f"{unread}{prepare} `kb-mcp index`, then `kb-mcp embed`"
            raise UnavailableIndexError(message)
        # A chunking that this version lacks would be cut as no table says.
        if meta.get("chunking", "") not in {"", *CHUNKINGS}:
            message = f"{unread} `kb-mcp index`, then `kb-mcp embed`"
            raise UnavailableIndexError(message)
        yield Reader(connection, searched)
    finally:
        connection.close()


class SqliteIndex:
    """One index file, in this process: the words index and the vector index together.

    It opens a reader per use, by ``reading``, and keeps the vectors of the last build
    read, so that a search reads them once a build.
    """

    def __init__(self, path: Path) -> None:
        """Name the index at ``path``, which need not be there yet."""
        self._path = path
        self._lock = threading.Lock()  # the SDK runs tools in worker threads
        self._kept: tuple[str, ChunkVectors] | None = None  # a build and its vectors

    @contextmanager
    def reading(self) -> Iterator[Reader]:
        """Open one use of the index, as ``reading`` does, its vectors kept here.

        Raises DamagedIndexError, naming ``kb-mcp index --rebuild``, when a read of the
        use finds a table damaged.
        """
        try:
            with reading(self._path, self._vectors) as reader:
                yield reader
        except sqlite3.DatabaseError as error:
            if not damaged(error):
                raise
            message = f"{self._path} is damaged ({error}): rebuild it with `kb-mcp index --rebuild`"
            raise DamagedIndexError(message) from None

    def update(self, change: Change, expected_build: str | None) -> Updated | None:
        """Change the index as ``WordsIndex.update`` says: a new file, renamed into place.

        Its lock, beside it, is held exclusive from the check of the build until the
        rename, ``index.lock_wait`` saying a wait; a change that is not whole attaches the
        index in place read-only and copies from it, keeping its model's rows, and a table
        of it found damaged raises DamagedIndexError. A failure leaves the index in place,
        and removes the new file.
        """
        lock = vector_cache.lock_of(self._path)
        with vector_cache.locked(lock, fcntl.LOCK_EX, "index.lock_wait", WRITER):
            embedded = None
            if not change.whole:
                try:
                    with reading(self._path) as reader:
                        if reader.build() != expected_build:
                            return None
                        embedded = reader.embedded()
                except UnavailableIndexError:
                    return None
            try:
                with building(self._path, change.built_at, embedded) as writer:
                    updated = writer.update(change, None if change.whole else self._path)
            except sqlite3.DatabaseError as error:
                # A whole update reads no index in place: its error is its own.
                if change.whole or not damaged(error):
                    raise
                message = f"{self._path} is damaged ({error}): it is rebuilt whole"
                raise DamagedIndexError(message) from None
            return updated

    def fill(
        self,
        expected_build: str,
        model: Embedded,
        add: Mapping[Chunk, NDArray[np.float32]],
        remove: Collection[Chunk],
    ) -> str | None:
        """Fill the index's chunks as ``VectorIndex.fill`` says: in a copy, renamed into place.

        Under its lock, as an update: SQLite's backup copies the index beside it, the copy
        removes and adds the chunks, each resolving its section to a rowid, and names the
        model and a new build; the index's time stays its update's.
        """
        lock = vector_cache.lock_of(self._path)
        with vector_cache.locked(lock, fcntl.LOCK_EX, "index.lock_wait", WRITER):
            try:
                with reading(self._path) as reader:
                    if reader.build() != expected_build:
                        return None
            except UnavailableIndexError:
                return None
            build = uuid.uuid4().hex
            source = f"{self._path.as_uri()}?mode=ro"
            try:
                with (
                    aside(self._path) as temporary,
                    closing(sqlite3.connect(source, uri=True)) as old,
                    closing(sqlite3.connect(temporary)) as copy,
                ):
                    old.backup(copy)
                    removed = copy.executemany(
                        FILL_REMOVE, [chunk.model_dump() for chunk in remove]
                    ).rowcount
                    added = copy.executemany(
                        FILL_ADD,
                        [
                            chunk.model_dump() | {"vector": vector_cache.as_bytes(vector)}
                            for chunk, vector in add.items()
                        ],
                    ).rowcount
                    if (removed, added) != (len(remove), len(add)):
                        message = f"{self._path}: a chunk names a section that the index lacks"
                        raise ValueError(message)
                    copy.executemany(
                        "UPDATE meta SET value = ? WHERE name = ?",
                        [
                            (model.model, "model"),
                            (model.fingerprint, "fingerprint"),
                            (str(model.dimensions), "dimensions"),
                            (model.chunking, "chunking"),
                            (build, "build"),
                        ],
                    )
                    copy.commit()
            except sqlite3.DatabaseError as error:
                if not damaged(error):
                    raise
                message = (
                    f"{self._path} is damaged ({error}): rebuild it with `kb-mcp index --rebuild`"
                )
                raise DamagedIndexError(message) from None
            return build

    def _vectors(self, reader: Reader) -> ChunkVectors:
        """Give the vectors of the build that ``reader`` reads, from memory once read."""
        with self._lock:
            build = reader.build()
            if self._kept is None or self._kept[0] != build:
                self._kept = (build, reader.vectors())
            return self._kept[1]
