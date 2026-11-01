"""What any backend of the words and vector indexes must do, as plan 035 asks.

Each test holds a backend to the docstrings of ``search.domain.indexes``, through those
protocols alone, on made-up documents; a new backend joins ``BACKENDS``. Snapshots, all or
nothing, the lock and the rename are no part of it: they are SQLite's own, in
``test_index.py``, as other backends offer neither.
"""

from __future__ import annotations

import functools
from copy import replace
from datetime import timedelta
from inspect import signature
from typing import TYPE_CHECKING, get_protocol_members

import numpy as np
import pytest

from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import FrontMatter, PersonRole
from kb_mcp.search.adapters import sqlite_index, vector_store
from kb_mcp.search.domain import people
from kb_mcp.search.domain.indexes import SearchReader, UnavailableIndexError
from kb_mcp.search.domain.search import Embedded, Filters, quote, sections
from tests.mirrors import MOMENT, issue, location, page, worklog_document

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

    from kb_mcp.search.domain.indexes import SearchIndex

# What writes documents, and a model if any, into a new index of a backend.
type Written = Callable[..., SearchIndex]
EMBEDDED = Embedded(model="made-up", fingerprint="f1", dimensions=3, chunking="sections")
NORTH = (1.0, 0.0, 0.0)
EAST = (0.0, 1.0, 0.0)
UP = (0.0, 0.0, 1.0)
# North with a little east: its cosine with north is 0.8.
NORTHISH = (0.8, 0.6, 0.0)
NORTHISH_COSINE = 0.8
EPSILON = 1e-6


class Piece(Record):
    """A piece of a document, as a fill names it: its section's number, span, key and vector."""

    number: int
    start: int  # in the section's body, after its heading line
    stop: int
    key: str
    vector: tuple[float, ...]


class Document(Record):
    """A document to write, with its pieces, if any."""

    front: FrontMatter
    body: str
    pieces: tuple[Piece, ...] = ()


def sqlite(
    folder: Path, documents: Sequence[Document], embedded: Embedded | None = None
) -> SearchIndex:
    """Write the documents into a new SQLite index, as a whole build writes them."""
    path = folder / "index.sqlite"
    with sqlite_index.building(path, MOMENT, embedded) as writer:
        for document in documents:
            first = writer.add(location(document.front), document.front, sections(document.body))
            writer.add_pieces(
                (
                    first + piece.number - 1,
                    piece.start,
                    piece.stop,
                    piece.key,
                    vector_store.as_bytes(np.array(piece.vector, dtype=np.float32)),
                )
                for piece in document.pieces
            )
        writer.join({})
    return sqlite_index.SqliteIndex(path)


BACKENDS = {"sqlite": sqlite}


@pytest.fixture(params=BACKENDS)
def written(request: pytest.FixtureRequest, tmp_path: Path) -> Written:
    """Give what writes documents into a new index, of each backend in turn."""
    return functools.partial(BACKENDS[request.param], tmp_path)


def piece_of(body: str, text: str, key: str, vector: tuple[float, ...]) -> Piece:
    """Name the piece holding ``text``, by where the first section holding it has it."""
    section = next(each for each in sections(body) if text in each.body)
    start = section.body.index(text)
    return Piece(number=section.number, start=start, stop=start + len(text), key=key, vector=vector)


def query(vector: tuple[float, ...]) -> NDArray[np.float32]:
    """Give a vector as a query's embedding comes."""
    return np.array(vector, dtype=np.float32)


RUNBOOK = page("1001", "Rollback runbook", labels=("ops",), breadcrumb=("Guides",))
RUNBOOK_BODY = "# Rollback runbook\n\nWhy we restore.\n\n## Restore\n\nRestore the ledger.\n"
RUNBOOK_PATH = location(RUNBOOK)
UPGRADE = issue("PROJ-7", "Kafka upgrade", updated=MOMENT - timedelta(days=1))
UPGRADE_BODY = "# Kafka upgrade\n\nThe broker moves on.\n"
UPGRADE_PATH = location(UPGRADE)
BOTH = (Document(front=RUNBOOK, body=RUNBOOK_BODY), Document(front=UPGRADE, body=UPGRADE_BODY))


def test_a_document_is_ranked_by_its_words(written: Written) -> None:
    """A word that one document holds finds it alone, with its dates; another word, nothing."""
    with written(BOTH).reading() as reader:
        found, whole = reader.scores(quote("ledger"), Filters())
        assert list(found) == [RUNBOOK_PATH]
        assert whole
        assert found[RUNBOOK_PATH].updated == RUNBOOK.updated
        assert found[RUNBOOK_PATH].created == RUNBOOK.created
        assert reader.scores(quote("ledger"), Filters(), every=True) == (found, True)
        assert reader.scores(quote("absent"), Filters()) == ({}, True)


def test_more_of_a_word_ranks_higher(written: Written) -> None:
    """Of two documents holding a word, the one holding more of it scores higher."""
    more = page("1002", "Dense")
    less = page("1003", "Sparse")
    index = written(
        [
            Document(front=more, body="# Dense\n\nbroker broker broker\n"),
            Document(front=less, body=f"# Sparse\n\nbroker {'filler ' * 40}\n"),
        ]
    )
    with index.reading() as reader:
        found, _ = reader.scores(quote("broker"), Filters())
    assert found[location(more)].relevance > found[location(less)].relevance


def test_a_document_is_read_back(written: Written) -> None:
    """Its front matter, length and sections come back, its text by any span of its body."""
    with written(BOTH).reading() as reader:
        (entry,) = reader.entries(paths=[RUNBOOK_PATH])
        assert entry.path == RUNBOOK_PATH
        assert entry.front == RUNBOOK
        assert entry.length == len(RUNBOOK_BODY)
        assert entry.sections == len(sections(RUNBOOK_BODY))
        bounds = reader.bounds(RUNBOOK_PATH)
        assert bounds == [
            (section.start, section.start + len(section.text)) for section in sections(RUNBOOK_BODY)
        ]
        assert reader.text(RUNBOOK_PATH, 0, len(RUNBOOK_BODY)) == RUNBOOK_BODY
        assert reader.text(RUNBOOK_PATH, *bounds[1]) == "## Restore\n\nRestore the ledger.\n"
        assert reader.text(RUNBOOK_PATH, 3, 11) == RUNBOOK_BODY[3:11]
        assert reader.heading(RUNBOOK_PATH, 2) == "Restore"
        assert reader.heading(RUNBOOK_PATH, 1) == ""  # its title again
        assert reader.heading(RUNBOOK_PATH, 3) == ""


def test_a_document_is_found_by_its_key_or_id(written: Written) -> None:
    """An issue by its key, a page by its id; an issue's id is never looked up."""
    with written(BOTH).reading() as reader:
        assert [each.path for each in reader.entries(keys=["PROJ-7"])] == [UPGRADE_PATH]
        assert [each.path for each in reader.entries(ids=["1001"])] == [RUNBOOK_PATH]
        assert reader.entries(ids=[UPGRADE.id]) == []
        assert reader.entries(paths=["jira/PROJ/PROJ-8.md"]) == []


def test_the_passage_is_the_section_that_best_matches(written: Written) -> None:
    """By its heading and body, with a snippet of its body; a title alone gives the first."""
    with written(BOTH).reading() as reader:
        passage = reader.passage(RUNBOOK_PATH, quote("ledger"))
        assert passage is not None
        assert (passage.number, passage.heading) == (2, "Restore")
        assert "ledger" in passage.snippet
        titled = reader.passage(RUNBOOK_PATH, quote("runbook"))
        assert titled is not None
        assert titled.number == 1
        assert reader.passage(RUNBOOK_PATH, quote("absent")) is None


def test_the_documents_are_listed_and_counted(written: Written) -> None:
    """By path, or newest first by a page of them; each value counted, the most used first."""
    with written(BOTH).reading() as reader:
        paths = sorted([RUNBOOK_PATH, UPGRADE_PATH])
        assert [each.path for each in reader.listing(Filters())] == paths
        total, newest = reader.recent(Filters(), "updated", 0, 1)
        assert total == len(BOTH)
        assert [each.path for each in newest] == [RUNBOOK_PATH]
        total, older = reader.recent(Filters(), "updated", 1, 1)
        assert total == len(BOTH)
        assert [each.path for each in older] == [UPGRADE_PATH]
        # Created at one moment, so by the newest update.
        assert [each.path for each in reader.recent(Filters(), "created", 0, 1)[1]] == [
            RUNBOOK_PATH
        ]
        assert reader.values("space") == [("ENG", 1)]
        assert reader.values("project") == [("PROJ", 1)]
        assert reader.values("label") == [("ops", 1)]
        assert reader.values("source") == [("confluence", 1), ("jira", 1)]


def test_the_summary_says_what_the_index_holds(written: Written) -> None:
    """Its documents by type, space and project, its sections, and when it was built."""
    with written(BOTH).reading() as reader:
        summary = reader.summary()
        assert reader.built_at() == MOMENT
        assert reader.build()
    assert summary.built_at == MOMENT
    assert summary.types == {"page": 1, "issue": 1}
    assert summary.spaces == {"ENG": 1}
    assert summary.projects == {"PROJ": 1}
    assert summary.sections == len(sections(RUNBOOK_BODY)) + len(sections(UPGRADE_BODY))
    assert summary.newest_fetch == MOMENT
    assert summary.people.count == 1  # one author of both
    assert (summary.model, summary.pieces, summary.chunking) == (None, 0, None)


ACCOUNT = "acct-0001"
ADA = "Ada Example"
BO = "Bo Sample"
COMMENTED = MOMENT - timedelta(days=4)
# Two documents alike in words and vector, unlike in all that a filter reads.
INSIDE = page(
    "1001",
    "Alike",
    space="OPS",
    status="archived",
    labels=("kept",),
    created=MOMENT - timedelta(days=9),
    updated=MOMENT - timedelta(days=2),
    people=(
        PersonRole(role="author", name=ADA, account=ACCOUNT),
        PersonRole(role="creator", name=ADA, account=ACCOUNT),
        PersonRole(role="assignee", name=ADA, account=ACCOUNT),
        PersonRole(
            role="commenter",
            name=ADA,
            account=ACCOUNT,
            at=(COMMENTED, COMMENTED + timedelta(hours=1)),
        ),
    ),
)
OUTSIDE = issue(
    "PROJ-8",
    "Alike",
    status="Done",
    issue_type="Bug",
    created=MOMENT,
    updated=MOMENT,
    people=(PersonRole(role="commenter", name=BO, at=(COMMENTED - timedelta(days=1),)),),
)
ALIKE_BODY = "# Alike\n\nThe same words here.\n"
SAME_PIECE = (piece_of(ALIKE_BODY, "same words", "k", NORTH),)
ALIKE = tuple(
    Document(front=front, body=ALIKE_BODY, pieces=SAME_PIECE) for front in (INSIDE, OUTSIDE)
)
# The one role that goes alone, on a meeting of the same words, by her name alone.
MEETING = replace(
    worklog_document("meeting", "m-20261020-review", "Alike", (ADA,)),
    updated=MOMENT - timedelta(days=1),
)
ATTENDED = (*ALIKE, Document(front=MEETING, body=ALIKE_BODY, pieces=SAME_PIECE))


@pytest.mark.parametrize(
    ("filters", "front"),
    [
        (Filters(source="confluence"), INSIDE),
        (Filters(source="jira"), OUTSIDE),
        (Filters(space="OPS"), INSIDE),
        (Filters(project="PROJ"), OUTSIDE),
        (Filters(status="archived"), INSIDE),
        (Filters(label="kept"), INSIDE),
        (Filters(issue_type="Bug"), OUTSIDE),
        (Filters(updated_after=MOMENT), OUTSIDE),
        (Filters(updated_before=MOMENT), INSIDE),
        (Filters(created_after=MOMENT), OUTSIDE),
        (Filters(created_before=MOMENT), INSIDE),
        (Filters(commented_after=COMMENTED), INSIDE),
        (Filters(commented_before=COMMENTED), OUTSIDE),
    ],
)
def test_filters_narrow_words_and_vectors_alike(
    written: Written, filters: Filters, front: FrontMatter
) -> None:
    """Whichever way a document is sought, a filter leaves it or takes it out; an edge counts."""
    path = location(front)
    with written(ALIKE, EMBEDDED).reading() as reader:
        assert list(reader.scores(quote("words"), filters)[0]) == [path]
        assert list(reader.nearest(query(NORTH), filters, 10)) == [path]
        assert [each.path for each in reader.listing(filters)] == [path]
        assert reader.recent(filters, "updated", 0, 10)[0] == 1
        both = [location(INSIDE), location(OUTSIDE)]
        assert [each.path for each in reader.entries(paths=both, filters=filters)] == [path]


@pytest.mark.parametrize(
    ("role", "fronts"),
    [
        ("person", (INSIDE, MEETING)),
        ("author", (INSIDE,)),
        ("creator", (INSIDE,)),
        ("assignee", (INSIDE,)),
        ("commenter", (INSIDE,)),
        ("participant", (MEETING,)),
    ],
)
def test_a_person_narrows_words_and_vectors_alike(
    written: Written, role: str, fronts: tuple[FrontMatter, ...]
) -> None:
    """By the id of the person, in any role or in the one that the filter names."""
    paths = {location(front) for front in fronts}
    with written(ATTENDED, EMBEDDED).reading() as reader:
        (ada,) = reader.persons(people.name_key(ADA))
        hers = Filters(**{role: ada})
        assert set(reader.scores(quote("words"), hers)[0]) == paths
        assert set(reader.nearest(query(NORTH), hers, 10)) == paths


def test_a_person_in_another_role_narrows_to_nothing(written: Written) -> None:
    """A commenter alone is found as one, and as no author."""
    with written(ALIKE, EMBEDDED).reading() as reader:
        (bo,) = reader.persons(people.name_key(BO))
        assert list(reader.scores(quote("words"), Filters(commenter=bo))[0]) == [location(OUTSIDE)]
        assert reader.scores(quote("words"), Filters(author=bo))[0] == {}
        assert reader.nearest(query(NORTH), Filters(author=bo), 10) == {}


def test_a_person_is_read_back(written: Written) -> None:
    """By a name's key, how it joined, their documents by role and source, their last update."""
    with written(ATTENDED).reading() as reader:
        key = people.name_key(ADA)
        (ada,) = reader.persons(key)
        assert reader.persons(key, people.ACCOUNT) == [ada]
        assert reader.persons(key, people.NAME) == [ada]  # the meeting's, by her name alone
        assert reader.persons("nobody") == []
        activity = reader.person(ada)
        assert activity is not None
        assert activity.person.name == ADA
        assert activity.roles == dict.fromkeys(
            ("assignee", "author", "commenter", "creator", "participant"), 1
        )
        assert activity.sources == {"confluence": 1, "worklog": 1}
        assert activity.last == MEETING.updated
        assert reader.person("p-nobody") is None
        rows = reader.roles(ada, [location(INSIDE)])[location(INSIDE)]
        held = {role: (count, last) for role, count, last in rows}
        assert held["author"] == (1, None)
        assert held["commenter"] == (2, COMMENTED + timedelta(hours=1))
        assert reader.roles(ada, [location(OUTSIDE)]) == {}


NEAR_BODY = (
    "# Compass\n\nnorth text\n\n## Turning\n\neast text\n\nmore words\n\n## Rising\n\nup text\n"
)


def test_nearest_gives_a_document_its_best_piece(written: Written) -> None:
    """Its score is that piece's cosine; its section and its span in the body say where."""
    compass = page("2001", "Compass")
    pieces = (
        piece_of(NEAR_BODY, "north text", "k-north", NORTH),
        piece_of(NEAR_BODY, "east text", "k-east", EAST),
        piece_of(NEAR_BODY, "more words", "k-more", NORTHISH),
        piece_of(NEAR_BODY, "up text", "k-up", UP),
    )
    path = location(compass)
    index = written([Document(front=compass, body=NEAR_BODY, pieces=pieces)], EMBEDDED)
    with index.reading() as reader:
        found = reader.nearest(query(EAST), Filters(), 10)
        assert list(found) == [path]
        score, number, start, end = found[path]
        assert score.relevance == pytest.approx(1.0, abs=EPSILON)
        assert score.updated == compass.updated
        assert (number, reader.text(path, start, end)) == (2, "east text")
        _, number, start, end = reader.nearest(query(UP), Filters(), 10)[path]
        assert (number, reader.text(path, start, end)) == (3, "up text")


def test_nearest_orders_documents_and_cuts_at_its_depth(
    written: Written,
) -> None:
    """The nearest first, each as near as its best piece; the rest cut at the depth."""
    fronts = [page("2001", "Near"), page("2002", "Less"), page("2003", "Far")]
    body = "# Same\n\nthe text\n"
    documents = [
        Document(front=front, body=body, pieces=(piece_of(body, "the text", key, vector),))
        for front, key, vector in zip(
            fronts, ("k1", "k2", "k3"), (NORTH, NORTHISH, EAST), strict=True
        )
    ]
    near, less, far = (location(front) for front in fronts)
    with written(documents, EMBEDDED).reading() as reader:
        found = reader.nearest(query(NORTH), Filters(), 10)
        assert list(found) == [near, less, far]
        assert found[less][0].relevance == pytest.approx(NORTHISH_COSINE, abs=EPSILON)
        assert list(reader.nearest(query(NORTH), Filters(), 2)) == [near, less]


def test_a_tie_by_meaning_goes_to_the_newest_then_the_path(
    written: Written,
) -> None:
    """Two documents of one text: the newest first, before the cut; then the path."""
    older = page("2001", "Older", updated=MOMENT - timedelta(days=1))
    newer = page("2002", "Newer")
    same = page("2003", "Same")
    body = "# Tied\n\nthe text\n"
    documents = [
        Document(front=front, body=body, pieces=(piece_of(body, "the text", "k", NORTH),))
        for front in (older, newer, same)
    ]
    with written(documents, EMBEDDED).reading() as reader:
        found = reader.nearest(query(NORTH), Filters(), 10)
        assert list(found) == [location(newer), location(same), location(older)]
        assert list(reader.nearest(query(NORTH), Filters(), 1)) == [location(newer)]


def test_nothing_is_near_in_an_index_without_pieces(written: Written) -> None:
    """A model named and no piece: no document, no key, and the model still named."""
    with written(BOTH, EMBEDDED).reading() as reader:
        assert reader.embedded() == EMBEDDED
        assert reader.nearest(query(NORTH), Filters(), 10) == {}
        assert reader.keys() == set()


def test_an_index_names_its_model_and_the_keys_of_its_pieces(
    written: Written,
) -> None:
    """Each key once, whatever pieces share it; the summary counts them with the model."""
    other = (piece_of(UPGRADE_BODY, "broker", "k-broker", EAST),)
    index = written((*ALIKE, Document(front=UPGRADE, body=UPGRADE_BODY, pieces=other)), EMBEDDED)
    with index.reading() as reader:
        assert reader.embedded() == EMBEDDED
        assert reader.keys() == {"k", "k-broker"}
        summary = reader.summary()
    assert (summary.model, summary.pieces, summary.chunking) == (EMBEDDED.model, 3, "sections")


def test_an_index_by_words_alone_names_no_model_and_no_keys(
    written: Written,
) -> None:
    """It cannot say which vectors it reads, so that a prune keeps them all."""
    with written(BOTH).reading() as reader:
        assert reader.embedded() is None
        with pytest.raises(UnavailableIndexError):
            reader.keys()


def test_a_backend_has_every_read_that_the_protocols_name(
    written: Written,
) -> None:
    """Each by the parameters declared, since a class satisfies a protocol by its methods."""

    def declared(method: Callable[..., object]) -> list[tuple[str, object, object]]:
        parameters = signature(method).parameters.values()
        return [(each.name, each.kind, each.default) for each in parameters if each.name != "self"]

    with written(BOTH).reading() as reader:
        for name in get_protocol_members(SearchReader):
            assert declared(getattr(reader, name)) == declared(getattr(SearchReader, name)), name
