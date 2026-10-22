"""The mirror's front matter: one way to write it, read back the same, typed strictly."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.kernel.content import RefusedError
from atlassian_offline_mcp.kernel.fields import RepresentationError
from atlassian_offline_mcp.mirror.adapters.markdown import documents, dump, load
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter

if TYPE_CHECKING:
    from pathlib import Path

# The keys of data-layout.md's front-matter table, in its order.
LAYOUT_KEYS = [
    "source",
    "type",
    "id",
    "key",
    "title",
    "space",
    "project",
    "status",
    "issue_type",
    "labels",
    "author",
    "assignee",
    "created",
    "updated",
    "version",
    "revision",
    "url",
    "breadcrumb",
    "fetched_at",
]
MOMENT = datetime(2026, 10, 20, 21, 52, 41, 371000, tzinfo=UTC)
PAGE = FrontMatter(
    source="confluence",
    type="page",
    id="196845",
    key=None,
    title="Yes",
    space="MFS",
    project=None,
    status="current",
    issue_type=None,
    labels=("probe", "2026"),
    author="A Person",
    assignee=None,
    created=MOMENT,
    updated=MOMENT,
    version=3,
    revision="000003",
    url="https://site.example.invalid/wiki/spaces/MFS/pages/196845",
    breadcrumb=("Home", "Probes"),
    fetched_at=MOMENT,
)


def test_front_matter_has_the_layout_keys_in_order() -> None:
    """The file starts with the documented keys, in the documented order."""
    text = dump(PAGE, "# Yes\n")
    keys = [line.split(":", 1)[0] for line in text.split("---\n")[1].splitlines()]
    assert [key for key in keys if not key.startswith("-")] == LAYOUT_KEYS


def test_front_matter_reads_back_as_written() -> None:
    """Writing then reading gives the same front matter and body, to the second."""
    front_matter, body = load(dump(PAGE, "# Yes\n\nBody.\n"), "page.md")
    second = MOMENT.replace(microsecond=0)
    assert front_matter == replace(PAGE, created=second, updated=second, fetched_at=second)
    assert body == "# Yes\n\nBody.\n"


def test_strings_that_look_like_other_types_are_quoted() -> None:
    """000003, 196845, 2026, Yes and a time are written so that YAML reads strings."""
    text = dump(PAGE, "")
    for line in ("revision: '000003'", "id: '196845'", "title: 'Yes'", "- '2026'"):
        assert line in text
    assert "created: '2026-10-20T21:52:41Z'" in text


def test_a_time_written_unquoted_by_hand_is_refused() -> None:
    """A YAML timestamp is not the mirror's time: the field is refused by name."""
    text = dump(PAGE, "").replace(
        "created: '2026-10-20T21:52:41Z'", "created: 2026-10-20T21:52:41Z"
    )
    with pytest.raises(RepresentationError, match=r"^page\.md\.created: expected a string"):
        load(text, "page.md")


@pytest.mark.parametrize(
    ("old", "new"),
    [("status: current\n", ""), ("source: confluence\n", "extra: 1\nsource: confluence\n")],
)
def test_front_matter_with_other_keys_is_refused(old: str, new: str) -> None:
    """A missing, extra or moved key is not the mirror's front matter."""
    with pytest.raises(RepresentationError, match="exactly the mirror's keys"):
        load(dump(PAGE, "").replace(old, new), "page.md")


def test_a_file_without_front_matter_is_refused() -> None:
    """A Markdown file that does not start with front matter is not a document."""
    with pytest.raises(RepresentationError, match="no front matter"):
        load("# Title\n", "page.md")


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "issue"},
        {"revision": "3"},
        {"title": "Two\nlines"},
        {"title": "Two\u2028lines"},
        {"labels": ("one\x85two",)},
        {"key": "PRB-1"},
        {"version": None},
        {"assignee": "Someone"},
        {"created": MOMENT.astimezone(timezone(timedelta(hours=1)))},
    ],
)
def test_front_matter_off_its_rules_is_refused(changes: dict[str, object]) -> None:
    """A type of another source, a bad revision, a line break or a bad key is refused."""
    with pytest.raises(RefusedError):
        replace(PAGE, **changes)


def test_the_documents_are_exactly_the_pages_posts_and_issues(tmp_path: Path) -> None:
    """Trees, assets and hidden files are not documents."""
    for name in (
        "confluence/MFS/196845-probe.md",
        "confluence/MFS/blog/196900-news.md",
        "confluence/MFS/_tree.md",
        "confluence/MFS/.hidden.md",
        "confluence/.trash/blog/1-old.md",
        "jira/_drafts/PRB-9.md",
        "jira/PRB/PRB-1.md",
        "assets/0a1b.md",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", "utf-8")
    assert [path.relative_to(tmp_path).as_posix() for path in documents(tmp_path)] == [
        "confluence/MFS/196845-probe.md",
        "confluence/MFS/blog/196900-news.md",
        "jira/PRB/PRB-1.md",
    ]
