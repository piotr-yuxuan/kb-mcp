"""Search's pure rules, and what the index hands back.

How a query becomes expressions for the index, how a body is cut into sections, and in
which order a space or a project is browsed. Nothing here reads a file or the index:
``adapters.sqlite_index`` runs the expressions and returns these types.
"""

from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from atlassian_offline_mcp.domain.content import ISSUE_KEY

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from datetime import datetime

    from numpy.typing import NDArray

    from atlassian_offline_mcp.domain.mirror import FrontMatter

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
# The characters of a piece of a section that one vector stands for, at most: under the
# 512 tokens of the smaller models' window, with the title, in English and French.
PIECE = 1200
BLANK_LINE = re.compile(r"\n[ \t]*\n")
NOT_SPACE = re.compile(r"\S")
# Reciprocal rank fusion's constant: a document's share of a list is 1 / (FUSION + rank).
FUSION = 60
# Characters of a document's title that each embedded piece begins with.
EMBEDDED_TITLE = 200


@dataclass(frozen=True)
class Identifiers:
    """The issue keys and page ids that a text names, in its order."""

    keys: tuple[str, ...]
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
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


@dataclass(frozen=True)
class Section:
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


@dataclass(frozen=True)
class Score:
    """How well a document matches one expression, by its best section."""

    relevance: float  # higher is better
    updated: datetime


@dataclass(frozen=True)
class Filters:
    """What narrows a search, each value as the index holds it; None does not narrow."""

    source: str | None = None
    space: str | None = None
    project: str | None = None
    status: str | None = None
    label: str | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None


@dataclass(frozen=True)
class Entry:
    """A document as the index holds it."""

    path: str  # relative to <data>/docs, with /
    front: FrontMatter
    length: int  # characters of the body
    sections: int


@dataclass(frozen=True)
class Passage:
    """A section of a document, as a search shows it: its number, heading and snippet."""

    number: int
    heading: str
    snippet: str


@dataclass(frozen=True)
class Summary:
    """What an index holds, and when it was built."""

    built_at: datetime
    skipped: int  # files of the mirror that could not be read
    types: dict[str, int]  # documents per type: page, blogpost, issue
    spaces: dict[str, int]
    projects: dict[str, int]
    sections: int
    newest_fetch: datetime | None
    model: str | None = None  # the model of the vectors, if any
    pieces: int = 0


@dataclass(frozen=True)
class Embedded:
    """The model that embedded an index's pieces, as the index records it."""

    model: str
    fingerprint: str
    dimensions: int


@dataclass(frozen=True, eq=False)
class Pieces:
    """Every piece of an index with its unit vector: what a search by meaning looks through."""

    documents: tuple[int, ...]  # each piece's document, by rowid
    paths: Mapping[int, str]  # each document's path, by rowid
    updated: Mapping[str, datetime]  # each document's update, by path
    sections: tuple[int, ...]  # each piece's section number
    offsets: tuple[int, ...]  # where each piece starts in its document's body
    matrix: NDArray[np.float32]  # one row per piece

    def nearest(
        self, query: NDArray[np.float32], kept: Collection[int] | None, limit: int
    ) -> dict[str, tuple[Score, int]]:
        """Score the documents nearest a query by their best piece, at most ``limit``.

        Only the documents in ``kept`` count, when it is given. Each path comes with its
        score, the cosine of its best piece, and that piece's index.
        """
        found: dict[str, tuple[Score, int]] = {}
        similarity = self.matrix @ query.reshape(-1) if self.documents else np.empty(0)
        for index in np.argsort(-similarity, kind="stable"):
            document = self.documents[index]
            path = self.paths[document]
            if path in found or (kept is not None and document not in kept):
                continue
            found[path] = (Score(float(similarity[index]), self.updated[path]), int(index))
            if len(found) == limit:
                break
        return found


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
        tuple(dict.fromkeys(key for key in keys if ISSUE_KEY.fullmatch(key))),
        tuple(dict.fromkeys(ids)),
    )


def plan(query: str) -> Plan:
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
            number,
            heading,
            start,
            body[start : start + head],
            body[start + head : end],
        )
        for number, ((start, heading, head), end) in enumerate(zip(cuts, ends, strict=True), 1)
    ]


def tree_paths(fronts: Sequence[FrontMatter]) -> list[tuple[str, ...]]:
    """Name where each document sits in its space or project: its ancestors, then itself.

    A Confluence breadcrumb names every ancestor by title, so a page is named by its
    title. A Jira breadcrumb names only the parent, by key, so an issue is named by its
    key and its chain of parents is followed among ``fronts``, a cycle stopping it.
    """
    parents = {front.key: front.breadcrumb[0] for front in fronts if front.key and front.breadcrumb}
    paths: list[tuple[str, ...]] = []
    for front in fronts:
        if not front.key:
            paths.append((*front.breadcrumb, front.title))
            continue
        chain = [front.key]
        while chain[-1] in parents and parents[chain[-1]] not in chain:
            chain.append(parents[chain[-1]])
        paths.append(tuple(reversed(chain)))
    return paths


def tree_key(path: tuple[str, ...]) -> tuple[tuple[str | int, ...], ...]:
    """Order tree paths depth first, names without regard to case, numbers as numbers."""
    return tuple(
        tuple(int(part) if index % 2 else part for index, part in enumerate(NUMBER.split(name)))
        for name in (name.casefold() for name in path)
    )


def rank(
    scores: Iterable[dict[str, Score]], pinned: Sequence[str], *, by_update: bool
) -> list[str]:
    """Order the documents found: those pinned first, in their order, then the others.

    The others go by their relevance summed over the expressions, or by update time when
    asked; ties go to the newest update, then the path.
    """
    total: dict[str, float] = {}
    updated: dict[str, datetime] = {}
    for found in scores:
        for path, score in found.items():
            total[path] = total.get(path, 0.0) + score.relevance
            updated[path] = score.updated
    first = list(dict.fromkeys(pinned))
    rest = sorted(
        (path for path in total if path not in first),
        key=lambda path: (0.0 if by_update else -total[path], -updated[path].timestamp(), path),
    )
    return [*first, *rest]


def pieces(text: str, limit: int = PIECE) -> list[tuple[int, int]]:
    """Cut a section's text into pieces of at most ``limit`` characters, as spans.

    A piece ends at the last blank line that fits; a paragraph longer than the limit is
    cut at its last line break that fits, else its last space, else at the limit. A
    piece starts at its first character that is not white space, so none is blank.
    """
    breaks = [found.end() for found in BLANK_LINE.finditer(text)]
    spans: list[tuple[int, int]] = []
    start = 0
    while found := NOT_SPACE.search(text, start):
        start = found.start()
        end = min(start + limit, len(text))
        if end < len(text):
            fitting = [cut for cut in breaks if start < cut <= end]
            # A line break or space just past the limit ends a piece that fits it exactly.
            line, space = (text.rfind(each, start + 1, end + 1) for each in ("\n", " "))
            end = fitting[-1] if fitting else next((cut for cut in (line, space) if cut > 0), end)
        spans.append((start, end))
        start = end
    return spans


def passages(title: str, cut: Sequence[Section]) -> list[tuple[int, int, int, str]]:
    """Give the text to embed for each piece of a document's sections.

    Each is the section's index in ``cut``, the piece's span in the section's body (its
    heading line aside), and the text: the title (cut to EMBEDDED_TITLE characters), the
    section's heading when it is not the title, and the piece, one per line. A section
    without a body has no piece.
    """
    found: list[tuple[int, int, int, str]] = []
    for index, section in enumerate(cut):
        heading = section.heading if section.heading != title else ""
        found += [
            (index, start, end, "\n".join(line for line in lines if line))
            for start, end in pieces(section.body)
            for lines in [(title[:EMBEDDED_TITLE], heading, section.body[start:end].strip())]
        ]
    return found


def fuse(rankings: Iterable[Sequence[str]], updated: Mapping[str, datetime]) -> list[str]:
    """Merge rankings by reciprocal rank fusion: each list gives 1 / (FUSION + rank).

    Ties go to the newest update, then the path; ``updated`` holds every document.
    """
    score: dict[str, float] = {}
    for ranking in rankings:
        for rank, path in enumerate(ranking, 1):
            score[path] = score.get(path, 0.0) + 1 / (FUSION + rank)
    return sorted(score, key=lambda path: (-score[path], -updated[path].timestamp(), path))
