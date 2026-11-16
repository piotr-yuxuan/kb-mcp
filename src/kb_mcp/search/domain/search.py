"""Search's pure rules, and what the index hands back.

How a query becomes expressions for the index, how a body is cut into sections, and in
which order a scope is browsed. Nothing here reads a file or the index:
``search.adapters.sqlite_index`` runs the expressions and returns these types.
"""

from __future__ import annotations

import re
import string
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import ConfigDict

from kb_mcp.kernel.chunking import Chunking
from kb_mcp.kernel.names import ISSUE_KEY
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import FrontMatter, document_id
from kb_mcp.search.domain.people import Person

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence


WORD = re.compile(r"[^\W_]+")
MAX_WORDS = 10
# How many words a query may have for its whole phrase to be scored too.
PHRASE_WORDS = range(2, 17)
# Function words of English and French, the languages of the corpus; elided French
# articles (l', d', qu') come out of the split as single letters. A word of both
# languages is listed once.
STOP_WORDS = frozenset(
    {
        # English
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        # French
        "au",
        "aux",
        "avec",
        "c",
        "ce",
        "ces",
        "cette",
        "comment",
        "d",
        "dans",
        "de",
        "des",
        "du",
        "elle",
        "elles",
        "en",
        "est",
        "et",
        "il",
        "ils",
        "j",
        "je",
        "l",
        "la",
        "le",
        "les",
        "leur",
        "leurs",
        "lui",
        "m",
        "ma",
        "mais",
        "mes",
        "mon",
        "n",
        "ne",
        "nos",
        "notre",
        "nous",
        "ou",
        "où",
        "par",
        "pas",
        "pour",
        "qu",
        "quand",
        "que",
        "quel",
        "quelle",
        "quelles",
        "quels",
        "qui",
        "quoi",
        "s",
        "sa",
        "se",
        "ses",
        "son",
        "sont",
        "sur",
        "t",
        "ta",
        "te",
        "tes",
        "ton",
        "tu",
        "un",
        "une",
        "vos",
        "votre",
        "vous",
        "y",
        "à",
    }
)
# An issue key in any case, not inside a longer word; the domain's rule then checks it.
KEY_IN_TEXT = re.compile(r"(?<![\w-])[A-Za-z][A-Za-z0-9_]*-[0-9]+(?![\w-])")
# The id in the address of a page or a blog post, as the site's address bar shows it.
ID_IN_ADDRESS = re.compile(r"(?:/pages/|[?&]pageId=|/blog/[0-9]{4}/[0-9]{2}/[0-9]{2}/)([0-9]+)")
HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
NUMBER = re.compile(r"([0-9]+)")
# The version of what a whole build writes from the same files: how ``sections`` cuts a
# body, how words are tokenized, a document's rows, how people are joined. It changes
# with any of them, as an update copies the rows of the build before, ``embed`` numbers
# its chunks by this code's cut, and a run with nothing changed keeps the old persons.
# ``tests/test_index.py`` pins what it writes, and names it in its failure.
WORDS = "1"
# Reciprocal rank fusion's constant: a document's share of a list is 1 / (FUSION + rank).
FUSION = 60
# How a search orders what it finds: by relevance, or by a date, newest first.
Sort = Literal["relevance", "updated", "created"]
# A document's place in its scope's tree: each node from the top down to the document,
# its title and, for a listed document, its path; empty for an ancestor not listed.
Place = tuple[tuple[str, str], ...]


class Identifiers(Record):
    """The issue keys and page ids that a text names, in its order."""

    keys: tuple[str, ...]
    ids: tuple[str, ...]


class Plan(Record):
    """What the index is asked for one query.

    Each expression is scored on its own, and a document's score is the sum of its best
    section's scores: one per word, then one for the whole phrase. ``match`` joins the
    words with OR, to find a document's best section. Every word is a quoted string, so
    nothing in a query is read as an operator.
    """

    words: tuple[str, ...]
    expressions: tuple[str, ...]
    match: str
    identifiers: Identifiers
    dropped: int  # words beyond MAX_WORDS, not searched


class Section(Record):
    """A part of a body: a heading line and the text up to the next one."""

    number: int  # 1 for the first
    heading: str  # the heading's words; empty for text before the first heading
    start: int  # the offset of its first character in the body
    head: str  # the heading line with its line break; empty before the first heading
    body: str

    @property
    def text(self) -> str:
        """Give the section as the body holds it."""
        return self.head + self.body

    @property
    def body_start(self) -> int:
        """Give the offset in the document's body where this section's body starts."""
        return self.start + len(self.head)


class Chunk(Record):
    """A chunk of a document that a vector stands for, as ``search.domain.chunking`` cuts it."""

    path: str  # the document's
    number: int  # the section holding its middle, numbered from 1
    start: int  # its range in the document's body
    end: int
    vector_key: str  # its vector's in the vector cache


class Matched(Record):
    """The chunk that placed a document by meaning: its section and its range in the body."""

    number: int  # the section holding its middle, numbered from 1
    start: int
    end: int


class Score(Record):
    """How well a document matches one expression, by its best section."""

    relevance: float  # higher is better
    updated: datetime
    created: datetime | None = None  # by words; a score by meaning has none


class Filters(Record):
    """What narrows a search, each value as the index holds it; None does not narrow.

    A scope, as ``space:ENG``, or by its key alone, in any scope type. A person, by their
    id: ``person`` in any role, each other in the role it names. The comment dates narrow
    by one comment: the commenter's, when one is given.
    """

    source: str | None = None
    scope: str | None = None
    status: str | None = None
    label: str | None = None
    subtype: str | None = None
    person: str | None = None
    author: str | None = None
    creator: str | None = None
    assignee: str | None = None
    commenter: str | None = None
    participant: str | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    commented_after: datetime | None = None
    commented_before: datetime | None = None


class IndexedDocument(Record):
    """A document as the index holds it, with the roles that its type takes, if declared.

    And its scope's as-of time, None when unknown.
    """

    path: str  # relative to <data>/docs, with /
    front: FrontMatter
    length: int  # characters of the body
    sections: int
    type_roles: tuple[str, ...] = ()
    as_of: datetime | None = None


class Passage(Record):
    """A section of a document, as a search shows it: its number, heading and snippet."""

    number: int
    heading: str
    text: str


class PersonCounts(Record):
    """The persons that an index joined, and the names that several identities hold."""

    count: int
    across: int  # persons with documents in more than one source
    alone: int  # persons by name alone, of no identity
    # Each name whose key the identities of two persons or more hold, as one of them writes
    # it, with the persons holding that key, the most first, ties by name.
    shared: tuple[tuple[str, int], ...]


class IndexStatus(Record):
    """What an index holds, and when it was built."""

    built_at: datetime
    skipped: int  # files of the mirror that could not be read
    types: dict[str, int]  # documents per type: page, blogpost, issue
    scopes: dict[str, int]  # documents per scope, as space:ENG
    as_of: dict[str, datetime]  # each scope's as-of time, where known
    sections: int
    persons: PersonCounts
    model: str | None = None  # the model of the vectors, if any
    chunks: int = 0
    chunking: Chunking | None = None  # how the chunks were cut, if there are vectors
    awaiting: int = 0  # documents that want a chunk by its chunking and hold none


class Activity(Record):
    """A person as the index holds them, with their documents by role and by source.

    A document counts once in a role, a commenter's however many their comments.
    """

    person: Person
    roles: dict[str, int]  # documents per role, the most first, ties by role
    sources: dict[str, int]  # documents per source, likewise
    last: datetime  # when the most recently updated of their documents was


class Embedded(Record):
    """The model that embedded an index's chunks, and how they were cut, as the index records it."""

    model: str
    fingerprint: str
    dimensions: int
    chunking: Chunking = "sections"


class ChunkVectors(Record):
    """Every chunk of an index with its unit vector: what a search by meaning looks through."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    # By identity, as before: an array has no truth value to compare by.
    __eq__ = object.__eq__
    __hash__ = object.__hash__

    # Columns beside the matrix, one row per chunk, rather than a record per chunk: a
    # serving process keeps them for every chunk of the index.
    documents: tuple[int, ...]  # each chunk's document, by rowid
    sections: tuple[int, ...]  # each chunk's section number
    starts: tuple[int, ...]  # where each chunk starts in its document's body
    ends: tuple[int, ...]  # where each chunk ends in its document's body
    matrix: NDArray[np.float32]  # one row per chunk
    paths: Mapping[int, str]  # each document's path, by rowid
    updated: Mapping[str, datetime]  # each document's update, by path

    def nearest(
        self, query: NDArray[np.float32], kept: Collection[int] | None, limit: int
    ) -> dict[str, tuple[Score, Matched]]:
        """Score the documents nearest a query by their best chunk, at most ``limit``.

        Only the documents in ``kept`` count, when it is given. Each path comes with its
        score, the cosine of its best chunk, and that chunk. Ties, as between documents
        of one text, go to the newest update, then the path, before the cut.
        """
        best: dict[str, int] = {}  # each document's best chunk, by its row
        similarity = self.matrix @ query.reshape(-1) if self.documents else np.empty(0)
        for index in np.argsort(-similarity, kind="stable"):
            document = self.documents[index]
            if kept is None or document in kept:
                best.setdefault(self.paths[document], int(index))
        chosen = sorted(
            best.items(),
            key=lambda item: (-similarity[item[1]], -self.updated[item[0]].timestamp(), item[0]),
        )[:limit]
        return {
            path: (
                Score(relevance=float(similarity[index]), updated=self.updated[path]),
                Matched(
                    number=self.sections[index], start=self.starts[index], end=self.ends[index]
                ),
            )
            for path, index in chosen
        }


def quote(text: str) -> str:
    """Make a text one FTS5 string: the index tokenises it, and reads no operator in it."""
    return '"' + text.replace('"', '""') + '"'


def identifiers(text: str) -> Identifiers:
    """Find the issue keys, in any case, and the page ids that a text names.

    A page id is a number standing alone between spaces, punctuation aside, or the id in
    a page's address; those of addresses come first.
    """
    keys = (key.upper() for key in KEY_IN_TEXT.findall(text))
    alone = (word.strip(string.punctuation) for word in text.split())
    ids = (
        *ID_IN_ADDRESS.findall(text),
        *(word for word in alone if word.isascii() and word.isdigit()),
    )
    return Identifiers(
        keys=tuple(dict.fromkeys(key for key in keys if ISSUE_KEY.fullmatch(key))),
        ids=tuple(dict.fromkeys(ids)),
    )


def plan_query(query: str) -> Plan:
    """Plan a query: its words, without stop words unless nothing else is left.

    The first MAX_WORDS distinct words are searched; the phrase counts when the query
    has PHRASE_WORDS words, stop words included.
    """
    tokens = [word.lower() for word in WORD.findall(unicodedata.normalize("NFC", query))]
    kept = list(dict.fromkeys(word for word in tokens if word not in STOP_WORDS))
    distinct = kept or list(dict.fromkeys(tokens))
    words = tuple(distinct[:MAX_WORDS])
    phrase = [quote(" ".join(tokens))] if len(tokens) in PHRASE_WORDS else []
    return Plan(
        words=words,
        expressions=(*(quote(word) for word in words), *phrase),
        match=" OR ".join(quote(word) for word in words),
        identifiers=identifiers(query),
        dropped=len(distinct) - len(words),
    )


def sections(body: str) -> list[Section]:
    """Cut a Markdown body before each ATX heading outside fenced code.

    The sections' texts, in order, give back the body exactly.
    """
    cuts: list[tuple[int, str, int]] = []  # where, the heading, the heading line's length
    fence = ""
    offset = 0
    for line in body.split("\n"):
        content = line.removesuffix("\r")
        opening = FENCE.match(content)
        if fence:
            if opening and opening[1].startswith(fence) and not opening[2].strip():
                fence = ""
        elif opening:
            fence = opening[1]
        elif heading := HEADING.fullmatch(content):
            cuts.append((offset, (heading[2] or "").strip(), len(line) + 1))
        offset += len(line) + 1
    if not cuts or cuts[0][0]:
        cuts.insert(0, (0, "", 0))
    ends = [start for start, _, _ in cuts[1:]] + [len(body)]
    return [
        Section(
            number=number,
            heading=heading,
            start=start,
            head=body[start : start + head],
            body=body[start + head : end],
        )
        for number, ((start, heading, head), end) in enumerate(zip(cuts, ends, strict=True), 1)
    ]


def tree_key(path: tuple[str, ...]) -> tuple[tuple[str | int, ...], ...]:
    """Order tree paths depth first, names without regard to case, numbers as numbers."""
    return tuple(
        tuple(int(part) if index % 2 else part for index, part in enumerate(NUMBER.split(name)))
        for name in (name.casefold() for name in path)
    )


def tree_order(entries: Sequence[IndexedDocument]) -> list[tuple[Place, IndexedDocument]]:
    """Place each document of one scope in its tree; give them in tree order, with places.

    A document sits under its parent where ``entries`` list it. Else under the titles of
    its breadcrumb, as ancestors not listed, below the listed document whose breadcrumb
    and title are the longest run of them from the top, where one alone has them; the
    title of a parent not listed, the breadcrumb's last, is never that document's. A
    loop of parents is cut where it closes, climbing from its first document in the
    order given, so that one listing gives one tree. Depth first by ``tree_key``, ties
    at each level by path.
    """
    by_id = {document_id(each.front.source, each.front.id): each for each in entries}
    titled: dict[tuple[str, ...], list[IndexedDocument]] = {}
    for each in entries:
        titled.setdefault((*each.front.breadcrumb, each.front.title), []).append(each)
    places: dict[str, Place] = {}

    def place(entry: IndexedDocument, placing: frozenset[str]) -> Place:
        if entry.path not in places:
            front, placing = entry.front, placing | {entry.path}
            parent, unlisted = by_id.get(front.parent or ""), ()
            if parent is None or parent.path in placing:
                crumbs = front.breadcrumb
                sizes = range(len(crumbs) - (front.parent is not None), 0, -1)
                runs = ((size, titled.get(crumbs[:size], [])) for size in sizes)
                size, parent = next(
                    (
                        (size, run[0])
                        for size, run in runs
                        if len(run) == 1 and run[0].path not in placing
                    ),
                    (0, None),
                )
                unlisted = crumbs[size:]
            places[entry.path] = (
                *(place(parent, placing) if parent else ()),
                *((title, "") for title in unlisted),
                (front.title, entry.path),
            )
        return places[entry.path]

    placed = [(place(each, frozenset()), each) for each in entries]
    return sorted(
        placed,
        key=lambda pair: tuple(
            zip(
                tree_key(tuple(title for title, _ in pair[0])),
                (path for _, path in pair[0]),
                strict=True,
            )
        ),
    )


def rank(scores: Iterable[dict[str, Score]], pinned: Sequence[str], *, sort: Sort) -> list[str]:
    """Order the documents found: those pinned first, in their order, then the others.

    The others go by their relevance summed over the expressions, or by the date asked,
    newest first; ties go to the newest update, then the path. Only scores by words hold
    the created date: sorting by it a score without one raises ValueError.
    """
    total: dict[str, float] = {}
    dated: dict[str, Score] = {}  # a score of each document, for its dates
    for found in scores:
        for path, score in found.items():
            total[path] = total.get(path, 0.0) + score.relevance
            dated[path] = score

    def key(path: str) -> tuple[float, float, str]:
        score = dated[path]
        newest = -score.updated.timestamp()
        if sort == "relevance":
            return -total[path], newest, path
        if sort == "updated":
            return 0.0, newest, path
        if score.created is None:
            message = f"{path}: a score by meaning, which holds no created date"
            raise ValueError(message)
        return -score.created.timestamp(), newest, path

    first = list(dict.fromkeys(pinned))
    return [*first, *sorted((path for path in total if path not in first), key=key)]


def fuse(rankings: Iterable[Sequence[str]], updated: Mapping[str, datetime]) -> list[str]:
    """Merge rankings by reciprocal rank fusion: each list gives 1 / (FUSION + rank).

    Ties go to the newest update, then the path; ``updated`` holds every document.
    """
    score: dict[str, float] = {}
    for ranking in rankings:
        for rank, path in enumerate(ranking, 1):
            score[path] = score.get(path, 0.0) + 1 / (FUSION + rank)
    return sorted(score, key=lambda path: (-score[path], -updated[path].timestamp(), path))
