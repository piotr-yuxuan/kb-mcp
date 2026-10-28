"""Test mirrors: documents written where the data layout puts them, with the shared codec.

Values are made up. Filler documents speak lorem ipsum, so that no word under test is in
half the sections of the index, where FTS5 would count it as worthless.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.content import time_revision
from atlassian_offline_mcp.mirror.adapters.markdown import dump
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter

if TYPE_CHECKING:
    from pathlib import Path

MOMENT = datetime(2026, 10, 20, 21, 52, 41, tzinfo=UTC)
LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer posuere erat a ante "
    "venenatis dapibus posuere velit aliquet. Cras mattis consectetur purus sit amet "
    "fermentum. Vivamus sagittis lacus vel augue laoreet rutrum faucibus dolor auctor."
)
FILLERS = 30
WORKLOG_FOLDERS = {"entry": "entries", "transcript": "transcripts"}


def page(page_id: str, title: str, **changes: object) -> FrontMatter:
    """Return the front matter of a Confluence page of the space ENG."""
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
        author="A Person",
        assignee=None,
        created=MOMENT,
        updated=MOMENT,
        version=1,
        revision="000001",
        url=None,
        breadcrumb=(),
        fetched_at=MOMENT,
    )
    return replace(front, **changes)


def issue(key: str, title: str, *, updated: datetime = MOMENT, **changes: object) -> FrontMatter:
    """Return the front matter of a Jira issue, its project taken from its key."""
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
        author="A Person",
        assignee=None,
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
