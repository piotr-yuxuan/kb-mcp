"""An index updated by ``index``, then filled by ``embed``, equals a whole build (plan 035).

Criterion 5: after each step of a scripted sequence, every table of the updated index,
filled, is a whole build's of the same mirror by ``build_index``, by what no rowid
changes, but its build and the time it was built. Criterion 6: the queries rank alike
in every mode. Criterion 15: persons, joined whole at each write, follow a document
added, removed or edited elsewhere as a whole build joins them.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from copy import replace
from typing import TYPE_CHECKING

import pytest

from kb_mcp.mcp.app.tools import Library
from kb_mcp.mirror.domain.mirror import Mention
from kb_mcp.search.adapters.aliases import read_aliases
from kb_mcp.search.adapters.sqlite_index import SqliteIndex
from kb_mcp.search.app.indexing import (
    Embedding,
    Indexing,
    build_index,
    fill_and_prune,
    update_index,
)
from kb_mcp.search.app.meaning import Meaning
from tests.endpoint import Scripted, connect_scripted, scripted, tiny
from tests.mirrors import MOMENT, fillers, issue, location, page, worklog_document, write
from tests.test_evaluate import GOLDEN
from tests.test_people import SAM_2

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import SearchMode
    from kb_mcp.kernel.chunking import Chunking
    from kb_mcp.mirror.domain.mirror import FrontMatter

# Each table of an index, by what no rowid changes: documents by every column but their
# rowids and their sections' bounds, the rest by path, and the meta rows but the build's.
TABLES = {
    "documents": """
        SELECT path, digest, source, type, id, key, title, space, project, status,
               issue_type, labels, people, links, created, updated, version, revision, url,
               breadcrumb, fetched_at, length, last_section - first_section
        FROM documents ORDER BY path
    """,
    "labels": """
        SELECT d.path, l.label FROM labels l JOIN documents d ON d.rowid = l.document
        ORDER BY 1, 2
    """,
    "people": """
        SELECT d.path, p.role, p.name, p.identity, p.at, p.person
        FROM people p JOIN documents d ON d.rowid = p.document ORDER BY 1, 2, 3, 4, 5, 6
    """,
    "persons": "SELECT id, name FROM persons ORDER BY id",
    "person_names": "SELECT person, name, key, joined FROM person_names ORDER BY 1, 2, 3, 4",
    "sections": """
        SELECT d.path, s.number, s.start, s.head, s.title, s.labels, s.breadcrumb, s.heading,
               s.body
        FROM sections s JOIN documents d ON d.rowid = s.document ORDER BY 1, 2
    """,
    "skipped": "SELECT path, digest, reason FROM skipped ORDER BY path",
    "chunks": """
        SELECT d.path, s.number, p.start, p."end", p.key, p.vector FROM chunks p
        JOIN sections s ON s.rowid = p.section JOIN documents d ON d.rowid = s.document
        ORDER BY 1, 2, 3, 4, 5
    """,
    "meta": "SELECT name, value FROM meta WHERE name NOT IN ('build', 'built_at') ORDER BY 1",
}
# Weights of the tiny model other than the fixtures': its fingerprint changes.
OTHER_WEIGHTS = {"tiny:latest": "e2" * 32}


def rows(index: Path) -> dict[str, list[tuple[object, ...]]]:
    """Read every table of an index; check its full-text index, on a copy, as FTS5 does."""
    copy = index.with_name(f"checked-{index.name}")
    copy.write_bytes(index.read_bytes())
    with closing(sqlite3.connect(copy)) as connection:
        connection.execute(
            "INSERT INTO section_words (section_words, rank) VALUES ('integrity-check', 1)"
        )
        read = {name: connection.execute(query).fetchall() for name, query in TABLES.items()}
    copy.unlink()
    return read


class Step:
    """How ``index``, then ``embed``, run on the data directory, and the whole build to match."""

    def __init__(self, data: Path) -> None:
        """Run on ``data``, cut by sections, with the tiny model's usual weights."""
        self.data = data
        self.chunking: Chunking = "sections"
        self.models: dict[str, str] | None = None

    def indexing(self) -> Indexing:
        """Say how ``index`` and ``embed`` write the index, as scripted."""
        answers = Scripted() if self.models is None else Scripted(models=self.models)
        return Indexing(
            docs=self.data / "docs",
            index=self.data / "index.sqlite",
            vectors=self.data / "vectors.sqlite",
            evaluation_indexes=self.data / "eval" / "indexes",
            aliases=self.data / "aliases.toml",
            model="tiny",
            chunking=self.chunking,
            endpoint=lambda: scripted(answers),
        )

    def run(self) -> None:
        """Update the index, then fill it, as ``index`` then ``embed`` do."""
        assert update_index(self.indexing(), MOMENT) is not None
        assert fill_and_prune(self.indexing()) is not None

    def whole(self) -> Path:
        """Build the mirror whole, by ``build_index``, with the same aliases, model and cut."""
        whole = self.data.parent / "whole.sqlite"
        answers = Scripted() if self.models is None else Scripted(models=self.models)
        embedding = Embedding(tiny(answers), self.data.parent / "whole.db", self.chunking)
        aliases = read_aliases(self.data / "aliases.toml")
        build_index(self.data / "docs", whole, MOMENT, embedding, aliases)
        return whole

    def equal(self) -> None:
        """Run ``index`` and ``embed``; their index must hold a whole build's every row."""
        self.run()
        assert rows(self.data / "index.sqlite") == rows(self.whole())


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a scratch home and a data directory whose mirror has a few pages."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    fillers(tmp_path / "data" / "docs", 4)
    return tmp_path / "data"


BODY = "# Rollback\n\nUndo the payout.\n\n## Release\n\nThe deploy of the seller service.\n"
ROLLBACK = page("196845", "Rollback", labels=("ops",))
ENTRY = replace(
    page("e-20261020-1", "Old title"), source="worklog", type="entry", space=None, version=None
)


def test_an_updated_index_equals_a_whole_build_at_each_step(data: Path) -> None:
    """Criterion 5: every table, after each change of the mirror, the chunking or the model."""
    docs = data / "docs"
    step = Step(data)
    step.equal()
    rollback = write(docs, ROLLBACK, BODY)
    step.equal()  # added
    write(docs, ROLLBACK, BODY.replace("seller", "buyer"))
    step.equal()  # edited
    (docs / rollback).unlink()
    retitled = write(docs, replace(ROLLBACK, title="Rollback plan"), BODY)
    step.equal()  # retitled, so that its path changes
    (docs / retitled).unlink()
    moved = write(docs, replace(ROLLBACK, title="Rollback plan", space="OPS"), BODY)
    step.equal()  # moved to another space
    (docs / moved).unlink()
    step.equal()  # removed
    first = write(docs, ROLLBACK, BODY)
    step.equal()
    earlier = docs / "confluence" / "ENG" / "100-copy.md"
    earlier.write_bytes((docs / first).read_bytes())
    step.equal()  # a second file of one source and id under an earlier path
    earlier.unlink()
    step.equal()  # that file removed, the first taken again
    write(docs, ENTRY, "# Old title\n\nNotes.\n")
    write(docs, replace(ENTRY, title="New title"), "# New title\n\nNotes.\n")
    step.equal()  # a retitled entry's old file left beside its new one
    (docs / "confluence" / "ENG" / "1-broken.md").write_text("---\ntitle: x\n---\n", "utf-8")
    step.equal()  # a file that load refuses
    step.chunking = "windows"
    step.equal()  # the chunking changed
    step.models = OTHER_WEIGHTS
    step.equal()  # the model's fingerprint changed


MODES: tuple[SearchMode, ...] = ("lexical", "semantic", "hybrid")
QUERIES = ("vacation lunch", "revert release", "PROJ-7 upgrade", "lorem ipsum", "payout deploy")


def rankings(index: Path, docs: Path) -> dict[tuple[str, SearchMode], list[tuple[str, int, str]]]:
    """Rank each query in each mode, the reranker off, as an evaluation does."""
    library = Library(SqliteIndex(index), docs, Meaning(connect_scripted()))
    return {
        (query, mode): [
            (shown.path, shown.section, shown.text) for shown in library.ranked(query, mode)[0]
        ]
        for query in QUERIES
        for mode in MODES
    }


def test_an_updated_index_ranks_as_a_whole_build(data: Path) -> None:
    """Criterion 6: through a sequence of edits, the same paths, order and sections.

    In the lexical, semantic and hybrid modes, as a whole build of the final mirror.
    """
    assert GOLDEN  # its questions are among the queries
    docs = data / "docs"
    write(docs, page("4002", "Holiday canteen"), "# Holiday canteen\n\nLeave for a **meal**.\n")
    write(docs, page("4003", "Words"), "revert release\n")
    step = Step(data)
    step.run()
    write(docs, issue("PROJ-7", "Kafka upgrade"), "# Kafka upgrade\n\nThe broker moves on.\n")
    step.run()
    write(docs, ROLLBACK, BODY)
    write(docs, page("4003", "Words"), "revert release, then deploy the payout\n")
    step.run()
    (docs / location(page("900001", "Lorem 1"))).unlink()
    step.run()
    updated = rankings(data / "index.sqlite", docs)
    assert updated == rankings(step.whole(), docs)
    assert all(updated[query, "semantic"] for query in QUERIES)


SAM = "Sam Sample"
SYNC = worklog_document("meeting", "m-20261020-sync", "Sync", (SAM,))


def authored(key: str, name: str, identity: str | None) -> tuple[FrontMatter, str]:
    """Give the front matter and body of an issue authored by a name, with its identity."""
    author = Mention(role="author", name=name, identity=identity)
    return issue(key, f"Issue {key}", people=(author,)), f"# Issue {key}\n"


def test_a_name_alone_follows_the_accounts_of_its_name_as_a_whole_build(data: Path) -> None:
    """Criterion 15: a meeting's name joins one account's issue, then neither of two; back.

    The meeting's file never changes; each step's persons are a whole build's.
    """
    docs = data / "docs"
    step = Step(data)
    write(docs, SYNC, "# Sync\n")
    step.equal()
    first = write(docs, *authored("PROJ-2", SAM, "atlassian:acct-0002"))
    step.equal()
    second = write(docs, *authored("PROJ-3", SAM, "atlassian:acct-0003"))
    step.equal()
    (docs / second).unlink()
    step.equal()
    (docs / first).unlink()
    step.equal()


def test_a_speaker_follows_its_meeting_s_participant_as_a_whole_build(data: Path) -> None:
    """Criterion 15: the meeting edited so that its participant changes; the transcript not."""
    docs = data / "docs"
    step = Step(data)
    meeting = worklog_document("meeting", "m-20261021-review", "Review", ("Alex Example",), "t-1")
    transcript = worklog_document("transcript", "t-1", "Meeting", ("Alex",), "m-20261021-review")
    write(docs, meeting, "# Review\n")
    write(docs, transcript, "# Meeting\n")
    write(docs, *authored("PROJ-4", "Alex Example", "atlassian:acct-0004"))
    write(docs, *authored("PROJ-5", "Alex Other", "atlassian:acct-0005"))
    step.equal()
    write(
        docs,
        replace(meeting, people=(Mention(role="participant", name="Alex Other"),)),
        "# Review\n",
    )
    step.equal()


@pytest.mark.parametrize("identity", ["atlassian:acct-0006", None])
def test_tied_spellings_serve_a_whole_build_s_name_whichever_file_was_edited(
    data: Path, identity: str | None
) -> None:
    """Criterion 15: two spellings of one person, of one update time; the first file edited.

    One account's two names, or a name alone spelt twice: the name served is a whole
    build's, though the edited file now has the largest rowid.
    """
    docs = data / "docs"
    step = Step(data)
    names = ("Robin Tied", "Robin Tie") if identity else ("Jo Twice", "JO TWICE")
    first = authored("PROJ-6", names[0], identity)
    write(docs, *first)
    write(docs, *authored("PROJ-7", names[1], identity))
    step.equal()
    write(docs, first[0], f"{first[1]}\nEdited, the time kept.\n")
    step.equal()


def test_an_alias_file_changed_alone_writes_a_build_copying_every_document(data: Path) -> None:
    """Criterion 15: joined by the alias, the chunks kept, and ``embed`` then writes nothing.

    The file refused, ``index`` stops, the index in place; ``embed`` runs regardless.
    """
    docs = data / "docs"
    step = Step(data)
    write(docs, SYNC, "# Sync\n")
    write(docs, *authored("PROJ-2", "Sam Sample", "atlassian:acct-0002"))
    write(docs, *authored("PROJ-3", "Sam Sample", "atlassian:acct-0003"))
    step.equal()
    held = rows(data / "index.sqlite")
    alias = f'"Sam Sample" = "{SAM_2}"\n'  # the account acct-0002's person
    (data / "aliases.toml").write_text(alias, encoding="utf-8")
    updated = update_index(step.indexing(), MOMENT)
    assert updated is not None
    assert (updated.report.copied, updated.report.added) == (len(held["documents"]), 0)
    assert updated.report.persons.count < len(held["persons"])
    filled = fill_and_prune(step.indexing())
    assert filled is not None
    assert filled.unchanged
    assert rows(data / "index.sqlite") == rows(step.whole())
    assert rows(data / "index.sqlite")["chunks"] == held["chunks"]
    before = (data / "index.sqlite").read_bytes()
    (data / "aliases.toml").write_text("not = [toml\n", encoding="utf-8")
    assert update_index(step.indexing(), MOMENT) is None
    assert (data / "index.sqlite").read_bytes() == before
    filled = fill_and_prune(step.indexing())
    assert filled is not None
    assert filled.unchanged
