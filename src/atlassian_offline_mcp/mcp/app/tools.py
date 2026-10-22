"""The tools of the MCP server, as the methods of one library over the index.

A method's name, parameters and defaults are its tool's schema, and continuation calls
are written from them, so the two never drift apart. Each call opens the index for
itself, so a rebuilt index is read from the next call on. A call that cannot be
answered as asked raises ``UnanswerableError``, whose message says what would do. A
ranking's search by words and by meaning are each a span, within the call's own, as
``docs/reference/telemetry/serve.md`` lists them.
"""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, TypedDict

import structlog
from opentelemetry import metrics, trace

from atlassian_offline_mcp.mcp.app import responses
from atlassian_offline_mcp.search.adapters.sqlite_index import UnavailableIndexError, reading
from atlassian_offline_mcp.search.app.meaning import Nearest
from atlassian_offline_mcp.search.domain.chunking import CHUNKERS, UNIT
from atlassian_offline_mcp.search.domain.search import (
    MAX_WORDS,
    Filters,
    Passage,
    fuse,
    identifiers,
    plan,
    rank,
    tree_key,
    tree_paths,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from atlassian_offline_mcp.config.domain.settings import SearchMode as Mode
    from atlassian_offline_mcp.search.adapters.sqlite_index import Reader
    from atlassian_offline_mcp.search.app.meaning import Meaning
    from atlassian_offline_mcp.search.domain.search import Entry, Plan

SEARCH_LIMIT = 8
SEARCH_LIMITS = (1, 50)
BROWSE_LIMIT = 50
BROWSE_LIMITS = (1, 200)
READ_CHARS = 12_000
CHARS_LIMITS = (1, 40_000)
LONGEST = {"query": 500, "ref": 300, "value": 100, "cursor": 100}
VALUES_SHOWN = 100
CURSOR_TIME = "%Y%m%dT%H%M%SZ"
NO_WORDS = (
    'The query has no words to search. Give words, or sort="updated" to list what changed last.'
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
    "aom.serve.fallbacks", unit="{fallback}", description="Searches by meaning ranked by words"
)


class SearchFilters(TypedDict, total=False):
    """What narrows a search. Values match without regard to case; dates are ISO 8601."""

    source: Literal["confluence", "jira"]
    space: str
    project: str
    status: str
    label: str
    updated_after: str  # this moment included
    updated_before: str  # this moment excluded


# Pydantic, which the SDK validates arguments with, then refuses a misspelt filter
# rather than drop it.
SearchFilters.__pydantic_config__ = {"extra": "forbid"}


NOT_SET_UP = "this server searches by words alone"


class UnanswerableError(Exception):
    """A call that cannot be answered as asked; the message says what would do."""


@dataclass(frozen=True)
class Ranking:
    """The documents ranked for a query, best first, and how they were ranked."""

    paths: list[str]
    whole: bool  # every document matching the words is counted
    meaning: dict[str, tuple[int, int, int]]  # for each document shown by meaning, the
    # section number of its best piece, and the piece's start and end in the body
    counted: str = "found"  # what the count line calls the documents counted
    note: str = ""  # the sentence saying why meaning, though asked for, was not used


@dataclass(frozen=True)
class Asked:
    """A search as asked: its query and plan, its filters, its order and its mode."""

    query: str
    planned: Plan
    filters: Filters
    by_update: bool
    mode: Mode


def ranking(reader: Reader, meaning: Meaning | None, asked: Asked) -> Ranking:
    """Rank the documents for a query in a mode; documents it names by identifier first.

    Lexical: by words, as 006 ranks. Semantic: the nearest by meaning. Hybrid: both,
    fused by reciprocal rank. Sorted by update, or with no meaning to search, by words,
    with a note saying why, which is the warning ``search.fallback``, counted in
    ``aom.serve.fallbacks``. A document is shown by meaning when that ranks it higher.
    The search by words is the span ``search.lexical``, by meaning ``search.semantic``.
    """
    planned, filters, by_update = asked.planned, asked.filters, asked.by_update
    with TRACER.start_as_current_span("search.lexical"):
        found = [reader.scores(each, filters, every=by_update) for each in planned.expressions]
        named = [*planned.identifiers.keys, *planned.identifiers.ids]
        keys, ids = planned.identifiers.keys, planned.identifiers.ids
        pinned = reader.entries(keys=keys, ids=ids, filters=filters)
        ordered = sorted(pinned, key=lambda e: named.index(e.front.key or e.front.id))
        first = [entry.path for entry in ordered]
        words = rank((one for one, _ in found), first, by_update=by_update)
        whole = all(every for _, every in found)
    if asked.mode == "lexical" or by_update:
        return Ranking(words, whole, {})
    with TRACER.start_as_current_span("search.semantic"):
        near = meaning.nearest(reader, asked.query, filters) if meaning else Nearest({}, NOT_SET_UP)
    if near.reason:
        FALLBACKS.add(1, {"aom.mode": asked.mode})
        structlog.get_logger().warning("search.fallback", mode=asked.mode, reason=near.reason)
        note = f" Ranked by words alone: {near.reason}."
        return Ranking(words, whole, {}, note=note)
    scores = {path: score for path, (score, *_) in near.found.items()}
    by_meaning = rank([scores], first, by_update=False)
    shown = {path: tuple(where) for path, (_, *where) in near.found.items()}
    if asked.mode == "semantic":
        return Ranking(by_meaning, whole=True, meaning=shown, counted="nearest in meaning")
    updated = {path: s.updated for one, _ in found for path, s in one.items()}
    updated |= {path: score.updated for path, score in scores.items()}
    # Both lists begin with the documents named; the rest is fused.
    fused = fuse([words[len(first) :], by_meaning[len(first) :]], updated)
    # A document that words do not find is ranked by meaning alone: shown by meaning.
    places = {path: at for at, path in enumerate(words)}
    higher = [path for at, path in enumerate(by_meaning) if at < places.get(path, math.inf)]
    by_higher = {path: shown[path] for path in higher if path in shown}
    return Ranking([*first, *fused], whole, by_higher, counted="found by words or meaning")


def passage_of(reader: Reader, entry: Entry, ranked: Ranking, planned: Plan) -> Passage:
    """Find the section to show for a document: by meaning or by words, as it was ranked.

    A document shown by words opens at its best section for the query's words; one
    without them, at its start, with a lead that leaves out the title's heading.
    """
    if entry.path in ranked.meaning:
        number, start, end = ranked.meaning[entry.path]
        lead = reader.text(entry.path, start, min(end, start + 2 * responses.SNIPPET))
        return Passage(number, reader.heading(entry.path, number), lead)
    passage = reader.passage(entry.path, planned.match) if planned.words else None
    lead = "" if passage else reader.text(entry.path, 0, 2 * responses.SNIPPET)
    return passage or Passage(1, "", lead.partition("\n")[2])


def excerpts(reader: Reader, ranked: Ranking, planned: Plan, paths: list[str]) -> list[Passage]:
    """Give the passage that ask quotes of each document, verbatim, in the order given.

    A document ranked by meaning gives the unit of its best piece, by the index's
    chunking; one ranked by words, its best section for the question's words, or its
    first, cut after its last line break within UNIT characters if longer, when that
    break falls in their second half.
    """
    embedded = reader.embedded()
    unit = CHUNKERS[embedded.chunking].unit if embedded else None
    found = []
    for path in paths:
        bounds = reader.bounds(path)
        if unit and path in ranked.meaning:
            number, start, end = ranked.meaning[path]
            first, last = unit((start, end), bounds[number - 1])
            text = reader.text(path, first, last)
        else:
            best = reader.passage(path, planned.match) if planned.words else None
            number = best.number if best else 1
            first, last = bounds[number - 1]
            text = reader.text(path, first, min(last, first + UNIT))
            text = text if last - first <= UNIT else text[: text.rfind("\n", UNIT // 2) + 1 or UNIT]
        found.append(Passage(number, reader.heading(path, number), text))
    return found


def checked(filters: SearchFilters | None) -> dict[str, str]:
    """Refuse a filter that is not one, or a value too long; give the filters given."""
    given: dict[str, str] = {**(filters or {})}
    if unknown := sorted(set(given) - SearchFilters.__optional_keys__):
        valid = ", ".join(sorted(SearchFilters.__optional_keys__))
        message = f"filters: no {', '.join(unknown)}; the filters are {valid}"
        raise UnanswerableError(message)
    bounded(**{name: (value, LONGEST["value"]) for name, value in given.items()})
    return given


def narrowed(reader: Reader, given: Mapping[str, str]) -> Filters:
    """Give the filters as the index holds their values, refusing one that no document has."""
    names = ("source", "space", "project", "status", "label")
    return Filters(
        **{name: canonical(reader, name, given.get(name)) for name in names},
        updated_after=instant("updated_after", given.get("updated_after")),
        updated_before=instant("updated_before", given.get("updated_before")),
    )


def bounded(**values: tuple[str | None, int]) -> None:
    """Refuse an argument longer than its limit, naming it."""
    for name, (value, limit) in values.items():
        if value is not None and len(value) > limit:
            message = f"{name}: at most {limit} characters"
            raise UnanswerableError(message)


def canonical(reader: Reader, name: str, value: str | None) -> str | None:
    """Find the value that the index holds for a filter, compared with ``casefold``.

    Refuse a value that no document has, listing the valid ones, the most used first.
    """
    if value is None:
        return None
    valid = reader.values(name)
    for candidate, _ in valid:
        if candidate.casefold() == value.casefold():
            return candidate
    message = f"{name}: no document has {json.dumps(value, ensure_ascii=False)}; the valid values:"
    shown = [candidate for candidate, _ in valid[:VALUES_SHOWN]]
    raise UnanswerableError(responses.refusal(message, shown, len(valid)))


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


def start_of(cursor: str | None, built_at: datetime) -> int:
    """Read a cursor that an answer gave: an offset, for the index built at that time."""
    if cursor is None:
        return 0
    offset, _, built = cursor.partition("@")
    if not offset.isascii() or not offset.isdigit() or not built:
        message = "cursor: give the one that the previous answer ended with"
        raise UnanswerableError(message)
    if built != built_at.strftime(CURSOR_TIME):
        message = "cursor: the index was rebuilt since; call again without the cursor"
        raise UnanswerableError(message)
    return int(offset)


def cursor_at(offset: int, built_at: datetime) -> str:
    """Write the cursor that continues a list at ``offset``, for this build of the index."""
    return f"{offset}@{built_at.strftime(CURSOR_TIME)}"


def clamp(value: int, limits: tuple[int, int]) -> int:
    """Bring a number within its limits, both included."""
    return max(limits[0], min(value, limits[1]))


@dataclass(frozen=True)
class Shown:
    """A document ranked for a query, with the section a search shows for it."""

    path: str
    section: int
    text: str  # the section's text, or the passage quoted, as the body holds it


class Library:
    """The four tools, over the index at one path."""

    def __init__(
        self, index: Path, docs: Path, meaning: Meaning | None = None, mode: Mode = "lexical"
    ) -> None:
        """Answer from the index at ``index``, built from the mirror at ``docs``.

        Search ranks in ``mode``; by meaning, through ``meaning``, when it is given.
        """
        self._index = index
        self._docs = docs
        self._meaning = meaning
        self._mode = mode

    @contextmanager
    def _reading(self) -> Iterator[Reader]:
        try:
            with reading(self._index) as reader:
                yield reader
        except UnavailableIndexError as error:
            raise UnanswerableError(str(error)) from None

    def _find(self, reader: Reader, ref: str) -> Entry | None:
        """Find a document by path, issue key, page id or address, in that preference."""
        named, path = identifiers(ref), ref.strip()
        found = reader.entries(paths=[path], keys=named.keys[:1], ids=named.ids[:1])
        return min(found, key=lambda entry: (entry.path != path, not entry.front.key), default=None)

    def search(
        self,
        query: str = "",
        filters: SearchFilters | None = None,
        sort: Literal["relevance", "updated"] = "relevance",
        limit: int = SEARCH_LIMIT,
        cursor: str | None = None,
    ) -> str:
        """Search the offline mirror of Confluence and Jira, the best documents first.

        Words match without regard to case or accents; issue keys, page ids and page
        addresses in the query put their documents first. With sort="updated" and no
        query, lists what changed last. Each hit gives the read() call of its best
        section; a long list ends with the call that continues it.
        """
        given = checked(filters)
        bounded(query=(query, LONGEST["query"]), cursor=(cursor, LONGEST["cursor"]))
        planned, by_update = plan(query), sort == "updated"
        with self._reading() as reader:
            built_at = reader.built_at()
            offset, size = start_of(cursor, built_at), clamp(limit, SEARCH_LIMITS)
            kept = narrowed(reader, given)
            if not planned.words and not by_update:
                return responses.answer(NO_WORDS)
            ranked = Ranking([], whole=True, meaning={})
            if planned.words:
                asked = Asked(query, planned, kept, by_update, self._mode)
                ranked = ranking(reader, self._meaning, asked)
                total, whole = len(ranked.paths), ranked.whole
                paths = ranked.paths[offset : offset + size]
                shown = sorted(reader.entries(paths=paths), key=lambda e: paths.index(e.path))
            else:
                (total, shown), whole = reader.recent(kept, offset, size), True
            # On the call's span, the SDK's: the mode, the documents found, whether words
            # stood in for meaning. Said here, as the docstring is the agent's to read.
            trace.get_current_span().set_attributes(
                {"aom.mode": self._mode, "aom.hits": total, "aom.fallback": bool(ranked.note)}
            )
            items = []
            for number, entry in enumerate(shown, offset + 1):
                passage = passage_of(reader, entry, ranked, planned)
                ref = entry.front.key or entry.front.id
                opening = responses.call(self.read, ref=ref, section=passage.number)
                items.append(responses.hit(number, entry, passage, opening))

        def more(count: int) -> str:
            after = cursor_at(offset + count, built_at)
            return responses.call(
                self.search, query=query, filters=filters, sort=sort, limit=limit, cursor=after
            )

        # A note on falling back to words lengthens the header: the hits make room for it.
        allowed = responses.budget(limit, SEARCH_LIMIT) - responses.tokens(ranked.note)
        count, footer = responses.page(items, total - offset, allowed, more)
        counted = f"Documents {ranked.counted}: {total if whole else f'at least {total}'}"
        header = f"{counted}; {responses.span(offset, count, built_at)}{ranked.note}"
        if planned.dropped:
            header += f" Only the first {MAX_WORDS} words of the query were searched."
        return responses.answer(header, "\n".join(items[:count]), footer)

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
        return self._asked(question, filters, cursor, self._mode)[0]

    def _asked(
        self, question: str, filters: SearchFilters | None, cursor: str | None, mode: Mode
    ) -> tuple[str, list[tuple[Entry, Passage]]]:
        """Write ask's answer in a mode, and give the documents and passages that it quotes."""
        given = checked(filters)
        bounded(question=(question, LONGEST["query"]), cursor=(cursor, LONGEST["cursor"]))
        planned = plan(question)
        with self._reading() as reader:
            built_at = reader.built_at()
            offset = start_of(cursor, built_at)
            asked = Asked(question, planned, narrowed(reader, given), by_update=False, mode=mode)
            if not planned.words:
                return responses.answer(NO_QUESTION), []
            ranked = ranking(reader, self._meaning, asked)
            paths = ranked.paths[offset : offset + ASK_DOCUMENTS]
            entries = {entry.path: entry for entry in reader.entries(paths=paths)}
            chosen = excerpts(reader, ranked, planned, paths)
        pairs = [(entries[path], passage) for path, passage in zip(paths, chosen, strict=True)]
        items = [
            responses.excerpt(
                number,
                entry,
                passage,
                responses.call(
                    self.read, ref=entry.front.key or entry.front.id, section=passage.number
                ),
            )
            for number, (entry, passage) in enumerate(pairs, offset + 1)
        ]

        def more(count: int) -> str:
            after = cursor_at(offset + count, built_at)
            return responses.call(self.ask, question=question, filters=filters, cursor=after)

        allowed = responses.BUDGET - responses.tokens(ranked.note)
        total = len(ranked.paths)
        count, footer = responses.page(items, total - offset, allowed, more)
        counted = f"Documents {ranked.counted}: {total if ranked.whole else f'at least {total}'}"
        header = f"{counted}; {responses.span(offset, count, built_at)}{ranked.note}"
        return responses.answer(header, "\n\n".join(items[:count]), footer), pairs[:count]

    def quoted(self, question: str, mode: Mode) -> list[Shown]:
        """Give the passages of ask's first answer in a mode, for an evaluation."""
        return [
            Shown(entry.path, passage.number, passage.snippet)
            for entry, passage in self._asked(question, None, None, mode)[1]
        ]

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
        planned = plan(query)
        with self._reading() as reader:
            asked = Asked(query, planned, Filters(), by_update=False, mode=mode)
            ranked = ranking(reader, self._meaning, asked)
            entries = {entry.path: entry for entry in reader.entries(paths=ranked.paths[:limit])}
            shown = []
            for path in ranked.paths[:limit]:
                number = passage_of(reader, entries[path], ranked, planned).number
                start, end = reader.bounds(path)[number - 1]
                shown.append(Shown(path, number, reader.text(path, start, end)))
        return shown, ranked.note

    def read(
        self,
        ref: str,
        section: int | None = None,
        offset: int | None = None,
        max_chars: int = READ_CHARS,
    ) -> str:
        """Read a mirrored document, or one of its sections, from a character offset.

        ref: a page id, an issue key, a page or issue address, or a path in the mirror.
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
        ref = entry.front.key or entry.front.id
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
            built_at = reader.built_at()
            offset = start_of(cursor, built_at)
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
            after = cursor_at(offset + count, built_at)
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
            summary = reader.summary()
        return responses.status(summary, self._docs)
