"""The tools of the MCP server, as the methods of one library over the index.

A method's name, parameters and defaults are its tool's schema, and continuation calls
are written from them, so the two never drift apart. Each call opens the index for
itself, so a rebuilt index is read from the next call on. A call that cannot be
answered as asked raises ``UnanswerableError``, whose message says what would do.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, TypedDict

from atlassian_offline_mcp.adapters.sqlite_index import UnavailableIndexError, reading
from atlassian_offline_mcp.app import responses
from atlassian_offline_mcp.domain.search import (
    MAX_WORDS,
    Filters,
    Passage,
    identifiers,
    plan,
    rank,
    tree_key,
    tree_paths,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from atlassian_offline_mcp.adapters.sqlite_index import Reader
    from atlassian_offline_mcp.domain.search import Entry

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
NOT_MIRRORED = (
    "Not mirrored: the mirror holds no such document. It holds what was downloaded;"
    " status() says which spaces and projects, and search() finds by words."
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


class UnanswerableError(Exception):
    """A call that cannot be answered as asked; the message says what would do."""


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


class Library:
    """The four tools, over the index at one path."""

    def __init__(self, index: Path, docs: Path) -> None:
        """Answer from the index at ``index``, built from the mirror at ``docs``."""
        self._index = index
        self._docs = docs

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
        given: dict[str, str] = {**(filters or {})}
        if unknown := sorted(set(given) - SearchFilters.__optional_keys__):
            valid = ", ".join(sorted(SearchFilters.__optional_keys__))
            message = f"filters: no {', '.join(unknown)}; the filters are {valid}"
            raise UnanswerableError(message)
        bounded(query=(query, LONGEST["query"]), cursor=(cursor, LONGEST["cursor"]))
        bounded(**{name: (value, LONGEST["value"]) for name, value in given.items()})
        planned, by_update = plan(query), sort == "updated"
        with self._reading() as reader:
            built_at = reader.built_at()
            offset, size = start_of(cursor, built_at), clamp(limit, SEARCH_LIMITS)
            names = ("source", "space", "project", "status", "label")
            narrowed = Filters(
                **{name: canonical(reader, name, given.get(name)) for name in names},
                updated_after=instant("updated_after", given.get("updated_after")),
                updated_before=instant("updated_before", given.get("updated_before")),
            )
            if not planned.words and not by_update:
                return responses.answer(NO_WORDS)
            if planned.words:
                found = [reader.scores(e, narrowed, every=by_update) for e in planned.expressions]
                named = [*planned.identifiers.keys, *planned.identifiers.ids]
                keys, ids = planned.identifiers.keys, planned.identifiers.ids
                pinned = reader.entries(keys=keys, ids=ids, filters=narrowed)
                pinned.sort(key=lambda entry: named.index(entry.front.key or entry.front.id))
                order = rank(
                    (one for one, _ in found), [e.path for e in pinned], by_update=by_update
                )
                total, whole = len(order), all(every for _, every in found)
                paths = order[offset : offset + size]
                shown = sorted(reader.entries(paths=paths), key=lambda e: paths.index(e.path))
            else:
                (total, shown), whole = reader.recent(narrowed, offset, size), True
            items = []
            for number, entry in enumerate(shown, offset + 1):
                passage = reader.passage(entry.path, planned.match) if planned.words else None
                # A body starts with its title's heading, which the lead leaves out.
                lead = "" if passage else reader.text(entry.path, 0, 2 * responses.SNIPPET)
                passage = passage or Passage(1, "", lead.partition("\n")[2])
                ref = entry.front.key or entry.front.id
                opening = responses.call(self.read, ref=ref, section=passage.number)
                items.append(responses.hit(number, entry, passage, opening))

        def more(count: int) -> str:
            after = cursor_at(offset + count, built_at)
            return responses.call(
                self.search, query=query, filters=filters, sort=sort, limit=limit, cursor=after
            )

        allowed = responses.budget(limit, SEARCH_LIMIT)
        count, footer = responses.page(items, total - offset, allowed, more)
        counted = f"Documents found: {total if whole else f'at least {total}'}"
        header = f"{counted}; {responses.span(offset, count, built_at)}"
        if planned.dropped:
            header += f" Only the first {MAX_WORDS} words of the query were searched."
        return responses.answer(header, "\n".join(items[:count]), footer)

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
