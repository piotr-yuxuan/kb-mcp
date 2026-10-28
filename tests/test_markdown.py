"""The mirror's front matter: one way to write it, read back the same, typed strictly."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.kernel.content import RefusedError
from atlassian_offline_mcp.kernel.fields import RepresentationError
from atlassian_offline_mcp.mirror.adapters.markdown import documents, dump, load
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter, PersonRole

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
    "people",
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
    people=(PersonRole(role="author", name="A Person"),),
    created=MOMENT,
    updated=MOMENT,
    version=3,
    revision="000003",
    url="https://site.example.invalid/wiki/spaces/MFS/pages/196845",
    breadcrumb=("Home", "Probes"),
    fetched_at=MOMENT,
)


ENTRY = FrontMatter(
    source="worklog",
    type="entry",
    id="e-0123456789abcdef-2",
    key=None,
    title="Retrospective notes",
    space=None,
    project=None,
    status="WAITING",
    issue_type=None,
    labels=("review", "ARCHIVE"),
    created=MOMENT,
    updated=MOMENT,
    version=None,
    revision="0123456789abcdef",
    url=None,
    breadcrumb=("todo.org_archive",),
    fetched_at=MOMENT,
)


EARLY = datetime(2026, 10, 20, 9, 12, tzinfo=UTC)
LATE = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
ISSUE = FrontMatter(
    source="jira",
    type="issue",
    id="10000",
    key="PRB-1",
    title="What are archived ideas?",
    space=None,
    project="PRB",
    status="Parking lot",
    issue_type="Idea",
    labels=(),
    people=(
        PersonRole(role="author", name="A Person", account="account-1"),
        PersonRole(role="creator", name="Another Person", account="account-2"),
        PersonRole(role="assignee", name="A Person", account="account-1"),
        PersonRole(role="commenter", name="Another Person", account="account-2", at=(EARLY, LATE)),
        PersonRole(role="commenter", name="A Person", account="account-1", at=(LATE,)),
    ),
    created=MOMENT,
    updated=MOMENT,
    version=None,
    revision="20261020T215241.371000Z",
    url=None,
    breadcrumb=("PRB-3",),
    fetched_at=MOMENT,
)
# The people of ISSUE as the layout writes them: each entry one line, in flow style.
PEOPLE = (
    "people:\n"
    "- {role: author, name: A Person, account: account-1}\n"
    "- {role: creator, name: Another Person, account: account-2}\n"
    "- {role: assignee, name: A Person, account: account-1}\n"
    "- {role: commenter, name: Another Person, account: account-2,"
    " at: ['2026-10-20T09:12:00Z', '2026-10-21T08:00:00Z']}\n"
    "- {role: commenter, name: A Person, account: account-1, at: ['2026-10-21T08:00:00Z']}\n"
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


def test_people_in_every_role_read_back_byte_for_byte() -> None:
    """Each person on one line, by role, with an account id and a commenter's times."""
    text = dump(ISSUE, "# What are archived ideas?\n")
    assert f"labels: []\n{PEOPLE}created: " in text
    front_matter, body = load(text, "issue.md")
    assert dump(front_matter, body) == text
    second = MOMENT.replace(microsecond=0)
    assert front_matter == replace(ISSUE, created=second, updated=second, fetched_at=second)
    assert (front_matter.author, front_matter.assignee) == ("A Person", "A Person")


def test_an_account_and_people_are_left_out_when_the_source_has_none() -> None:
    """No account without an account id, ``[]`` without people; the properties say nobody."""
    assert "people:\n- {role: author, name: A Person}\ncreated: " in dump(PAGE, "")
    assert "people: []\n" in dump(ENTRY, "")
    assert (ENTRY.author, ENTRY.assignee) == (None, None)
    assert (PAGE.author, PAGE.assignee) == ("A Person", None)


@pytest.mark.parametrize(
    ("old", "new", "refusal"),
    [
        ("role: creator", "role: reviewer", r"people\[1\]: role: not one of the roles"),
        ("account: account-2}", "account: account-2, email: x}", r"people\[1\]: fields other"),
        (
            "{role: creator, name: Another Person",
            "{name: Another Person, role: creator",
            r"people\[1\]: fields other",
        ),
        ("role: creator", "role: author", r"^issue\.md: people: a second author"),
        ("role: assignee", "role: creator", r"^issue\.md: people: a second author"),
        ("role: creator", "role: assignee", r"^issue\.md: people: a second author"),
        (
            "name: A Person, account: account-1, at",
            "name: Another Person, account: account-2, at",
            r"^issue\.md: people: .* a commenter twice",
        ),
        (
            "account: account-1}",
            "account: account-1, at: ['2026-10-20T09:12:00Z']}",
            r"people\[0\]: at: only and always for a commenter",
        ),
        (
            "at: ['2026-10-21T08:00:00Z']}",
            "at: []}",
            r"people\[4\]: at: only and always for a commenter",
        ),
        (
            "'2026-10-21T08:00:00Z']}",
            "'2026-10-21T10:00:00+02:00']}",
            r"people\[3\]: at: a time not in UTC",
        ),
        (
            "'2026-10-20T09:12:00Z', '2026-10-21T08:00:00Z'",
            "'2026-10-21T08:00:00Z', '2026-10-20T09:12:00Z'",
            r"people\[3\]: at: .* out of order",
        ),
        (
            "at: ['2026-10-21T08:00:00Z']}",
            "at: ['yesterday']}",
            r"people\[4\]\.at\[0\]: expected an ISO 8601 time",
        ),
        (
            "name: Another Person, account: account-2}",
            'name: "Another\\nPerson", account: account-2}',
            r"people\[1\]: name, account: empty, or with a line break",
        ),
        (
            "name: Another Person, account: account-2}",
            "name: '', account: account-2}",
            r"people\[1\]: name, account: empty",
        ),
        ("account: account-1}", "account: null}", r"people\[0\]\.account: expected a string"),
        (PEOPLE, "author: A Person\nassignee: A Person\n", "exactly the mirror's keys"),
    ],
)
def test_people_off_the_layout_are_refused_by_place(old: str, new: str, refusal: str) -> None:
    """A role, field, repeat, time or name off the layout's rules; the format before 041."""
    text = dump(ISSUE, "")
    assert old in text
    with pytest.raises(RepresentationError, match=refusal):
        load(text.replace(old, new), "issue.md")


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


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"type": "transcript", "id": "t-20261020-1"},
        {"type": "transcript", "id": "t-0123456789abcdef"},
        {"id": "e-0123456789abcdef"},
        {"people": (PersonRole(role="assignee", name="A Person"),)},
    ],
)
def test_work_log_front_matter_reads_back_as_written(changes: dict[str, object]) -> None:
    """An entry or a transcript, its id and revision of the work log's rules."""
    written = replace(ENTRY, **changes)
    front_matter, _ = load(dump(written, "# Notes\n"), "entry.md")
    second = MOMENT.replace(microsecond=0)
    assert front_matter == replace(written, created=second, updated=second, fetched_at=second)


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "page"},
        {"id": "196845"},
        {"id": "e-0123456789ABCDEF"},
        {"id": "t-20261020-" + "a" * 65},
        {"revision": "000003"},
        {"space": "MFS"},
        {"version": 3},
    ],
)
def test_work_log_front_matter_off_its_rules_is_refused(changes: dict[str, object]) -> None:
    """Another source's type, id, revision or keys are refused."""
    with pytest.raises(RefusedError):
        replace(ENTRY, **changes)


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
        {"created": MOMENT.astimezone(timezone(timedelta(hours=1)))},
    ],
)
def test_front_matter_off_its_rules_is_refused(changes: dict[str, object]) -> None:
    """A type of another source, a bad revision, a line break or a bad key is refused."""
    with pytest.raises(RefusedError):
        replace(PAGE, **changes)


def test_the_documents_are_exactly_the_pages_posts_issues_entries_and_transcripts(
    tmp_path: Path,
) -> None:
    """Trees, assets and hidden files are not documents; the work log's are, after the rest."""
    for name in (
        "confluence/MFS/196845-probe.md",
        "confluence/MFS/blog/196900-news.md",
        "confluence/MFS/_tree.md",
        "confluence/MFS/.hidden.md",
        "confluence/.trash/blog/1-old.md",
        "jira/_drafts/PRB-9.md",
        "jira/PRB/PRB-1.md",
        "assets/0a1b.md",
        "worklog/entries/e-0123456789abcdef-plan.md",
        "worklog/entries/.e-0123456789abcdef-plan.md",
        "worklog/transcripts/t-20261020-1-stand-up.md",
        "worklog/other/t-20261020-1-stand-up.md",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", "utf-8")
    assert [path.relative_to(tmp_path).as_posix() for path in documents(tmp_path)] == [
        "confluence/MFS/196845-probe.md",
        "confluence/MFS/blog/196900-news.md",
        "jira/PRB/PRB-1.md",
        "worklog/entries/e-0123456789abcdef-plan.md",
        "worklog/transcripts/t-20261020-1-stand-up.md",
    ]
