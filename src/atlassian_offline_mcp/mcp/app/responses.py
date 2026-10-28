"""How answers are written: compact Markdown within a budget of tokens.

Everything read from the index goes inside one block marked as untrusted reference
data; outside it stand only the server's own words. A list fills up to its budget and
the answer ends with the call that continues it. Nothing here reads the index.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from itertools import takewhile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from pathlib import Path

    from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter
    from atlassian_offline_mcp.search.domain.search import Entry, Passage, Summary

BUDGET = 4_000  # estimated tokens of an answer to arguments at or below their defaults
CEILING = 10_000  # estimated tokens of any answer
FIELD = 200  # characters of a one-line field or a heading, as shown
LABEL = 60
LABELS = 10
SNIPPET = 300
DEPTH = 10  # levels of indentation, at most
# Estimated tokens kept for an answer's header and the markers of its block.
RESERVE = 100
SPACES = re.compile(r"\s+")


def tokens(text: str) -> int:
    """Estimate the tokens of a text: one per 3 ASCII characters, one per other one."""
    other = sum(not char.isascii() for char in text)
    return -(-(len(text) + 2 * other) // 3)


def short(text: str, limit: int = FIELD) -> str:
    """Show a text from the site on one line, shortened to ``limit`` characters."""
    flat = SPACES.sub(" ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def stamp(moment: datetime) -> str:
    """Show a time to the minute, in UTC."""
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def answer(header: str, content: str = "", footer: str = "") -> str:
    """Put an answer together: the server's header, the block if any, then the footer.

    The block holds content read from the index, marked as untrusted. Its boundary is the
    start of the content's SHA-256, so the content cannot hold the closing marker but by
    a chance of 2^-64.
    """
    boundary = hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    block = (
        f'<untrusted-reference-data boundary="{boundary}">\n{content}\n'
        f'</untrusted-reference-data boundary="{boundary}">'
    )
    return "\n".join(part for part in (header, content and block, footer) if part)


def call(tool: Callable[..., str], **arguments: object) -> str:
    """Write a call of a tool, with the arguments that differ from its defaults.

    Values are JSON, which reads as Python too; a name that the tool does not take
    fails here, so calls stay in step with the tools' signatures.
    """
    parameters = inspect.signature(tool).parameters
    given = (
        f"{name}={json.dumps(value, ensure_ascii=False)}"
        for name, value in arguments.items()
        if value is not None and value != parameters[name].default
    )
    return f"{tool.__name__}({', '.join(given)})"


def budget(asked: int, default: int) -> int:
    """Give an answer's budget: the default one, unless more than the default was asked."""
    return BUDGET if asked <= default else CEILING


def page(
    items: Sequence[str], left: int, allowed: int, more: Callable[[int], str]
) -> tuple[int, str]:
    """Choose how many items, from the first, fit in a budget, one at least.

    ``left`` counts the items from the first to the end of the whole list, and
    ``more(count)`` writes the call that continues after ``count`` of them. Return the
    count, and the footer that ends a truncated answer, or "" when nothing is left.
    """
    room = allowed - RESERVE - tokens(more(len(items)))
    used, count = 0, len(items)
    for index, item in enumerate(items):
        used += tokens(item) + 1
        if used > room and index:
            count = index
            break
    return count, (f"More: {more(count)}" if count < left else "")


def span(offset: int, count: int, built_at: datetime) -> str:
    """Say which items of a list an answer shows, and when the index was built."""
    shown = f"{offset + 1} to {offset + count} below" if count else f"none from {offset + 1}"
    return f"{shown}. Index built {stamp(built_at)}."


def cut(text: str, budget: int) -> int:
    """Choose where a slice of a body ends, within the budget.

    The slice ends after a line break when one falls in the second half of what fits,
    and holds one character at least, so that reading always moves on.
    """
    thirds, fits = 0, len(text)
    for index, char in enumerate(text):
        thirds += 1 if char.isascii() else 3
        if thirds > 3 * budget:
            fits = index
            break
    fits = fits or min(1, len(text))
    if fits == len(text):
        return fits
    newline = text.rfind("\n", fits // 2, fits)
    return newline + 1 if newline >= 0 else fits


def refusal(message: str, values: Sequence[str], total: int) -> str:
    """Refuse a value, listing the valid ones, which come from the site."""
    more = f"\n({total - len(values)} more are not shown.)" if total > len(values) else ""
    return answer(message, ", ".join(short(value, LABEL) for value in values), more.strip())


def facts(front: FrontMatter) -> str:
    """Say what a document is, who it is for and from, and when it was created.

    Its issue type, its status unless current, its assignee (``unassigned`` for an issue
    with none), its author, its creator when named otherwise than its author, and its
    created day, leaving out what it lacks.
    """
    unassigned = "unassigned" if front.source == "jira" else ""
    creator = next((person.name for person in front.people if person.role == "creator"), None)
    shown = (
        short(front.issue_type, LABEL) if front.issue_type else "",
        "" if front.status == "current" else short(front.status, LABEL),
        f"assignee {short(front.assignee, LABEL)}" if front.assignee else unassigned,
        f"author {short(front.author, LABEL)}" if front.author else "",
        f"creator {short(creator, LABEL)}" if creator and creator != front.author else "",
        f"created {front.created:%Y-%m-%d}",
    )
    return " | ".join(part for part in shown if part)


def hit(number: int, entry: Entry, passage: Passage, opening: str) -> str:
    """Write one hit of a search: what and where it is, its best section and a snippet."""
    front = entry.front
    lines = [
        f"{number}. {short(front.title)}",
        (
            f"   {front.key or front.id} | {entry.path} | updated {stamp(front.updated)}"
            f" | mirrored {front.fetched_at:%Y-%m-%d} | {facts(front)}"
        ),
    ]
    if front.breadcrumb:
        lines.append(f"   in {short(' / '.join(front.breadcrumb))}")
    heading = f" {short(passage.heading)}" if passage.heading else ""
    lines.append(f"   section {passage.number}{heading}: {opening}")
    if snippet := short(passage.snippet, SNIPPET):
        lines.append(f"   > {snippet}")
    return "\n".join(lines)


def excerpt(number: int, entry: Entry, passage: Passage, opening: str) -> str:
    """Write one passage that ask quotes: what and where it is, then its text, verbatim.

    ``passage`` holds the text whole, where a search's holds a snippet.
    """
    front = entry.front
    heading = f": {short(passage.heading)}" if passage.heading else ""
    about = (
        f"{number}. {short(front.title)} | {front.key or front.id} | section"
        f" {passage.number}{heading} | updated {stamp(front.updated)}"
        f" | mirrored {front.fetched_at:%Y-%m-%d} | {facts(front)}"
    )
    return f"{about}\n{short(front.url or entry.path)} | {opening}\n{passage.snippet}"


def metadata(entry: Entry, *, whole: bool) -> str:
    """Write a document's front matter as one-line ``key: value`` lines.

    ``whole`` gives every key; otherwise the title, path and mirror date alone.
    """
    front = entry.front
    rows = [("title", front.title), ("path", entry.path), ("mirrored", stamp(front.fetched_at))]
    if whole:
        labels = ", ".join(short(label, LABEL) for label in front.labels[:LABELS])
        rows += [
            ("ref", front.key or front.id),
            ("type", front.type),
            ("space", front.space),
            ("project", front.project),
            ("issue type", front.issue_type),
            ("status", front.status),
            ("labels", labels),
            ("breadcrumb", " / ".join(front.breadcrumb)),
            ("author", front.author),
            ("assignee", front.assignee),
            ("created", stamp(front.created)),
            ("updated", stamp(front.updated)),
            ("url", front.url),
        ]
    return "\n".join(f"{key}: {short(value)}" for key, value in rows if value)


def tree(pairs: Sequence[tuple[tuple[str, ...], Entry]], base: int) -> list[str]:
    """Write each document of a tree as one item, indented by its depth below ``base``.

    Ancestors not listed before it, in this list, come first as one context line in
    brackets: folders, documents not mirrored, or, for the first item, documents
    listed on an earlier page.
    """
    items: list[str] = []
    previous: tuple[str, ...] = ()
    for path, entry in pairs:
        ancestors = path[base:-1]
        shared = zip(previous, ancestors, strict=False)
        common = sum(1 for _ in takewhile(lambda pair: pair[0] == pair[1], shared))
        front = entry.front
        line = (
            f"{'  ' * min(len(ancestors), DEPTH)}- {short(front.title)} ({front.key or front.id},"
            f" updated {front.updated:%Y-%m-%d}, mirrored {front.fetched_at:%Y-%m-%d})"
        )
        if missing := ancestors[common:]:
            line = f"{'  ' * min(common, DEPTH)}- [{short(' / '.join(missing))}]\n{line}"
        items.append(line)
        previous = path[base:]
    return items


def status(summary: Summary, docs: Path) -> str:
    """Say what the index holds, and when it was built."""

    def counts(values: dict[str, int]) -> str:
        return ", ".join(f"{name} {count}" for name, count in values.items()) or "none"

    lines = [
        f"built: {stamp(summary.built_at)}",
        f"documents: {counts(summary.types)}; sections: {summary.sections}",
        (
            f"search by meaning: {summary.model}, {summary.pieces} pieces cut by {summary.chunking}"
            if summary.model
            else "search by meaning: off, the index holds no vectors"
        ),
        f"spaces: {counts(summary.spaces)}",
        f"projects: {counts(summary.projects)}",
        f"files skipped at build: {summary.skipped}",
        f"newest mirror date: {stamp(summary.newest_fetch) if summary.newest_fetch else 'none'}",
        f"mirror files: {docs}",
    ]
    return answer("The index of the offline mirror.", "\n".join(lines))
