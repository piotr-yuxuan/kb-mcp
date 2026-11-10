"""What any backend of the words and vector indexes must do, as plan 035 asks.

Each test holds a backend to the docstrings of ``search.domain.indexes``, through those
protocols alone, on made-up documents; a new backend joins ``BACKENDS``. Snapshots, all or
nothing, the lock and the rename are no part of it: they are SQLite's own, in
``test_index.py``, as other backends offer neither.
"""

from __future__ import annotations

import functools
import hashlib
from copy import replace
from datetime import timedelta
from inspect import signature
from typing import TYPE_CHECKING, get_protocol_members

import numpy as np
import pytest

from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import FrontMatter, PersonRole
from kb_mcp.search.adapters import sqlite_index
from kb_mcp.search.domain import people
from kb_mcp.search.domain.indexes import (
    Change,
    IndexedBody,
    Put,
    SearchReader,
    Skipped,
    UnavailableIndexError,
)
from kb_mcp.search.domain.search import WORDS, Chunk, Embedded, Filters, quote, sections
from tests.mirrors import MOMENT, issue, location, page, worklog_document

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

    from kb_mcp.kernel.chunking import Chunking
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


class FilledChunk(Record):
    """A chunk of a document to fill: its section's number, range, key and vector."""

    number: int
    start: int  # in the document's body
    end: int
    key: str
    vector: tuple[float, ...]


class FilledDocument(Record):
    """A document to write, with its chunks, if any."""

    front: FrontMatter
    body: str
    chunks: tuple[FilledChunk, ...] = ()


def digest(body: str) -> str:
    """Give the digest that a document's file has here: that of its body."""
    return hashlib.sha256(body.encode()).hexdigest()


def put_of(document: FilledDocument) -> Put:
    """Give a document as an update puts it, its file named as the data layout names it."""
    return Put(
        path=location(document.front),
        digest=digest(document.body),
        front=document.front,
        sections=tuple(sections(document.body)),
    )


def change(
    *,
    put: Sequence[FilledDocument] = (),
    removed: Sequence[str] = (),
    skipped: Sequence[Skipped] = (),
    whole: bool = False,
) -> Change:
    """Give a change of these documents put, these paths removed and files skipped."""
    return Change(
        removed=frozenset(removed),
        put=tuple(put_of(document) for document in put),
        skipped=tuple(skipped),
        aliases={},
        built_at=MOMENT,
        whole=whole,
    )


def filled(documents: Sequence[FilledDocument]) -> dict[Chunk, NDArray[np.float32]]:
    """Give the documents' parts as a fill takes them: each chunk, by path, with its vector."""
    return {
        Chunk(
            path=location(document.front),
            number=part.number,
            start=part.start,
            end=part.end,
            vector_key=part.key,
        ): np.array(part.vector, dtype=np.float32)
        for document in documents
        for part in document.chunks
    }


def sqlite(
    folder: Path, documents: Sequence[FilledDocument], embedded: Embedded | None = None
) -> SearchIndex:
    """Write the documents into a new SQLite index by a whole update; then fill their chunks."""
    index = sqlite_index.SqliteIndex(folder / "index.sqlite")
    done = index.update(change(put=documents, whole=True), None)
    assert done is not None
    if embedded is not None:
        assert index.fill(done.build, embedded, filled(documents), ())
    return index


BACKENDS = {"sqlite": sqlite}


@pytest.fixture(params=BACKENDS)
def written(request: pytest.FixtureRequest, tmp_path: Path) -> Written:
    """Give what writes documents into a new index, of each backend in turn."""
    return functools.partial(BACKENDS[request.param], tmp_path)


def chunk_of(body: str, text: str, key: str, vector: tuple[float, ...]) -> FilledChunk:
    """Name the chunk holding ``text``, by where the first section holding it has it."""
    section = next(each for each in sections(body) if text in each.body)
    start = section.body_start + section.body.index(text)
    return FilledChunk(
        number=section.number, start=start, end=start + len(text), key=key, vector=vector
    )


def query(vector: tuple[float, ...]) -> NDArray[np.float32]:
    """Give a vector as a query's embedding comes."""
    return np.array(vector, dtype=np.float32)


RUNBOOK = page("1001", "Rollback runbook", labels=("ops",), breadcrumb=("Guides",))
RUNBOOK_BODY = "# Rollback runbook\n\nWhy we restore.\n\n## Restore\n\nRestore the ledger.\n"
RUNBOOK_PATH = location(RUNBOOK)
UPGRADE = issue("PROJ-7", "Kafka upgrade", updated=MOMENT - timedelta(days=1))
UPGRADE_BODY = "# Kafka upgrade\n\nThe broker moves on.\n"
UPGRADE_PATH = location(UPGRADE)
BOTH = (
    FilledDocument(front=RUNBOOK, body=RUNBOOK_BODY),
    FilledDocument(front=UPGRADE, body=UPGRADE_BODY),
)


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
            FilledDocument(front=more, body="# Dense\n\nbroker broker broker\n"),
            FilledDocument(front=less, body=f"# Sparse\n\nbroker {'filler ' * 40}\n"),
        ]
    )
    with index.reading() as reader:
        found, _ = reader.scores(quote("broker"), Filters())
    assert found[location(more)].relevance > found[location(less)].relevance


def test_a_document_is_read_back(written: Written) -> None:
    """Its front matter, length and sections come back, its text by any span of its body."""
    with written(BOTH).reading() as reader:
        (entry,) = reader.indexed_documents(paths=[RUNBOOK_PATH])
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
        assert [each.path for each in reader.indexed_documents(keys=["PROJ-7"])] == [UPGRADE_PATH]
        assert [each.path for each in reader.indexed_documents(ids=["1001"])] == [RUNBOOK_PATH]
        assert reader.indexed_documents(ids=[UPGRADE.id]) == []
        assert reader.indexed_documents(paths=["jira/PROJ/PROJ-8.md"]) == []


def test_documents_found_come_by_path_whatever_order_they_were_written_in(
    written: Written,
) -> None:
    """Of two documents of one key, the first by path comes first, as the tools take it."""
    other = page("1002", "Another upgrade", key=UPGRADE.key)
    index = written(
        [FilledDocument(front=UPGRADE, body=UPGRADE_BODY), FilledDocument(front=other, body="")]
    )
    with index.reading() as reader:
        found = [each.path for each in reader.indexed_documents(keys=["PROJ-7"])]
    assert found == sorted((location(other), UPGRADE_PATH))


def test_the_passage_is_the_section_that_best_matches(written: Written) -> None:
    """By its heading and body, with a snippet of its body; a title alone gives the first."""
    with written(BOTH).reading() as reader:
        passage = reader.snippet(RUNBOOK_PATH, quote("ledger"))
        assert passage is not None
        assert (passage.number, passage.heading) == (2, "Restore")
        assert "ledger" in passage.text
        titled = reader.snippet(RUNBOOK_PATH, quote("runbook"))
        assert titled is not None
        assert titled.number == 1
        assert reader.snippet(RUNBOOK_PATH, quote("absent")) is None


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
        summary = reader.index_status()
        assert reader.built_at() == MOMENT
        assert reader.build()
    assert summary.built_at == MOMENT
    assert summary.types == {"page": 1, "issue": 1}
    assert summary.spaces == {"ENG": 1}
    assert summary.projects == {"PROJ": 1}
    assert summary.sections == len(sections(RUNBOOK_BODY)) + len(sections(UPGRADE_BODY))
    assert summary.newest_fetch == MOMENT
    assert summary.people.count == 1  # one author of both
    assert (summary.model, summary.chunks, summary.chunking) == (None, 0, None)


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
SAME_CHUNK = (chunk_of(ALIKE_BODY, "same words", "k", NORTH),)
ALIKE = tuple(
    FilledDocument(front=front, body=ALIKE_BODY, chunks=SAME_CHUNK) for front in (INSIDE, OUTSIDE)
)
# The one role that goes alone, on a meeting of the same words, by her name alone.
MEETING = replace(
    worklog_document("meeting", "m-20261020-review", "Alike", (ADA,)),
    updated=MOMENT - timedelta(days=1),
)
ATTENDED = (*ALIKE, FilledDocument(front=MEETING, body=ALIKE_BODY, chunks=SAME_CHUNK))


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
        assert [each.path for each in reader.indexed_documents(paths=both, filters=filters)] == [
            path
        ]


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
        assert reader.persons(key, people.BY_ACCOUNT) == [ada]
        assert reader.persons(key, people.BY_NAME) == [ada]  # the meeting's, by her name alone
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


def test_nearest_gives_a_document_its_best_chunk(written: Written) -> None:
    """Its score is that chunk's cosine; its section and its span in the body say where."""
    compass = page("2001", "Compass")
    chunks = (
        chunk_of(NEAR_BODY, "north text", "k-north", NORTH),
        chunk_of(NEAR_BODY, "east text", "k-east", EAST),
        chunk_of(NEAR_BODY, "more words", "k-more", NORTHISH),
        chunk_of(NEAR_BODY, "up text", "k-up", UP),
    )
    path = location(compass)
    index = written([FilledDocument(front=compass, body=NEAR_BODY, chunks=chunks)], EMBEDDED)
    with index.reading() as reader:
        found = reader.nearest(query(EAST), Filters(), 10)
        assert list(found) == [path]
        score, chunk = found[path]
        assert score.relevance == pytest.approx(1.0, abs=EPSILON)
        assert score.updated == compass.updated
        assert (chunk.number, reader.text(path, chunk.start, chunk.end)) == (2, "east text")
        _, chunk = reader.nearest(query(UP), Filters(), 10)[path]
        assert (chunk.number, reader.text(path, chunk.start, chunk.end)) == (3, "up text")


def test_of_a_document_s_tied_chunks_the_first_in_its_body_is_its_best(written: Written) -> None:
    """By section number, then start, whatever order the chunks were written in."""
    compass = page("2001", "Compass")
    chunks = tuple(
        chunk_of(NEAR_BODY, text, f"k-{text}", NORTH)
        for text in ("up text", "more words", "east text")
    )
    path = location(compass)
    index = written([FilledDocument(front=compass, body=NEAR_BODY, chunks=chunks)], EMBEDDED)
    with index.reading() as reader:
        _, chunk = reader.nearest(query(NORTH), Filters(), 10)[path]
        assert (chunk.number, reader.text(path, chunk.start, chunk.end)) == (2, "east text")


def test_nearest_orders_documents_and_cuts_at_its_depth(
    written: Written,
) -> None:
    """The nearest first, each as near as its best chunk; the rest cut at the depth."""
    fronts = [page("2001", "Near"), page("2002", "Less"), page("2003", "Far")]
    body = "# Same\n\nthe text\n"
    documents = [
        FilledDocument(front=front, body=body, chunks=(chunk_of(body, "the text", key, vector),))
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
        FilledDocument(front=front, body=body, chunks=(chunk_of(body, "the text", "k", NORTH),))
        for front in (older, newer, same)
    ]
    with written(documents, EMBEDDED).reading() as reader:
        found = reader.nearest(query(NORTH), Filters(), 10)
        assert list(found) == [location(newer), location(same), location(older)]
        assert list(reader.nearest(query(NORTH), Filters(), 1)) == [location(newer)]


def test_nothing_is_near_in_an_index_without_chunks(written: Written) -> None:
    """A model named and no chunk: no document, no key, and the model still named."""
    with written(BOTH, EMBEDDED).reading() as reader:
        assert reader.embedded() == EMBEDDED
        assert reader.nearest(query(NORTH), Filters(), 10) == {}
        assert reader.keys() == set()


def test_an_index_names_its_model_and_the_keys_of_its_chunks(
    written: Written,
) -> None:
    """Each key once, whatever chunks share it; the summary counts them with the model."""
    other = (chunk_of(UPGRADE_BODY, "broker", "k-broker", EAST),)
    index = written(
        (*ALIKE, FilledDocument(front=UPGRADE, body=UPGRADE_BODY, chunks=other)), EMBEDDED
    )
    with index.reading() as reader:
        assert reader.embedded() == EMBEDDED
        assert reader.keys() == {"k", "k-broker"}
        summary = reader.index_status()
    assert (summary.model, summary.chunks, summary.chunking) == (EMBEDDED.model, 3, "sections")


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


def build_of(index: SearchIndex) -> str:
    """Name the build that the index holds now."""
    with index.reading() as reader:
        return reader.build()


EDITED = replace(RUNBOOK, labels=("ops", "revert"))
EDITED_BODY = "# Rollback runbook\n\nWhy we revert.\n"


def test_a_document_put_again_is_replaced(written: Written) -> None:
    """Its new words find it, its old ones nothing; it reads back as put, the other as it was."""
    index = written(BOTH)
    build = build_of(index)
    done = index.update(change(put=[FilledDocument(front=EDITED, body=EDITED_BODY)]), build)
    assert done is not None
    assert (done.copied, done.added, done.replaced, done.removed) == (1, 0, 1, 0)
    with index.reading() as reader:
        assert reader.build() == done.build != build
        assert reader.scores(quote("ledger"), Filters()) == ({}, True)
        assert list(reader.scores(quote("revert"), Filters())[0]) == [RUNBOOK_PATH]
        (entry,) = reader.indexed_documents(paths=[RUNBOOK_PATH])
        assert entry.front == EDITED
        assert reader.text(RUNBOOK_PATH, 0, len(EDITED_BODY)) == EDITED_BODY
        assert reader.values("label") == [("ops", 1), ("revert", 1)]
        assert list(reader.scores(quote("broker"), Filters())[0]) == [UPGRADE_PATH]
        assert reader.held().documents[RUNBOOK_PATH] == digest(EDITED_BODY)


LONE = page(
    "1003",
    "Lone page",
    space="OPS",
    labels=("alone",),
    people=(PersonRole(role="author", name=BO),),
)
LONE_BODY = "# Lone page\n\nA solitary word.\n"


def test_a_document_removed_leaves_no_trace(written: Written) -> None:
    """In ranking, entries, the listing, values, persons, the summary and what is held."""
    index = written([*BOTH, FilledDocument(front=LONE, body=LONE_BODY)])
    path = location(LONE)
    done = index.update(change(removed=[path]), build_of(index))
    assert done is not None
    assert (done.copied, done.added, done.replaced, done.removed) == (2, 0, 0, 1)
    assert done.types == {"page": 1, "issue": 1}
    with index.reading() as reader:
        assert reader.scores(quote("solitary"), Filters(), every=True) == ({}, True)
        assert reader.snippet(path, quote("solitary")) is None
        assert reader.indexed_documents(paths=[path], ids=[LONE.id]) == []
        assert [each.path for each in reader.listing(Filters())] == sorted(
            [RUNBOOK_PATH, UPGRADE_PATH]
        )
        assert reader.recent(Filters(), "updated", 0, 10)[0] == len(BOTH)
        assert reader.values("space") == [("ENG", 1)]
        assert ("alone", 1) not in reader.values("label")
        assert reader.values("author") == [("A Person", 2)]
        assert reader.persons(people.name_key(BO)) == []
        summary = reader.index_status()
        assert summary.types == {"page": 1, "issue": 1}
        assert summary.sections == len(sections(RUNBOOK_BODY)) + len(sections(UPGRADE_BODY))
        assert summary.spaces == {"ENG": 1}
        assert path not in reader.held().documents


def test_held_gives_each_document_s_digest_and_each_file_skipped(written: Written) -> None:
    """With what wrote the index: its build, the code's cut and the meaning of no alias file."""
    index = written(BOTH)
    with index.reading() as reader:
        held = reader.held()
        assert held.build == reader.build()
    assert held.documents == {
        RUNBOOK_PATH: digest(RUNBOOK_BODY),
        UPGRADE_PATH: digest(UPGRADE_BODY),
    }
    assert held.skipped == {}
    assert (held.words, held.aliases) == (WORDS, people.aliases_digest({}))
    refused = Skipped(path="confluence/ENG/1-broken.md", digest="d1", reason="no front matter")
    unread = Skipped(path="confluence/ENG/2-unread.md", digest=None, reason="not readable")
    done = index.update(change(skipped=[unread, refused]), held.build)
    assert done is not None
    assert done.skipped == (refused, unread)
    with index.reading() as reader:
        assert reader.held().skipped == {refused.path: refused, unread.path: unread}
        assert reader.index_status().skipped == len(done.skipped)
    done = index.update(change(), done.build)
    assert done is not None
    assert done.skipped == ()


def test_an_update_of_a_build_no_longer_held_changes_nothing(written: Written) -> None:
    """It gives None, as another run wrote the index meanwhile; a whole update checks nothing."""
    index = written(BOTH)
    build = build_of(index)
    assert index.update(change(removed=[RUNBOOK_PATH]), "another build") is None
    with index.reading() as reader:
        assert reader.build() == build
        assert len(reader.listing(Filters())) == len(BOTH)
    done = index.update(change(put=[BOTH[0]], whole=True), "another build")
    assert done is not None
    assert (done.copied, done.added, done.replaced, done.removed) == (0, 1, 0, 0)
    with index.reading() as reader:
        assert [each.path for each in reader.listing(Filters())] == [RUNBOOK_PATH]


def test_of_two_files_of_one_source_and_id_the_first_by_its_path_s_parts_is_held(
    written: Written,
) -> None:
    """Put after the one held by path, a file is skipped; put before, it takes its place.

    By the parts of each path, not its text: ``1000/1.md`` comes before ``1000-1.md``.
    """
    index = written(BOTH)
    later = replace(
        put_of(FilledDocument(front=EDITED, body=EDITED_BODY)), path="confluence/ENG/1001-zzz.md"
    )
    done = index.update(replace(change(), put=(later,)), build_of(index))
    assert done is not None
    assert [(each.path, each.digest) for each in done.skipped] == [(later.path, later.digest)]
    assert (done.copied, done.added, done.replaced, done.removed) == (2, 0, 0, 0)
    nested = replace(later, path="confluence/ENG/1000/1.md")
    flat = replace(later, path="confluence/ENG/1000-1.md")
    done = index.update(replace(change(), put=(flat, nested)), done.build)
    assert done is not None
    assert [(each.path, each.digest) for each in done.skipped] == sorted(
        [(RUNBOOK_PATH, digest(RUNBOOK_BODY)), (flat.path, flat.digest)]
    )
    assert (done.copied, done.added, done.replaced, done.removed) == (1, 1, 0, 1)
    with index.reading() as reader:
        (entry,) = reader.indexed_documents(ids=[RUNBOOK.id])
        assert entry.path == nested.path
        assert reader.held().documents.keys() == {nested.path, UPGRADE_PATH}


def test_a_document_replaced_or_removed_takes_its_chunks_with_it(written: Written) -> None:
    """Search by meaning no longer finds it, nor names its keys; the other keeps its own."""
    other = (chunk_of(UPGRADE_BODY, "broker", "k-broker", EAST),)
    index = written(
        (*ALIKE, FilledDocument(front=UPGRADE, body=UPGRADE_BODY, chunks=other)), EMBEDDED
    )
    replaced = FilledDocument(front=INSIDE, body="# Alike\n\nOther words now.\n")
    done = index.update(change(put=[replaced], removed=[location(OUTSIDE)]), build_of(index))
    assert done is not None
    assert done.awaiting == 1
    with index.reading() as reader:
        assert reader.embedded() == EMBEDDED
        assert list(reader.nearest(query(NORTH), Filters(), 10)) == [UPGRADE_PATH]
        assert reader.keys() == {"k-broker"}
        summary = reader.index_status()
    assert (summary.chunks, summary.awaiting) == (1, 1)


SAM = "Sam Sample"
SYNC = worklog_document("meeting", "m-20261020-sync", "Sync", (SAM,))
SYNC_PATH = location(SYNC)


def sam_of(account: str, key: str) -> FilledDocument:
    """Give an issue authored by an account of Sam Sample's name."""
    front = issue(
        key, f"Issue {key}", people=(PersonRole(role="author", name=SAM, account=account),)
    )
    return FilledDocument(front=front, body=f"# Issue {key}\n")


def test_a_person_s_rows_follow_an_account_put_or_removed_in_another_document(
    written: Written,
) -> None:
    """A meeting's name alone joins the one account of its name; with two, neither, said.

    The meeting's file is never put again: each update joins every document whole.
    """
    index = written([FilledDocument(front=SYNC, body="# Sync\n")])
    key = people.name_key(SAM)

    def participant() -> list[str]:
        with index.reading() as reader:
            return [each for each in reader.persons(key) if reader.roles(each, [SYNC_PATH])]

    (alone,) = participant()
    first, second = sam_of("acct-0002", "PROJ-2"), sam_of("acct-0003", "PROJ-3")
    done = index.update(change(put=[first]), build_of(index))
    assert done is not None
    assert done.persons.ambiguous == ()
    (joined,) = participant()
    with index.reading() as reader:
        assert reader.persons(key) == reader.persons(key, people.BY_ACCOUNT) == [joined]
    done = index.update(change(put=[second]), done.build)
    assert done is not None
    assert [each.name for each in done.persons.ambiguous] == [SAM]
    assert participant() == [alone]
    done = index.update(change(removed=[location(second.front)]), done.build)
    assert done is not None
    assert participant() == [joined]
    done = index.update(change(removed=[location(first.front)]), done.build)
    assert done is not None
    assert participant() == [alone]


def test_documents_come_back_with_their_front_matter_and_body(written: Written) -> None:
    """Each as put, by path: its body exactly, as its sections' heading lines and bodies give it."""
    with written(BOTH).reading() as reader:
        assert reader.documents() == [
            IndexedBody(path=RUNBOOK_PATH, front=RUNBOOK, body=RUNBOOK_BODY),
            IndexedBody(path=UPGRADE_PATH, front=UPGRADE, body=UPGRADE_BODY),
        ]


COMPASS = page("2001", "Compass")
COMPASS_PATH = location(COMPASS)
NORTHERN = chunk_of(NEAR_BODY, "north text", "k-north", NORTH)
EASTERN = chunk_of(NEAR_BODY, "east text", "k-east", EAST)


def test_a_fill_adds_and_removes_chunks_and_names_the_model(written: Written) -> None:
    """Search by meaning finds what it added, not what it removed; ``chunks`` and ``keys`` too.

    A fill of a build no longer held gives None and changes nothing.
    """
    index = written([FilledDocument(front=COMPASS, body=NEAR_BODY)])
    build = build_of(index)
    north, east = filled(
        [FilledDocument(front=COMPASS, body=NEAR_BODY, chunks=(NORTHERN, EASTERN))]
    ).items()
    done = index.fill(build, EMBEDDED, dict([north, east]), ())
    assert done is not None
    assert done != build
    with index.reading() as reader:
        assert reader.embedded() == EMBEDDED
        assert reader.chunks() == [north[0], east[0]]
        assert reader.keys() == {"k-north", "k-east"}
        assert list(reader.nearest(query(EAST), Filters(), 10)) == [COMPASS_PATH]
    assert index.fill(build, EMBEDDED, {}, [north[0]]) is None
    other = replace(EMBEDDED, chunking="windows")
    after = index.fill(done, other, {}, [north[0]])
    assert after is not None
    with index.reading() as reader:
        assert reader.build() == after
        assert reader.embedded() == other
        assert reader.chunks() == [east[0]]
        assert reader.keys() == {"k-east"}
        _, chunk = reader.nearest(query(NORTH), Filters(), 10)[COMPASS_PATH]
        assert (chunk.number, reader.text(COMPASS_PATH, chunk.start, chunk.end)) == (2, "east text")


def test_a_chunk_that_names_no_section_is_refused(written: Written) -> None:
    """A fill of a section that the document lacks raises, and leaves the index as it was."""
    index = written([FilledDocument(front=COMPASS, body=NEAR_BODY)])
    build = build_of(index)
    stray = Chunk(path=COMPASS_PATH, number=9, start=0, end=1, vector_key="k")
    with pytest.raises(ValueError, match="names a section"):
        index.fill(build, EMBEDDED, {stray: query(NORTH)}, ())
    with index.reading() as reader:
        assert (reader.build(), reader.embedded(), reader.chunks()) == (build, None, [])


def test_a_document_replaced_has_no_chunks_until_filled(written: Written) -> None:
    """Its chunks go with it; filled again, they come back, the other's as they were."""
    parts = (NORTHERN,)
    index = written(
        [
            FilledDocument(front=COMPASS, body=NEAR_BODY, chunks=parts),
            FilledDocument(
                front=UPGRADE,
                body=UPGRADE_BODY,
                chunks=(chunk_of(UPGRADE_BODY, "broker", "k-broker", EAST),),
            ),
        ],
        EMBEDDED,
    )
    with index.reading() as reader:
        held = reader.chunks()
    done = index.update(
        change(put=[FilledDocument(front=COMPASS, body=NEAR_BODY)]), build_of(index)
    )
    assert done is not None
    with index.reading() as reader:
        assert [chunk.path for chunk in reader.chunks()] == [UPGRADE_PATH]
        assert reader.keys() == {"k-broker"}
    again = filled([FilledDocument(front=COMPASS, body=NEAR_BODY, chunks=parts)])
    assert index.fill(done.build, EMBEDDED, again, ())
    with index.reading() as reader:
        assert reader.chunks() == held
        assert reader.keys() == {"k-north", "k-broker"}


BLANK = page("3001", "Blank")
TITLED = page("3002", "Titled")


@pytest.mark.parametrize(("chunking", "waiting"), [("sections", 1), ("windows", 2)])
def test_a_document_that_wants_no_chunk_never_awaits(
    written: Written, chunking: Chunking, waiting: int
) -> None:
    """Of the documents with no chunk, those that the chunking cuts some text from await.

    White space alone gives none; a title alone, none cut by sections, one by windows.
    Filled, the runbook awaits no more.
    """
    documents = [
        FilledDocument(front=BLANK, body="\n"),
        FilledDocument(front=TITLED, body="# Titled\n"),
        FilledDocument(front=RUNBOOK, body=RUNBOOK_BODY),
    ]
    index = written(documents, replace(EMBEDDED, chunking=chunking))
    with index.reading() as reader:
        assert reader.index_status().awaiting == waiting
        build = reader.build()
    parts = filled([replace(documents[2], chunks=(chunk_of(RUNBOOK_BODY, "ledger", "k", NORTH),))])
    done = index.fill(build, replace(EMBEDDED, chunking=chunking), parts, ())
    assert done is not None
    with index.reading() as reader:
        assert reader.index_status().awaiting == waiting - 1
    updated = index.update(change(put=[documents[2]]), done)
    assert updated is not None
    assert updated.awaiting == waiting
