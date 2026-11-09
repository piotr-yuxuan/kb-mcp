"""The tools of the MCP server, as the methods of one library over the index.

A method's name, parameters and defaults are its tool's schema, and continuation calls
are written from them, so the two never drift apart. Each call opens the index for
itself, so a rebuilt index is read from the next call on. A call that cannot be
answered as asked raises ``UnanswerableError``, whose message says what would do. A
ranking's search by words and by meaning are each a span, within the call's own, as
``docs/reference/telemetry/serve.md`` lists them.
"""

from __future__ import annotations

import bisect
import json
import math
import re
import unicodedata
from contextlib import contextmanager
from copy import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict

import structlog
from opentelemetry import metrics, trace

from kb_mcp.config.domain.settings import SearchMode as Mode
from kb_mcp.kernel.names import WORKLOG_ID
from kb_mcp.kernel.record import Record
from kb_mcp.kernel.reranking import DEPTHS, LONGEST_QUERY
from kb_mcp.mcp.app import responses
from kb_mcp.mirror.domain.mirror import ref_of
from kb_mcp.search.app.meaning import Nearest
from kb_mcp.search.domain import people
from kb_mcp.search.domain.chunking import CHUNKERS, PASSAGE_CHARS, around
from kb_mcp.search.domain.indexes import UnavailableIndexError
from kb_mcp.search.domain.reranking import (
    BODY_CHARS,
    HEADING_CHARS,
    TITLE_CHARS,
    split_order,
    written,
)
from kb_mcp.search.domain.search import (
    MAX_WORDS,
    Filters,
    Passage,
    Plan,
    Sort,
    fuse,
    identifiers,
    plan_query,
    rank,
    tree_key,
    tree_paths,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from kb_mcp.search.app.meaning import Meaning
    from kb_mcp.search.app.reranking import Reranking
    from kb_mcp.search.domain.indexes import SearchIndex, SearchReader
    from kb_mcp.search.domain.search import IndexedDocument

SEARCH_LIMIT = 8
SEARCH_LIMITS = (1, 50)
BROWSE_LIMIT = 50
BROWSE_LIMITS = (1, 200)
READ_CHARS = 12_000
CHARS_LIMITS = (1, 40_000)
LONGEST = {"query": LONGEST_QUERY, "ref": 300, "value": 100, "cursor": 100}
VALUES_SHOWN = 100
# The hex digits of the index's build that a cursor names, as many as a time took: the
# whole id would take a reranking's deepest past LONGEST["cursor"], from an offset of 100.
CURSOR_BUILD = 16
NO_WORDS = (
    "The query has no words to search."
    ' Give words, or sort="updated" or "created" to list the newest by that date.'
)
NO_QUESTION = "The question has no words to search: ask it in words."
# The documents that one answer of ask quotes, at most, however short their passages.
ASK_DOCUMENTS = 20
NOT_MIRRORED = (
    "Not mirrored: the mirror holds no such document. It holds what was downloaded;"
    " status() says which spaces and projects, and search() finds by words."
)
TRACER = trace.get_tracer(__name__)
# The searches asked by meaning that ranked by words alone, by the mode asked.
FALLBACKS = metrics.get_meter(__name__).create_counter(
    "kb_mcp.serve.fallbacks", unit="{fallback}", description="Searches by meaning ranked by words"
)


class SearchFilters(TypedDict, total=False):
    """What narrows a search. Values match without regard to case; dates are ISO 8601.

    source worklog: the user's entries (notes, AI summaries) and transcripts (verbatim).
    person: in any role, by any of their names or their id.
    author: an issue's reporter, a page's creator; creator: an issue's.
    commented_*: by commenter if given; _after included, _before excluded.
    participant: a meeting's, or a transcript's speaker.
    """

    source: Literal["confluence", "jira", "worklog"]
    space: str
    project: str
    status: str
    label: str
    issue_type: str
    person: str
    author: str
    creator: str
    assignee: str
    commenter: str
    participant: str
    updated_after: str  # this moment included
    updated_before: str  # this moment excluded
    created_after: str  # this moment included
    created_before: str  # this moment excluded
    commented_after: str  # this moment included
    commented_before: str  # this moment excluded


def untitled(schema: dict[str, Any]) -> None:
    """Drop the title that Pydantic gives each filter, its name again: every request carries it."""
    for each in schema["properties"].values():
        each.pop("title", None)


# Pydantic, which the SDK validates arguments with, then refuses a misspelt filter
# rather than drop it, and writes the schema without titles.
SearchFilters.__pydantic_config__ = {"extra": "forbid", "json_schema_extra": untitled}


NOT_SET_UP = "this server searches by words alone"


class UnanswerableError(Exception):
    """A call that cannot be answered as asked; the message says what would do."""


class Ranking(Record):
    """The documents ranked for a query, best first, and how they were ranked."""

    paths: list[str]
    whole: bool  # every document matching the words is counted
    meaning: dict[str, tuple[int, int, int]]  # for each document shown by meaning, the
    # section number of its best piece, and the piece's start and end in the body
    counted: str = "found"  # what the count line calls the documents counted
    note: str = ""  # the sentences saying why meaning, or reranking, was not used
    pinned: int = 0  # the documents that the query names, first, by identifier
    order: tuple[int, ...] = ()  # how the documents after those were reranked, by place


class Asked(Record):
    """A search as asked: its query and plan, its filters, its order and its mode."""

    query: str
    planned: Plan
    filters: Filters
    sort: Sort
    mode: Mode
    order: tuple[int, ...] | None = None  # the order that a cursor carries: None, none yet


def ranking(reader: SearchReader, meaning: Meaning | None, asked: Asked) -> Ranking:
    """Rank the documents for a query in a mode; documents it names by identifier first.

    Lexical: by words, as 006 ranks. Semantic: the nearest by meaning. Hybrid: both,
    fused by reciprocal rank. Sorted by a date, or with no meaning to search, by words,
    with a note saying why, which is the warning ``search.fallback``, counted in
    ``kb_mcp.serve.fallbacks``. A document is shown by meaning when that ranks it higher.
    The search by words is the span ``search.lexical``, by meaning ``search.semantic``.
    """
    planned, filters, by_date = asked.planned, asked.filters, asked.sort != "relevance"
    with TRACER.start_as_current_span("search.lexical"):
        found = [reader.scores(each, filters, every=by_date) for each in planned.expressions]
        named = [*planned.identifiers.keys, *planned.identifiers.ids]
        keys, ids = planned.identifiers.keys, planned.identifiers.ids
        pinned = reader.indexed_documents(keys=keys, ids=ids, filters=filters)
        ordered = sorted(pinned, key=lambda e: named.index(ref_of(e.front.key, e.front.id)))
        first = [entry.path for entry in ordered]
        words = rank((one for one, _ in found), first, sort=asked.sort)
        whole = all(every for _, every in found)
    if asked.mode == "lexical" or by_date:
        return Ranking(paths=words, whole=whole, meaning={}, pinned=len(first))
    with TRACER.start_as_current_span("search.semantic"):
        near = (
            meaning.nearest(reader, asked.query, filters)
            if meaning
            else Nearest(found={}, reason=NOT_SET_UP)
        )
    if near.reason:
        FALLBACKS.add(1, {"kb_mcp.mode": asked.mode})
        structlog.get_logger().warning("search.fallback", mode=asked.mode, reason=near.reason)
        note = f" Ranked by words alone: {near.reason}."
        return Ranking(paths=words, whole=whole, meaning={}, note=note, pinned=len(first))
    scores = {path: score for path, (score, *_) in near.found.items()}
    by_meaning = rank([scores], first, sort="relevance")
    shown = {path: tuple(where) for path, (_, *where) in near.found.items()}
    if asked.mode == "semantic":
        counted = "nearest in meaning"
        return Ranking(
            paths=by_meaning, whole=True, meaning=shown, counted=counted, pinned=len(first)
        )
    updated = {path: s.updated for one, _ in found for path, s in one.items()}
    updated |= {path: score.updated for path, score in scores.items()}
    # Both lists begin with the documents named; the rest is fused.
    fused = fuse([words[len(first) :], by_meaning[len(first) :]], updated)
    # A document that words do not find is ranked by meaning alone: shown by meaning.
    places = {path: at for at, path in enumerate(words)}
    higher = [path for at, path in enumerate(by_meaning) if at < places.get(path, math.inf)]
    by_higher = {path: shown[path] for path in higher if path in shown}
    counted = "found by words or meaning"
    return Ranking(
        paths=[*first, *fused], whole=whole, meaning=by_higher, counted=counted, pinned=len(first)
    )


def snippet_of(
    reader: SearchReader, entry: IndexedDocument, ranked: Ranking, planned: Plan
) -> Passage:
    """Find the section to show for a document: by meaning or by words, as it was ranked.

    A document shown by words opens at its best section for the query's words; one
    without them, at its start, with a lead that leaves out the title's heading.
    """
    if entry.path in ranked.meaning:
        number, start, end = ranked.meaning[entry.path]
        lead = reader.text(entry.path, start, min(end, start + 2 * responses.SNIPPET))
        return Passage(number=number, heading=reader.heading(entry.path, number), text=lead)
    passage = reader.snippet(entry.path, planned.match) if planned.words else None
    lead = "" if passage else reader.text(entry.path, 0, 2 * responses.SNIPPET)
    return passage or Passage(number=1, heading="", text=lead.partition("\n")[2])


def folded(text: str) -> str:
    """Write a text without its accents, character for character, as the index compares.

    Each character is the first of its decomposition, so that offsets hold: a text
    written decomposed keeps its marks, and a Hangul syllable becomes its first jamo,
    where the index differs; a passage then falls back to its section's start.
    """
    return "".join(unicodedata.normalize("NFD", char)[0] for char in text)


def place_of(
    reader: SearchReader, ranked: Ranking, planned: Plan, path: str
) -> tuple[int, tuple[int, int]]:
    """Give a document's section, by its number, and its best place there, as a span of the body.

    A document ranked by meaning gives its best piece. One ranked by words gives the
    occurrence of the question's rarest word with the most other words within UNIT / 2
    of it, in its best section for the question's words, or the start of its first.
    Words are found as the index finds them: without regard to case or accents, between
    characters that are no letter nor digit. Candidates being the rarest word's
    occurrences, a section of many hits costs as many bisections.
    """
    if path in ranked.meaning:
        number, start, end = ranked.meaning[path]
        return number, (start, end)
    alone = (rf"(?<![^\W_]){re.escape(folded(word))}(?![^\W_])" for word in planned.words)
    words = re.compile("|".join(alone), re.IGNORECASE)
    best = reader.snippet(path, planned.match) if planned.words else None
    number = best.number if best else 1
    first, last = reader.bounds(path)[number - 1]
    spots: dict[str, list[int]] = {}  # where each word of the question is
    for each in words.finditer(folded(reader.text(path, first, last))):
        spots.setdefault(each[0].casefold(), []).append(each.start())
    hit = first + max(
        min(spots.values(), key=len, default=[0]),
        key=lambda at: sum(
            bisect.bisect_left(places, at - PASSAGE_CHARS // 2)
            < bisect.bisect_right(places, at + PASSAGE_CHARS // 2)
            for places in spots.values()
        ),
    )
    return number, (hit, hit + 1)


def passages(
    reader: SearchReader, ranked: Ranking, planned: Plan, paths: list[str]
) -> list[Passage]:
    """Give the passage that ask quotes of each document, verbatim, in the order given.

    About each document's best place (``place_of``): by meaning, the unit of its best
    piece, by the index's chunking; by words, its section whole up to UNIT characters,
    else UNIT of it about the place, by ``around``, then cut to whole lines where a line
    break falls in the half that the cut shortens.
    """
    embedded = reader.embedded()
    quoted_span = CHUNKERS[embedded.chunking].quoted_span if embedded else None
    found = []
    for path in paths:
        number, place = place_of(reader, ranked, planned, path)
        first, last = reader.bounds(path)[number - 1]
        if quoted_span and path in ranked.meaning:
            start, end = quoted_span(place, (first, last))
            text = reader.text(path, start, end)
        else:
            start, end = around(place, (first, last))
            text = reader.text(path, start, end)
            text = (
                text
                if end == last
                else text[: text.rfind("\n", PASSAGE_CHARS // 2) + 1 or PASSAGE_CHARS]
            )
            text = text if start == first else text[text.find("\n", 0, PASSAGE_CHARS // 2) + 1 :]
        found.append(Passage(number=number, heading=reader.heading(path, number), text=text))
    return found


def reranked(
    reader: SearchReader, asked: Asked, ranked: Ranking, reranking: Reranking | None
) -> Ranking:
    """Reorder the documents after those named, as many as the reranking's depth, by score.

    A page that continues another keeps the order that its cursor carries, reranked or
    not, and asks nothing. A first page asks the reranking server about the next
    documents, each by its title, the heading of its section and BODY characters about
    its best place (``place_of``); with fewer than two, it asks nothing. A reranking that
    fails keeps the order given, and the note says why. Sorted by a date, nothing moves.
    Raises UnanswerableError for a cursor whose order passes the documents now found.
    """
    if asked.sort != "relevance" or (asked.order is None and reranking is None):
        return ranked
    start = ranked.pinned
    order = asked.order
    if order is None:
        candidates = ranked.paths[start : start + reranking.depth]
        if len(candidates) < DEPTHS.start:
            return ranked
        indexed = {entry.path: entry for entry in reader.indexed_documents(paths=candidates)}
        texts = []
        for path in candidates:
            number, place = place_of(reader, ranked, asked.planned, path)
            first, last = around(place, reader.bounds(path)[number - 1], BODY_CHARS)
            title, heading = indexed[path].front.title, reader.heading(path, number)
            texts.append(
                f"{title[:TITLE_CHARS]}\n{heading[:HEADING_CHARS]}\n"
                f"{reader.text(path, first, last)}"
            )
        reordering = reranking.reorder(asked.query, texts)
        if reordering.order is None:
            return replace(ranked, note=f"{ranked.note} Not reranked: {reordering.reason}.")
        order = reordering.order
    if len(ranked.paths) < start + len(order):
        message = "cursor: the ranking changed since; call again without the cursor"
        raise UnanswerableError(message)
    moved = ranked.paths[start : start + len(order)]
    paths = [
        *ranked.paths[:start],
        *(moved[place] for place in order),
        *ranked.paths[start + len(order) :],
    ]
    return replace(ranked, paths=paths, order=order)


def checked(filters: SearchFilters | None) -> dict[str, str]:
    """Refuse a filter that is not one, or a value too long; give the filters given."""
    given: dict[str, str] = {**(filters or {})}
    if unknown := sorted(set(given) - SearchFilters.__optional_keys__):
        valid = ", ".join(sorted(SearchFilters.__optional_keys__))
        message = f"filters: no {', '.join(unknown)}; the filters are {valid}"
        raise UnanswerableError(message)
    bounded(**{name: (value, LONGEST["value"]) for name, value in given.items()})
    return given


def narrowed(reader: SearchReader, given: Mapping[str, str]) -> Filters:
    """Give the filters as the index holds their values, refusing one that no document has."""
    names = ("source", "space", "project", "status", "label", "issue_type")
    dates = (
        *("updated_after", "updated_before", "created_after", "created_before"),
        *("commented_after", "commented_before"),
    )
    return Filters(
        **{name: canonical(reader, name, given.get(name)) for name in names},
        **{name: who(reader, name, given.get(name)) for name in PERSON_FILTERS},
        **{name: instant(name, given.get(name)) for name in dates},
    )


# Each filter that names a person, and the role it keeps them in: person, any.
PERSON_FILTERS = {
    "person": None,
    "author": "author",
    "creator": "creator",
    "assignee": "assignee",
    "commenter": "commenter",
    "participant": "participant",
}


def who(reader: SearchReader, name: str, value: str | None) -> str | None:
    """Find the person whom a filter names, by their id or any name that a source writes.

    Of the persons with a document in the filter's role, in PERSON_FILTERS, the one of
    that id, else those holding a name of the value's key (``people.name_key``): one is
    taken, as is, of several, for a value with an annotation, the one alone holding a
    name written as the value is, annotation included (``people.written_key``), such as
    an account named "Robin (Ops)" beside one named "Robin (Sales)"; a bare "Robin"
    beside them could be either, though a person by name alone writes it so. Refuse a
    value that none holds there, listing the role's names: those whose key holds the
    value's first, the most used first; and one that several hold, listing
    ``responses.NAMES`` of them at most, those of the most documents first, then by id,
    each by name, id, documents by role and by source and the last update, so that the
    agent gives one's id, then how many more.
    """
    if value is None:
        return None
    role, wanted = PERSON_FILTERS[name], people.name_key(value)
    ids = [value] if people.PERSON_ID.fullmatch(value) else reader.persons(wanted)
    found = [
        each for each in map(reader.person, ids) if each and (role is None or role in each.roles)
    ]
    written = people.written_key(value)
    exact = [
        each
        for each in found
        if written != wanted
        and written in {people.written_key(spelling.name) for spelling in each.person.names}
    ]
    if len(found) == 1 or len(exact) == 1:
        return (exact or found)[0].person.id
    quoted = json.dumps(value, ensure_ascii=False)
    if found:
        message = f"{name}: {quoted} names {len(found)} people; give the id of one:"
        found.sort(key=lambda each: (-sum(each.sources.values()), each.person.id))
        listed = "\n".join(responses.activity(each) for each in found[: responses.NAMES])
        rest = len(found) - responses.NAMES
        more = f"({rest} more are not shown.)" if rest > 0 else ""
        raise UnanswerableError(responses.answer(message, listed, more))
    message = f"{name}: no document has {quoted}; the valid values:"
    valid = [candidate for candidate, _ in reader.values(name)]
    listed = sorted(valid, key=lambda each: wanted not in people.name_key(each))
    raise UnanswerableError(responses.refusal(message, listed[:VALUES_SHOWN], len(valid)))


def about(
    reader: SearchReader, filters: Filters, paths: Sequence[str]
) -> tuple[str, dict[str, str]]:
    """Write the person that ``person`` narrows to, and their roles on each document shown.

    The person as ``responses.person`` writes them, then a blank line, with those perhaps
    the same: of each ``people.first_word`` of their names, the one other person whose
    names of that key joined by name, whom an alias of the word, written as their name
    of that key, would join to them; none where an account is named by the word, from
    which the alias would take the name, or where those names are several persons, which
    annotations keep apart and the alias would join too. Then their roles by path, as
    ``responses.roles`` says them. Nothing without that filter.
    """
    if filters.person is None:
        return "", {}
    found = reader.person(filters.person)
    words = sorted({people.first_word(spelling.name) for spelling in found.person.names})
    moved = [
        (word, reader.persons(word, people.NAME))
        for word in words
        if not reader.persons(word, people.ACCOUNT)
    ]
    alike = [
        (word, reader.person(ids[0]))
        for word, ids in moved
        if len(ids) == 1 and ids[0] != filters.person
    ]
    others = [
        (next(each.name for each in other.person.names if each.key == word), other.person.id)
        for word, other in alike
        if other
    ]
    held = reader.roles(filters.person, paths)
    roles = {path: responses.roles(found.person.name, each) for path, each in held.items()}
    return f"{responses.person(found, others)}\n\n", roles


def bounded(**values: tuple[str | None, int]) -> None:
    """Refuse an argument longer than its limit, naming it."""
    for name, (value, limit) in values.items():
        if value is not None and len(value) > limit:
            message = f"{name}: at most {limit} characters"
            raise UnanswerableError(message)


def canonical(reader: SearchReader, name: str, value: str | None) -> str | None:
    """Find the value that the index holds for a filter, without regard to case or accents.

    Values compare as hits show them, their spaces collapsed, composed and casefolded,
    then decomposed without the combining diacritical marks of U+0300 to U+036F and
    casefolded again: a Hangul syllable keeps its letters, a kana its voicing mark. One
    value alone matching is taken; else the value given, then one that a hit shows
    alike, the most used first. Refuse a value that no document has, or that several
    have but for accents alone, listing the valid ones: those holding it first, the
    most used first.
    """
    if value is None:
        return None

    def shown(text: str) -> str:
        return unicodedata.normalize("NFC", " ".join(text.split())).casefold()

    def plain(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", shown(text))
        return "".join(char for char in decomposed if not "\u0300" <= char <= "\u036f").casefold()

    valid = [candidate for candidate, _ in reader.values(name)]
    wanted = plain(value)
    found = [each for each in valid if plain(each) == wanted]
    cased = [each for each in found if shown(each) == shown(value)]
    if len(found) == 1:
        return found[0]
    if cased:
        return value if value in cased else cased[0]
    message = f"{name}: no document has {json.dumps(value, ensure_ascii=False)}; the valid values:"
    listed = sorted(valid, key=lambda each: wanted not in plain(each))
    raise UnanswerableError(responses.refusal(message, listed[:VALUES_SHOWN], len(valid)))


def instant(name: str, value: str | None) -> datetime | None:
    """Read an ISO 8601 date or time; a date is its midnight, a time without offset UTC."""
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
        return (moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment).astimezone(UTC)
    except ValueError, OverflowError:
        message = f"{name}: an ISO 8601 date or time, such as 2026-10-01 or 2026-10-01T09:00Z"
        raise UnanswerableError(message) from None


def start_of(cursor: str | None, build: str) -> int:
    """Read a cursor that an answer gave: an offset, for that build of the index."""
    if cursor is None:
        return 0
    offset, _, built = cursor.partition("@")
    if not offset.isascii() or not offset.isdigit() or not built:
        message = "cursor: give the one that the previous answer ended with"
        raise UnanswerableError(message)
    if built != build[:CURSOR_BUILD]:
        message = "cursor: the index was rebuilt since; call again without the cursor"
        raise UnanswerableError(message)
    return int(offset)


def continued(cursor: str | None, build: str) -> tuple[int, tuple[int, ...] | None]:
    """Read a cursor of search or ask: its offset, and the order of the documents reranked.

    The order is None for no cursor, a first page, and empty for a cursor that carries
    none. Refuses a cursor not given, as ``start_of`` does.
    """
    try:
        base, order = split_order(cursor)
    except ValueError:
        message = "cursor: give the one that the previous answer ended with"
        raise UnanswerableError(message) from None
    return start_of(base, build), order


def cursor_at(offset: int, build: str) -> str:
    """Write the cursor that continues a list at ``offset``, for this build of the index."""
    return f"{offset}@{build[:CURSOR_BUILD]}"


def clamp(value: int, limits: tuple[int, int]) -> int:
    """Bring a number within its limits, both included."""
    return max(limits[0], min(value, limits[1]))


class Shown(Record):
    """A document ranked for a query, with the section a search shows for it."""

    path: str
    section: int
    text: str  # the section's text, or the passage quoted, as the body holds it


class Library:
    """The four tools, over one index."""

    def __init__(
        self,
        index: SearchIndex,
        docs: Path,
        meaning: Meaning | None = None,
        mode: Mode = "lexical",
        reranking: Reranking | None = None,
    ) -> None:
        """Answer from ``index``, built from the mirror at ``docs``.

        Search ranks in ``mode``; by meaning, through ``meaning``, when it is given; its
        first documents are reranked through ``reranking``, when it is given.
        """
        self._index = index
        self._docs = docs
        self._meaning = meaning
        self._mode = mode
        self._reranking = reranking

    def rerank_with(self, reranking: Reranking | None) -> Library:
        """Give a library over the same index, reranking through ``reranking``, for evaluations."""
        return Library(self._index, self._docs, self._meaning, self._mode, reranking)

    @contextmanager
    def _reading(self) -> Iterator[SearchReader]:
        try:
            with self._index.reading() as reader:
                yield reader
        except UnavailableIndexError as error:
            raise UnanswerableError(str(error)) from None

    def _find(self, reader: SearchReader, ref: str) -> IndexedDocument | None:
        """Find a document by path, issue key, page or work-log id, or address, in that order."""
        named, path = identifiers(ref), ref.strip()
        ids = [path] if WORKLOG_ID.fullmatch(path) else named.ids[:1]
        found = reader.indexed_documents(paths=[path], keys=named.keys[:1], ids=ids)
        return min(found, key=lambda entry: (entry.path != path, not entry.front.key), default=None)

    def search(
        self,
        query: str = "",
        filters: SearchFilters | None = None,
        sort: Sort = "relevance",
        limit: int = SEARCH_LIMIT,
        cursor: str | None = None,
    ) -> str:
        """Search the offline mirror of Confluence, Jira and the work log, the best first.

        Words match without regard to case or accents; issue keys, page ids and page
        addresses in the query put their documents first. With sort="updated" or
        "created" and no query, lists the newest by that date. Each hit gives the read()
        call of its best section; a long list ends with the call that continues it.
        """
        given = checked(filters)
        bounded(query=(query, LONGEST["query"]), cursor=(cursor, LONGEST["cursor"]))
        planned = plan_query(query)
        with self._reading() as reader:
            built_at, build = reader.built_at(), reader.build()
            (offset, order), size = continued(cursor, build), clamp(limit, SEARCH_LIMITS)
            kept = narrowed(reader, given)
            if not planned.words and sort == "relevance":
                return responses.answer(NO_WORDS)
            ranked = Ranking(paths=[], whole=True, meaning={})
            if planned.words:
                asked = Asked(
                    query=query,
                    planned=planned,
                    filters=kept,
                    sort=sort,
                    mode=self._mode,
                    order=order,
                )
                first = ranking(reader, self._meaning, asked)
                ranked = reranked(reader, asked, first, self._reranking)
                total, whole = len(ranked.paths), ranked.whole
                paths = ranked.paths[offset : offset + size]
                shown = sorted(
                    reader.indexed_documents(paths=paths), key=lambda e: paths.index(e.path)
                )
            else:
                (total, shown), whole = reader.recent(kept, sort, offset, size), True
            # On the call's span, the SDK's: the mode, the documents found, whether words
            # stood in for meaning. Said here, as the docstring is the agent's to read.
            trace.get_current_span().set_attributes(
                {
                    "kb_mcp.mode": self._mode,
                    "kb_mcp.hits": total,
                    "kb_mcp.fallback": bool(ranked.note),
                    "kb_mcp.reranked": bool(ranked.order),
                }
            )
            items = []
            person, held = about(reader, kept, [entry.path for entry in shown])
            for number, entry in enumerate(shown, offset + 1):
                passage = snippet_of(reader, entry, ranked, planned)
                ref = ref_of(entry.front.key, entry.front.id)
                opening = responses.call(self.read, ref=ref, section=passage.number)
                items.append(responses.hit(number, entry, passage, opening, held.get(entry.path)))

        def more(count: int) -> str:
            after = cursor_at(offset + count, build) + written(ranked.order)
            return responses.call(
                self.search, query=query, filters=filters, sort=sort, limit=limit, cursor=after
            )

        # A note on falling back to words lengthens the header, and a person the block's
        # start: the hits make room for them.
        allowed = responses.budget(limit, SEARCH_LIMIT) - responses.tokens(ranked.note + person)
        count, footer = responses.page(items, total - offset, allowed, more)
        counted = f"Documents {ranked.counted}: {total if whole else f'at least {total}'}"
        header = f"{counted}; {responses.span(offset, count, built_at)}{ranked.note}"
        if planned.dropped:
            header += f" Only the first {MAX_WORDS} words of the query were searched."
        return responses.answer(header, person + "\n".join(items[:count]), footer)

    def ask(
        self, question: str, filters: SearchFilters | None = None, cursor: str | None = None
    ) -> str:
        """Answer a question from the offline mirror with passages to quote, the best first.

        Ask in words; issue keys and page ids in the question put their documents first.
        Each passage is the part of a document that answers best, verbatim, with its
        title, ref, section, dates, site address and the read() call of its section: cite
        it by ref. An answer holds what fits its budget, then the call that continues it.
        filters narrow as search's do.
        """
        answer, pairs, ranked = self._asked(question, filters, cursor, self._mode)
        # On the call's span, the SDK's, as for search: the mode, the documents found,
        # whether words stood in for meaning, and the passages quoted.
        trace.get_current_span().set_attributes(
            {
                "kb_mcp.mode": self._mode,
                "kb_mcp.hits": len(ranked.paths),
                "kb_mcp.fallback": bool(ranked.note),
                "kb_mcp.reranked": bool(ranked.order),
                "kb_mcp.passages": len(pairs),
            }
        )
        return answer

    def _asked(
        self, question: str, filters: SearchFilters | None, cursor: str | None, mode: Mode
    ) -> tuple[str, list[tuple[IndexedDocument, Passage]], Ranking]:
        """Write ask's answer in a mode; give the documents and passages quoted, and the ranking."""
        given = checked(filters)
        bounded(question=(question, LONGEST["query"]), cursor=(cursor, LONGEST["cursor"]))
        planned = plan_query(question)
        with self._reading() as reader:
            built_at, build = reader.built_at(), reader.build()
            offset, order = continued(cursor, build)
            kept = narrowed(reader, given)
            asked = Asked(
                query=question,
                planned=planned,
                filters=kept,
                sort="relevance",
                mode=mode,
                order=order,
            )
            if not planned.words:
                return responses.answer(NO_QUESTION), [], Ranking(paths=[], whole=True, meaning={})
            ranked = reranked(reader, asked, ranking(reader, self._meaning, asked), self._reranking)
            paths = ranked.paths[offset : offset + ASK_DOCUMENTS]
            indexed = {entry.path: entry for entry in reader.indexed_documents(paths=paths)}
            chosen = passages(reader, ranked, planned, paths)
            person, held = about(reader, kept, paths)
        pairs = [(indexed[path], passage) for path, passage in zip(paths, chosen, strict=True)]
        items = [
            responses.passage(
                number,
                entry,
                passage,
                responses.call(
                    self.read, ref=ref_of(entry.front.key, entry.front.id), section=passage.number
                ),
                held.get(entry.path),
            )
            for number, (entry, passage) in enumerate(pairs, offset + 1)
        ]

        def more(count: int) -> str:
            after = cursor_at(offset + count, build) + written(ranked.order)
            return responses.call(self.ask, question=question, filters=filters, cursor=after)

        allowed = responses.BUDGET - responses.tokens(ranked.note + person)
        total = len(ranked.paths)
        count, footer = responses.page(items, total - offset, allowed, more)
        counted = f"Documents {ranked.counted}: {total if ranked.whole else f'at least {total}'}"
        header = f"{counted}; {responses.span(offset, count, built_at)}{ranked.note}"
        content = person + "\n\n".join(items[:count])
        return responses.answer(header, content, footer), pairs[:count], ranked

    def quoted(self, question: str, mode: Mode) -> list[Shown]:
        """Give the passages of ask's first answer in a mode, for an evaluation."""
        return [
            Shown(path=entry.path, section=passage.number, text=passage.text)
            for entry, passage in self._asked(question, None, None, mode)[1]
        ]

    def key_of(self, kind: Literal["space", "project"], key: str) -> str:
        """Give a space's or a project's key as the index holds it; refuse one it lacks."""
        with self._reading() as reader:
            return canonical(reader, kind, key) or ""

    def resolve(self, ref: str) -> str | None:
        """Find a document's path by its id, key, address or path, as read does."""
        with self._reading() as reader:
            found = self._find(reader, ref)
        return None if found is None else found.path

    def ranked(self, query: str, mode: Mode, limit: int = SEARCH_LIMIT) -> tuple[list[Shown], str]:
        """Rank documents for a query as search does, in a mode, for an evaluation.

        Give the first ``limit``, each with the section that search shows for it, and
        the note saying why meaning was not used, if it was asked for and was not.
        """
        planned = plan_query(query)
        with self._reading() as reader:
            asked = Asked(
                query=query, planned=planned, filters=Filters(), sort="relevance", mode=mode
            )
            ranked = reranked(reader, asked, ranking(reader, self._meaning, asked), self._reranking)
            indexed = {
                entry.path: entry for entry in reader.indexed_documents(paths=ranked.paths[:limit])
            }
            shown = []
            for path in ranked.paths[:limit]:
                number = snippet_of(reader, indexed[path], ranked, planned).number
                start, end = reader.bounds(path)[number - 1]
                shown.append(Shown(path=path, section=number, text=reader.text(path, start, end)))
        return shown, ranked.note

    def read(
        self,
        ref: str,
        section: int | None = None,
        offset: int | None = None,
        max_chars: int = READ_CHARS,
    ) -> str:
        """Read a mirrored document, or one of its sections, from a character offset.

        ref: a page id, an issue key, a work-log id, a page or issue address, or a path in
        the mirror.
        A long document comes in slices, each ending with the call that reads on.
        """
        bounded(ref=(ref, LONGEST["ref"]))
        with self._reading() as reader:
            entry = self._find(reader, ref)
            if entry is None:
                return responses.answer(NOT_MIRRORED)
            built_at, bounds = reader.built_at(), reader.bounds(entry.path)
            if section is not None and not 1 <= section <= len(bounds):
                message = f"section: 1 to {len(bounds)} for this document"
                raise UnanswerableError(message)
            start, end = bounds[section - 1] if section else (0, entry.length)
            begin = start if offset is None else offset
            if begin != start and not start < begin < end:
                message = f"offset: {start} to {max(start, end - 1)} here"
                raise UnanswerableError(message)
            last = min(end, begin + clamp(max_chars, CHARS_LIMITS))
            text = reader.text(entry.path, begin, last)
        frame = responses.metadata(entry, whole=begin == 0)
        ref = ref_of(entry.front.key, entry.front.id)
        later = responses.call(self.read, ref=ref, section=section, offset=end, max_chars=max_chars)
        allowed = responses.budget(max_chars, READ_CHARS) - responses.RESERVE
        stop = begin + responses.cut(text, allowed - responses.tokens(frame + later))
        footer = ""
        if stop < end:
            onward = responses.call(
                self.read, ref=ref, section=section, offset=stop, max_chars=max_chars
            )
            footer = f"More: {onward}"
        elif section and section < len(bounds):
            footer = f"Next section: {responses.call(self.read, ref=ref, section=section + 1)}"
        part = f", section {section} of {len(bounds)}" if section else ""
        header = (
            f"Characters {begin} to {stop} of {entry.length}{part}."
            f" Index built {responses.stamp(built_at)}."
        )
        return responses.answer(header, f"{frame}\n\n{text[: stop - begin]}", footer)

    def browse(
        self,
        space: str | None = None,
        project: str | None = None,
        parent: str | None = None,
        limit: int = BROWSE_LIMIT,
        cursor: str | None = None,
    ) -> str:
        """List the documents of a space or a project in tree order, or those under a parent.

        Give space or project; parent is a page id, an issue key or an address within it.
        Bracketed lines name ancestors that are not listed there.
        """
        bounded(space=(space, LONGEST["value"]), project=(project, LONGEST["value"]))
        bounded(parent=(parent, LONGEST["ref"]), cursor=(cursor, LONGEST["cursor"]))
        with self._reading() as reader:
            if (space is None) == (project is None):
                keys = [f"space {key}" for key, _ in reader.values("space")]
                keys += [f"project {key}" for key, _ in reader.values("project")]
                message = "browse: give either space or project, one of:"
                raise UnanswerableError(responses.refusal(message, keys[:VALUES_SHOWN], len(keys)))
            built_at, build = reader.built_at(), reader.build()
            offset = start_of(cursor, build)
            narrowed = Filters(
                space=canonical(reader, "space", space),
                project=canonical(reader, "project", project),
            )
            listed = reader.listing(narrowed)
            top = None if parent is None else self._find(reader, parent)
        if parent is not None and top not in listed:
            return responses.answer(NOT_MIRRORED)
        paths = tree_paths([entry.front for entry in listed])
        # Ties go by path: pages of results need one order from call to call.
        pairs = sorted(
            zip(paths, listed, strict=True), key=lambda pair: (tree_key(pair[0]), pair[1].path)
        )
        base = next((path for path, entry in pairs if entry == top), ())
        pairs = [pair for pair in pairs if pair[0][: len(base)] == base and pair[0] != base]
        size = clamp(limit, BROWSE_LIMITS)
        items = responses.tree(pairs[offset : offset + size], len(base))

        def more(count: int) -> str:
            after = cursor_at(offset + count, build)
            return responses.call(
                self.browse, space=space, project=project, parent=parent, limit=limit, cursor=after
            )

        allowed = responses.budget(limit, BROWSE_LIMIT)
        count, footer = responses.page(items, len(pairs) - offset, allowed, more)
        header = f"Documents in tree order: {len(pairs)}; {responses.span(offset, count, built_at)}"
        return responses.answer(header, "\n".join(items[:count]), footer)

    def status(self) -> str:
        """Say what the offline mirror holds, and when its index was built."""
        with self._reading() as reader:
            summary = reader.index_status()
        return responses.status(summary, self._docs)
