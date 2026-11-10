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

from kb_mcp.mirror.domain.mirror import RELATIONS, ROLES, ref_of
from kb_mcp.search.domain import people

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from pathlib import Path

    from kb_mcp.mirror.domain.mirror import FrontMatter
    from kb_mcp.search.domain.search import Activity, IndexedDocument, IndexStatus, Passage

BUDGET = 4_000  # estimated tokens of an answer to arguments at or below their defaults
CEILING = 10_000  # estimated tokens of any answer
FIELD = 200  # characters of a one-line field or a heading, as shown
LABEL = 60
LABELS = 10
NAMES = 10  # names of one role that a read shows, then how many more
SHARED = 5  # names of several identities that status shows, then how many more
SNIPPET = 300
DEPTH = 10  # levels of indentation, at most
# Estimated tokens kept for an answer's header and the markers of its block.
RESERVE = 100
SPACES = re.compile(r"\s+")
# How each name of a person joined them, as a person's answer says it.
JOINED = {
    people.BY_IDENTITY: "by its identity",
    people.BY_ALIAS: "by an alias",
    people.BY_NAME: "by name",
    people.BY_ATTENDANCE: "by attendance",
}


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


def activity(found: Activity) -> str:
    """Say who a person is and what they did, on one line.

    Their name and id, their documents by role then by source, the most first, and the
    day of the last update of one, such as
    ``Sam Sample, p-0123456789abcdef: author 1; jira 1; last updated 2026-10-20``.
    """
    roles = ", ".join(f"{role} {count}" for role, count in found.roles.items())
    sources = ", ".join(f"{source} {count}" for source, count in found.sources.items())
    return (
        f"{short(found.person.name, LABEL)}, {found.person.id}: {roles}; {sources};"
        f" last updated {found.last:%Y-%m-%d}"
    )


def person(found: Activity, alike: Sequence[tuple[str, str]]) -> str:
    """Write the person that an answer is narrowed to, before its documents, on a few lines.

    Who they are and what they did, as ``activity`` says it; their names as the sources
    write them, by how each joined, in the order of JOINED, NAMES at most, then how many
    more; then, NAMES at most, each person by name alone who is perhaps the same, not
    joined, given as the name that an alias would hold and their id, with the line of
    the alias file that would join them. Each name is cut at LABEL characters, as a
    hit's.
    """
    order = list(JOINED)
    names = sorted(found.person.spellings, key=lambda each: order.index(each.how))
    ways = [
        (said, [short(each.name, LABEL) for each in names[:NAMES] if each.how == how])
        for how, said in JOINED.items()
    ]
    more = f"; {len(names) - NAMES} more" if len(names) > NAMES else ""
    written = "; ".join(f"{', '.join(spelt)} {said}" for said, spelt in ways if spelt)
    lines = [f"Person: {activity(found)}.", f"Names: {written}{more}."]
    lines += [
        f"Perhaps the same, not joined: {other}; the alias"
        f" {json.dumps(short(name, LABEL), ensure_ascii=False)}"
        f" = {json.dumps(found.person.id)} would join them."
        for name, other in alike[:NAMES]
    ]
    return "\n".join(lines)


def roles(name: str, held: Sequence[tuple[str, int, datetime | None]]) -> str:
    """Say a person's roles on one document, in the order of the roles.

    A commenter's with their comments' count and the day of the last, such as
    ``Sam Sample: creator, commenter 2 (last 2026-10-21)``.
    """
    shown = (
        role if last is None else f"{role} {count} (last {last:%Y-%m-%d})"
        for role, count, last in sorted(held, key=lambda each: ROLES.index(each[0]))
    )
    return f"{short(name, LABEL)}: {', '.join(shown)}"


def facts(front: FrontMatter) -> str:
    """Say what a document is, who it is for and from, and when it was created.

    Its issue type, its status unless current, its assignee (``unassigned`` for an issue
    with none), its author, its creator when named otherwise than its author, and its
    created day, leaving out what it lacks.
    """
    unassigned = "unassigned" if front.source == "jira" else ""
    creator = front.creator
    shown = (
        short(front.issue_type, LABEL) if front.issue_type else "",
        "" if front.status == "current" else short(front.status, LABEL),
        f"assignee {short(front.assignee, LABEL)}" if front.assignee else unassigned,
        f"author {short(front.author, LABEL)}" if front.author else "",
        f"creator {short(creator, LABEL)}" if creator and creator != front.author else "",
        f"created {front.created:%Y-%m-%d}",
    )
    return " | ".join(part for part in shown if part)


def dated(front: FrontMatter, held: str | None) -> str:
    """Say when a ranked document was updated and mirrored, what it is, and who holds it.

    ``held``, unless None, ends it: a person's roles there, as ``roles`` says them.
    """
    when = f"updated {stamp(front.updated)} | mirrored {front.fetched_at:%Y-%m-%d}"
    return f"{when} | {facts(front)}" + (f" | {held}" if held else "")


def hit(
    number: int, entry: IndexedDocument, passage: Passage, opening: str, held: str | None
) -> str:
    """Write one hit of a search: what and where it is, its best section and a snippet."""
    front = entry.front
    lines = [
        f"{number}. {short(front.title)}",
        f"   {ref_of(front.key, front.id)} | {entry.path} | {dated(front, held)}",
    ]
    if front.breadcrumb:
        lines.append(f"   in {short(' / '.join(front.breadcrumb))}")
    heading = f" {short(passage.heading)}" if passage.heading else ""
    lines.append(f"   section {passage.number}{heading}: {opening}")
    if snippet := short(passage.text, SNIPPET):
        lines.append(f"   > {snippet}")
    return "\n".join(lines)


def passage(
    number: int, entry: IndexedDocument, passage: Passage, opening: str, held: str | None
) -> str:
    """Write one passage that ask quotes: what and where it is, then its text, verbatim.

    ``passage`` holds the text whole, where a search's holds a snippet.
    """
    front = entry.front
    heading = f": {short(passage.heading)}" if passage.heading else ""
    about = (
        f"{number}. {short(front.title)} | {ref_of(front.key, front.id)} | section"
        f" {passage.number}{heading} | {dated(front, held)}"
    )
    return f"{about}\n{short(front.url or entry.path)} | {opening}\n{passage.text}"


def metadata(entry: IndexedDocument, *, whole: bool) -> str:
    """Write a document's front matter as one-line ``key: value`` lines.

    ``whole`` gives every key that a reader needs, but the source, id, key, version and
    revision that the ref and the dates stand for; otherwise the title, path and mirror
    date alone. People
    come by name alone, one line per role in the order of the roles: NAMES names at
    most, then how many more, each commenter with their comments' count and the day of
    the last. Links come by ref, one line per relation in the order of the relations:
    LABELS refs at most, then how many more. A role's or a relation's line is not cut as a
    value is, so that the count of the rest stays; each name or ref in it is, so that a
    name that a hit cuts comes whole.
    """
    front = entry.front
    rows = [("title", front.title), ("path", entry.path), ("mirrored", stamp(front.fetched_at))]
    if whole:
        labels = ", ".join(short(label, LABEL) for label in front.labels[:LABELS])
        rows += [
            ("ref", ref_of(front.key, front.id)),
            ("type", front.type),
            ("space", front.space),
            ("project", front.project),
            ("issue type", front.issue_type),
            ("status", front.status),
            ("labels", labels),
            ("breadcrumb", " / ".join(front.breadcrumb)),
        ]
        for role in ROLES:
            held = [person for person in front.people if person.role == role]
            names = [
                short(person.name)
                + (f" ({len(person.at)}, last {person.at[-1]:%Y-%m-%d})" if person.at else "")
                for person in held[:NAMES]
            ]
            more = f"; {len(held) - NAMES} more" if len(held) > NAMES else ""
            rows.append((role, "; ".join(names) + more))
        for relation in RELATIONS:
            refs = [short(link.ref) for link in front.links if link.relation == relation]
            more = f"; {len(refs) - LABELS} more" if len(refs) > LABELS else ""
            rows.append((relation, "; ".join(refs[:LABELS]) + more))
        rows += [
            ("created", stamp(front.created)),
            ("updated", stamp(front.updated)),
            ("url", front.url),
        ]
    uncut = {*ROLES, *RELATIONS}
    return "\n".join(
        f"{key}: {value if key in uncut else short(value)}" for key, value in rows if value
    )


def tree(pairs: Sequence[tuple[tuple[str, ...], IndexedDocument]], base: int) -> list[str]:
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
            f"{'  ' * min(len(ancestors), DEPTH)}- {short(front.title)}"
            f" ({ref_of(front.key, front.id)}, updated {front.updated:%Y-%m-%d},"
            f" mirrored {front.fetched_at:%Y-%m-%d})"
        )
        if missing := ancestors[common:]:
            line = f"{'  ' * min(common, DEPTH)}- [{short(' / '.join(missing))}]\n{line}"
        items.append(line)
        previous = path[base:]
    return items


def status(state: IndexStatus, docs: Path) -> str:
    """Say what the index holds, and when it was built.

    Its persons on one line: how many, in more than one source, and by name alone; then
    SHARED at most of the names of several identities, each with the persons holding it,
    and how many more, so that the agent knows which names to ask about by id.
    """

    def counts(values: dict[str, int]) -> str:
        return ", ".join(f"{name} {count}" for name, count in values.items()) or "none"

    persons = state.persons
    shared = ", ".join(
        f"{json.dumps(short(name, LABEL), ensure_ascii=False)} ({count})"
        for name, count in persons.shared[:SHARED]
    )
    rest = len(persons.shared) - SHARED

    lines = [
        f"built: {stamp(state.built_at)}",
        f"documents: {counts(state.types)}; sections: {state.sections}",
        (
            f"search by meaning: {state.model}, {state.chunks} chunks cut by {state.chunking}"
            if state.model
            else "search by meaning: off, the index holds no vectors; run kb-mcp embed"
        ),
        f"spaces: {counts(state.spaces)}",
        f"projects: {counts(state.projects)}",
        (
            f"persons: {persons.count}, {persons.across} in more than one source,"
            f" {persons.alone} by name alone"
            + (f"; names of several identities: {shared}" if shared else "")
            + (f", and {rest} more" if rest > 0 else "")
        ),
        f"files skipped at build: {state.skipped}",
        f"newest mirror date: {stamp(state.newest_fetch) if state.newest_fetch else 'none'}",
        f"mirror files: {docs}",
    ]
    return answer("The index of the offline mirror.", "\n".join(lines))
