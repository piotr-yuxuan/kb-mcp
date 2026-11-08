"""The words index and the vector index: only what search needs of a backend.

Types alone, with no effect. A class satisfies one of these protocols by having its
methods, without inheriting, as ``search.adapters.sqlite_index.SqliteIndex`` satisfies
them all; callers type against them, so that only where an index is made names its
backend. ``tests/test_index_contract.py`` holds every backend to these docstrings.

A use is opened once: ``reading()`` opens one and gives its reader, and no other method
opens one, so that all that a call reads comes through one reader. A search reads words
and vectors in one use, hence ``SearchIndex``, the two interfaces together, whose
reader reads both. ``Put`` and ``Skipped`` say what an index takes of each file of the
mirror; ``Held`` what it holds of them, ``Change`` what an update changes, all of it or
none, and ``Updated`` what that did.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import FrontMatter
from kb_mcp.search.domain.people import Outcome
from kb_mcp.search.domain.search import Section

if TYPE_CHECKING:
    from collections.abc import Iterable
    from contextlib import AbstractContextManager

    import numpy as np
    from numpy.typing import NDArray

    from kb_mcp.search.domain.search import (
        Activity,
        Embedded,
        Entry,
        Filters,
        Passage,
        Score,
        Sort,
        Summary,
    )


# Why an update keeps nothing of the index in place: none that this version reads, one
# written by another version of the cut (``search.WORDS``) or before it was recorded, one
# damaged, or the run's --rebuild.
type Whole = Literal["unavailable", "another version", "damaged", "--rebuild"]


class UnavailableIndexError(Exception):
    """No index to read, or one that this version cannot read; the message says why."""


class DamagedIndexError(UnavailableIndexError):
    """An index that this version reads, but one of whose tables cannot be read."""


class Put(Record):
    """A file of the mirror, read: the document that an index takes of it."""

    path: str  # relative to the mirror, which names the document
    digest: str  # the SHA-256 of the file's bytes
    front: FrontMatter
    sections: tuple[Section, ...]  # its body, as ``search.sections`` cuts it


class Skipped(Record):
    """A file of the mirror that an index could not take, and why."""

    path: str  # relative to the mirror
    digest: str | None  # the SHA-256 of its bytes; None for a file that could not be read
    reason: str  # holding nothing of the file's content


class Held(Record):
    """What a words index holds of the mirror's files: what an update compares them with."""

    build: str
    words: str | None  # the ``search.WORDS`` of the code that wrote it; None if unrecorded
    aliases: str | None  # what the alias file meant, as ``people.aliases_digest`` gives it
    documents: dict[str, str]  # each document's path, and its file's digest
    skipped: dict[str, Skipped]  # each file skipped, by path


class Change(Record):
    """What an update changes of a words index, all of it or none.

    The documents of ``removed`` go, those of ``put`` come, replacing any of their path,
    and the index holds no other skipped file than those of ``skipped`` and those that
    two of one source and id leave out. A ``whole`` update keeps nothing of the index in
    place. Persons are joined again over every document, through ``aliases``.
    """

    removed: frozenset[str]  # the paths of documents to remove
    put: tuple[Put, ...]
    skipped: tuple[Skipped, ...]
    aliases: dict[str, str]  # each alias's name and target, in the file's order
    built_at: datetime
    whole: bool = False


class Updated(Record):
    """What an update did, and what the index then holds.

    Of the documents of the index in place, each is ``copied``, ``replaced`` by one put
    of its path, or ``removed``; each other put is ``added``. ``skipped`` gives every
    file that the index lacks, a put whose source and id an earlier file by path holds
    among them, and a copied document so pushed out. ``awaiting`` counts the documents
    that hold a section but no piece, of an index that names a model, else None.
    """

    build: str
    copied: int
    added: int
    replaced: int
    removed: int
    types: dict[str, int]  # the documents held, by type
    sections: int
    awaiting: int | None
    skipped: tuple[Skipped, ...]
    persons: Outcome  # what the join left apart


class WordsReader(Protocol):
    """One use's reads of the documents: what the server and ranking ask.

    A document is named by its path. Its body is the text after its front matter, cut
    into sections as ``search.sections`` cuts it, numbered from 1. An expression is what
    ``search.quote`` writes, and a match such expressions joined with OR.
    """

    def scores(
        self, expression: str, filters: Filters, *, every: bool = False
    ) -> tuple[dict[str, Score], bool]:
        """Score each document passing the filters by its best section for one expression.

        Only the best documents are kept, unless ``every`` is asked; the flag says whether
        every document that matches is there.
        """

    def passage(self, path: str, match: str) -> Passage | None:
        """Find the section of a document that best matches, with a snippet of its body.

        Sections are judged by their heading and body alone: a match on the title alone
        gives the first section. None when the document does not match.
        """

    def entries(
        self,
        *,
        paths: Iterable[str] = (),
        keys: Iterable[str] = (),
        ids: Iterable[str] = (),
        filters: Filters | None = None,
    ) -> list[Entry]:
        """Find the documents of these paths, issue keys, and page or work-log ids, by path.

        An issue's id is never looked up, since a page may have the same.
        """

    def recent(
        self, filters: Filters, by: Sort, offset: int, limit: int
    ) -> tuple[int, list[Entry]]:
        """Count the documents that pass the filters, and list a page of them, newest first.

        Newest by created date, or else by update; ties go to the newest update, then the
        path.
        """

    def listing(self, filters: Filters) -> list[Entry]:
        """List every document that passes the filters, by path."""

    def bounds(self, path: str) -> list[tuple[int, int]]:
        """Give where each section of a document starts and ends in its body, in order."""

    def text(self, path: str, start: int, end: int) -> str:
        """Give the characters of a document's body from ``start`` to ``end``."""

    def heading(self, path: str, number: int) -> str:
        """Give the heading of a document's section; empty when it has no such section.

        Empty too for the first section's heading when it is the document's title.
        """

    def values(self, name: str) -> list[tuple[str, int]]:
        """Give each value that a filter or count can take, the most used first."""

    def persons(self, key: str, joined: str | None = None) -> list[str]:
        """Give the ids of the persons with a name of this key, as ``name_key`` gives it, sorted.

        ``joined``, if given, keeps the names that joined so, such as ``people.ACCOUNT``.
        """

    def person(self, person: str) -> Activity | None:
        """Give the person of this id, with their documents by role and by source; else None.

        Their spellings in the order that ``people.Person`` has them.
        """

    def roles(
        self, person: str, paths: Iterable[str]
    ) -> dict[str, list[tuple[str, int, datetime | None]]]:
        """Give a person's roles on each of these documents where they hold one, by path.

        Each role with the count of its rows, a commenter's being their comments, and the
        time of the last comment, None for any other role.
        """

    def summary(self) -> Summary:
        """Say what the index holds and when it was built."""

    def held(self) -> Held:
        """Say what the index holds of the mirror's files, by path, and what wrote it.

        Raises DamagedIndexError when a table of it cannot be read.
        """

    def built_at(self) -> datetime:
        """Say when the index was built."""

    def build(self) -> str:
        """Name this build of the index, unlike any other, even one of the same second."""


class VectorReader(Protocol):
    """One use's reads of the pieces and their vectors: what search by meaning asks."""

    def embedded(self) -> Embedded | None:
        """Name the model of the index's vectors, or None when it has no model."""

    def keys(self) -> set[str]:
        """Give the vector store's keys of the pieces' vectors: what the index reads of it.

        Raises UnavailableIndexError for an index that cannot say which vectors it reads,
        such as one with no model: a prune must then keep them all.
        """

    def nearest(
        self, vector: NDArray[np.float32], filters: Filters, depth: int
    ) -> dict[str, tuple[Score, int, int, int]]:
        """Give at most ``depth`` documents passing the filters, nearest a unit vector first.

        A document is as near as its best piece, of pieces tied the first by section
        number and start. Each path comes with its score, the cosine of that piece, then
        the piece's section number, and its start and end in the body. Ties go to the
        newest update, then the path, before the cut.
        """


class SearchReader(WordsReader, VectorReader, Protocol):
    """One use's reads of words and vectors together, as a search asks them."""


class WordsIndex(Protocol):
    """The documents of a mirror, by their words, and what they hold."""

    def reading(self) -> AbstractContextManager[WordsReader]:
        """Open one use, and give its reader.

        Raises UnavailableIndexError when there is no index, or one this version cannot
        read.
        """

    def update(self, change: Change, expected_build: str | None) -> Updated | None:
        """Change the index, all of it or none; give what it did, or None if it changed meanwhile.

        Unless the change is whole, the index must still be the build ``expected_build``
        read. A document replaced or removed takes its pieces with it; each copied keeps
        its own. Of two documents of one source and id, the first by the parts of its
        path is held, and the other skipped. Raises DamagedIndexError when a table of the
        index in place cannot be read, and TimeoutError when another run's change holds
        the index too long.
        """


class VectorIndex(Protocol):
    """The pieces of the words index's documents, by their vectors."""

    def reading(self) -> AbstractContextManager[VectorReader]:
        """Open one use, and give its reader.

        Raises UnavailableIndexError when there is no index, or one this version cannot
        read.
        """


class SearchIndex(WordsIndex, VectorIndex, Protocol):
    """The two interfaces together: what a search reads in one use."""

    def reading(self) -> AbstractContextManager[SearchReader]:
        """Open one use, and give the reader of both.

        Raises UnavailableIndexError when there is no index, or one this version cannot
        read.
        """
