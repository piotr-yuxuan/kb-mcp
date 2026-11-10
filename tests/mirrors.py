"""Test mirrors: documents written where the data layout puts them, with the shared codec.

Values are made up. Filler documents speak lorem ipsum, so that no word under test is in
half the sections of the index, where FTS5 would count it as worthless.
``prepared_sources`` prepares each Atlassian source, and ``prepared_source`` one, with a function
of a test's own in pandoc's place.
"""

from __future__ import annotations

import re
import unicodedata
from copy import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.markdown import dump
from kb_mcp.mirror.domain.mirror import FrontMatter, Link, Mention
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.domain.content import DOCUMENT_CLASSES, time_revision
from kb_mcp.sources.atlassian.prepare.app.prepare import prepare_atlassian
from kb_mcp.sources.registry import SOURCES

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from kb_mcp.kernel.outcome import Outcome
    from kb_mcp.sources.atlassian.prepare.app.prepare import AtlassianCounts

# The registry's Atlassian sources, by name, each with its connector's document classes.
ATLASSIAN = {
    each.name: tuple(
        known for known in DOCUMENT_CLASSES if known.document_type in each.connector.document_types
    )
    for each in SOURCES
    if each.connector.account is not None
}
MOMENT = datetime(2026, 10, 20, 21, 52, 41, tzinfo=UTC)
LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer posuere erat a ante "
    "venenatis dapibus posuere velit aliquet. Cras mattis consectetur purus sit amet "
    "fermentum. Vivamus sagittis lacus vel augue laoreet rutrum faucibus dolor auctor."
)
FILLERS = 30
WORKLOG_FOLDERS = {
    "entry": "entries",
    "day": "days",
    "meeting": "meetings",
    "transcript": "transcripts",
}


def named(author: str | None, assignee: str | None = None) -> tuple[Mention, ...]:
    """Give the people of a document by its author and its assignee, each when named."""
    return tuple(
        Mention(role=role, name=name)
        for role, name in (("author", author), ("assignee", assignee))
        if name is not None
    )


def page(
    page_id: str, title: str, *, author: str | None = "A Person", **changes: object
) -> FrontMatter:
    """Return the front matter of a Confluence page of the space ENG, by ``author``.

    ``people`` among the changes replaces the author.
    """
    front = FrontMatter(
        source="confluence",
        type="page",
        id=page_id,
        key=None,
        title=title,
        space="ENG",
        project=None,
        status="current",
        issue_type=None,
        labels=(),
        people=named(author),
        links=(),
        created=MOMENT,
        updated=MOMENT,
        version=1,
        revision="000001",
        url=None,
        breadcrumb=(),
        fetched_at=MOMENT,
    )
    return replace(front, **changes)


def issue(
    key: str,
    title: str,
    *,
    updated: datetime = MOMENT,
    author: str | None = "A Person",
    assignee: str | None = None,
    **changes: object,
) -> FrontMatter:
    """Return the front matter of a Jira issue, its project taken from its key.

    ``people`` among the changes replaces the author and the assignee.
    """
    project, number = key.rsplit("-", 1)
    front = FrontMatter(
        source="jira",
        type="issue",
        id=str(10000 + int(number)),
        key=key,
        title=title,
        space=None,
        project=project,
        status="To Do",
        issue_type="Task",
        labels=(),
        people=named(author, assignee),
        links=(),
        created=MOMENT,
        updated=updated,
        version=None,
        revision=time_revision(updated),
        url=None,
        breadcrumb=(),
        fetched_at=MOMENT,
    )
    return replace(front, **changes)


def location(front: FrontMatter) -> str:
    """Name a document's file, relative to <data>/docs, as the data layout does."""
    if front.source == "jira":
        return f"jira/{front.project}/{front.key}.md"
    if front.type in {"day", "meeting"}:
        return f"worklog/{WORKLOG_FOLDERS[front.type]}/{front.id}.md"
    decomposed = unicodedata.normalize("NFKD", front.title).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", decomposed).strip("-")[:60].rstrip("-")
    name = f"{front.id}-{slug}.md" if slug else f"{front.id}.md"
    if front.source == "worklog":
        return f"worklog/{WORKLOG_FOLDERS[front.type]}/{name}"
    folder = "blog/" if front.type == "blogpost" else ""
    return f"confluence/{front.space}/{folder}{name}"


def write(docs: Path, front: FrontMatter, body: str | None = None) -> str:
    """Write a document into the mirror at ``docs``; return its path relative to it."""
    path = location(front)
    text = f"# {front.title}\n\n{LOREM}\n" if body is None else body
    (docs / path).parent.mkdir(parents=True, exist_ok=True)
    (docs / path).write_text(dump(front, text), encoding="utf-8")
    return path


def prepared_source(
    store: RawStore, docs: Path, site: str | None, convert: Callable[[str], str], source: str
) -> Outcome[AtlassianCounts]:
    """Mirror one source of the store that ``store`` views into ``docs``; give its outcome.

    Among ``ATLASSIAN``, as the preparer does.

    It converts by ``convert`` through its rows of the cache beside ``docs``, the file
    of the data layout, ``conversions.sqlite``, which each Atlassian source adopts, as the
    preparer has it. It names ``convert`` by its qualified name, as pandoc's version and
    arguments name pandoc's conversion, so that two functions never answer for each other.
    """
    path = docs.parent / "conversions.sqlite"
    with conversions.opened(
        path, lambda: convert.__qualname__, convert, source=source, adopted=tuple(ATLASSIAN)
    ) as cache:
        return prepare_atlassian(RawStore(store.root, source), docs, site, cache, ATLASSIAN)


def prepared_sources(
    store: RawStore, docs: Path, site: str | None, convert: Callable[[str], str]
) -> dict[str, Outcome[AtlassianCounts]]:
    """Mirror ``store`` into ``docs``, each source as a run does; give its outcome by its name."""
    return {source: prepared_source(store, docs, site, convert, source) for source in ATLASSIAN}


def fillers(docs: Path, count: int = FILLERS) -> None:
    """Write pages of lorem ipsum, older than MOMENT, each with a few sections."""
    for number in range(count):
        older = MOMENT - timedelta(days=number + 1)
        front = page(str(900000 + number), f"Lorem {number}", updated=older)
        write(docs, front, f"# Lorem {number}\n\n{LOREM}\n\n## Ipsum\n\n{LOREM}\n")


# Midnight UTC: where a created range given as the date 2026-10-25 starts or ends.
CREATED = datetime(2026, 10, 25, tzinfo=UTC)
# Made-up people on three issues and a page, each titled with "Broker", all created
# after the fillers. Newest created first: PROJ-3 and PROJ-1, a tie that PROJ-3's later
# update breaks, then PROJ-2, then the page; newest updated first: PROJ-2, PROJ-3,
# PROJ-1, the page. The label "resume" twice, "résumé" once.
PEOPLE = (
    issue(
        "PROJ-1",
        "Broker crash",
        updated=CREATED + timedelta(hours=1),
        issue_type="Bug",
        status="Done",
        author="Bo Sample",
        assignee="Ada Example",
        created=CREATED,
    ),
    issue(
        "PROJ-2",
        "Broker disk alert",
        updated=CREATED + timedelta(hours=3),
        author="Ada Example",
        assignee="Hélène Example",
        created=CREATED - timedelta(days=3),
        labels=("resume",),
    ),
    issue(
        "PROJ-3",
        "Broker retention",
        updated=CREATED + timedelta(hours=2),
        issue_type="Story",
        assignee="Ada Example",
        created=CREATED,
        labels=("resume",),
    ),
    page(
        "196845",
        "Broker runbook",
        author="Bo Sample",
        created=CREATED - timedelta(days=4),
        updated=CREATED - timedelta(days=1),
        labels=("résumé",),
    ),
)


def worklog_document(
    document_type: str,
    document_id: str,
    title: str,
    names: Sequence[str],
    linked: str | None = None,
) -> FrontMatter:
    """Return the front matter of a work-log meeting or transcript, naming its participants.

    ``linked`` is the id of the transcript that a meeting links to, or of the meeting
    that a transcript is the record of, if any.
    """
    relation = "transcript" if document_type == "meeting" else "summary"
    return replace(
        page(document_id, title),
        source="worklog",
        type=document_type,
        space=None,
        version=None,
        revision="0123456789abcdef",
        people=tuple(Mention(role="participant", name=name) for name in names),
        links=() if linked is None else (Link(relation=relation, ref=linked),),
    )


# Made-up people across three sources, as plan 043's join rules them. Robin Example's
# account, acct-0001, writes the name Robin Sample on its newest document, PAY-1, and
# comments twice on PAY-2; two accounts are named Sam Sample. The work log names them
# without an account, and its transcripts by first name alone: three of them the
# records of a meeting each, two of none. Files come in the order of their paths, so
# the meetings before the transcripts.
PERSONS = (
    page(
        "300001",
        "Ledger runbook",
        people=(Mention(role="author", name="Robin Example", identity="atlassian:acct-0001"),),
    ),
    issue(
        "PAY-1",
        "Ledger export",
        updated=MOMENT + timedelta(days=1),
        people=(
            Mention(role="author", name="Sam Sample", identity="atlassian:acct-0002"),
            Mention(role="creator", name="Robin Sample", identity="atlassian:acct-0001"),
        ),
    ),
    issue(
        "PAY-2",
        "Ledger rounding",
        people=(
            Mention(role="author", name="Sam Sample", identity="atlassian:acct-0003"),
            Mention(
                role="commenter",
                name="Robin Example",
                identity="atlassian:acct-0001",
                at=(MOMENT, MOMENT + timedelta(hours=1)),
            ),
        ),
    ),
    worklog_document(
        "meeting",
        "m-20261020-planning",
        "Planning",
        ("Robin Example", "Robin Other"),
        "t-20261020-2",
    ),
    worklog_document(
        "meeting", "m-20261020-review", "Review", ("Robin Example", "Alex Example"), "t-20261020-1"
    ),
    worklog_document(
        "meeting",
        "m-20261020-stand-up",
        "Stand-up",
        ("robin  EXAMPLE", "Sam Sample", "Alex Example (not in the header)"),
        "t-20261020-3",
    ),
    worklog_document(
        "transcript", "t-20261020-1", "Review", ("Robin", "Alex"), "m-20261020-review"
    ),
    worklog_document("transcript", "t-20261020-2", "Planning", ("Robin",), "m-20261020-planning"),
    worklog_document("transcript", "t-20261020-3", "Stand-up", ("Sam",), "m-20261020-stand-up"),
    worklog_document("transcript", "t-20261021-1", "Pairing", ("Robin", "Alex")),
    worklog_document("transcript", "t-20261021-2", "Ledger chat", ("Alex",)),
)
