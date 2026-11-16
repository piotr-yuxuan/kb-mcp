"""The mirror's front matter: one way to write it, read back the same, typed strictly."""

from __future__ import annotations

from copy import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
import yaml

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.names import RefusedError
from kb_mcp.mirror.adapters.markdown import documents, dump, load
from kb_mcp.mirror.adapters.source_files import SOURCE_FILE, dumped, source_files
from kb_mcp.mirror.domain.mirror import FrontMatter, Link, Mention, SourceFile

if TYPE_CHECKING:
    from pathlib import Path

# The keys of data-layout.md's front-matter table, in its order.
LAYOUT_KEYS = [
    "source",
    "type",
    "id",
    "key",
    "title",
    "scope",
    "status",
    "subtype",
    "labels",
    "people",
    "parent",
    "links",
    "created",
    "updated",
    "version",
    "revision",
    "url",
    "breadcrumb",
]
MOMENT = datetime(2026, 10, 20, 21, 52, 41, 371000, tzinfo=UTC)
PAGE = FrontMatter(
    source="confluence",
    type="page",
    id="196845",
    key=None,
    title="Yes",
    scope="space:MFS",
    status="current",
    subtype=None,
    labels=("probe", "2026"),
    people=(Mention(role="author", name="A Person"),),
    parent="confluence:196001",
    links=(),
    created=MOMENT,
    updated=MOMENT,
    version=3,
    revision="000003",
    url="https://site.example.invalid/wiki/spaces/MFS/pages/196845",
    breadcrumb=("Home", "Probes"),
)


ENTRY = FrontMatter(
    source="worklog",
    type="entry",
    id="e-0123456789abcdef-2",
    key=None,
    title="Retrospective notes",
    scope="folder:worklog",
    status="WAITING",
    subtype=None,
    labels=("review", "ARCHIVE"),
    people=(),
    parent=None,
    links=(),
    created=MOMENT,
    updated=MOMENT,
    version=None,
    revision="0123456789abcdef",
    url=None,
    breadcrumb=("todo.org_archive",),
)


EARLY = datetime(2026, 10, 20, 9, 12, tzinfo=UTC)
LATE = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
ISSUE = FrontMatter(
    source="jira",
    type="issue",
    id="10000",
    key="PRB-1",
    title="What are archived ideas?",
    scope="project:PRB",
    status="Parking lot",
    subtype="Idea",
    labels=(),
    people=(
        Mention(role="author", name="A Person", identity="atlassian:account-1"),
        Mention(role="creator", name="Another Person", identity="atlassian:account-2"),
        Mention(role="assignee", name="A Person", identity="atlassian:account-1"),
        Mention(
            role="commenter",
            name="Another Person",
            identity="atlassian:account-2",
            at=(EARLY, LATE),
        ),
        Mention(role="commenter", name="A Person", identity="atlassian:account-1", at=(LATE,)),
    ),
    parent="jira:10002",
    links=(),
    created=MOMENT,
    updated=MOMENT,
    version=None,
    revision="20261020T215241.371000Z",
    url=None,
    breadcrumb=("Ideas",),
)
# The people of ISSUE as the layout writes them: each entry one line, in flow style.
PEOPLE = (
    "people:\n"
    "- {role: author, name: A Person, identity: 'atlassian:account-1'}\n"
    "- {role: creator, name: Another Person, identity: 'atlassian:account-2'}\n"
    "- {role: assignee, name: A Person, identity: 'atlassian:account-1'}\n"
    "- {role: commenter, name: Another Person, identity: 'atlassian:account-2',"
    " at: ['2026-10-20T09:12:00Z', '2026-10-21T08:00:00Z']}\n"
    "- {role: commenter, name: A Person, identity: 'atlassian:account-1',"
    " at: ['2026-10-21T08:00:00Z']}\n"
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
    assert front_matter == replace(PAGE, created=second, updated=second)
    assert body == "# Yes\n\nBody.\n"


def test_people_in_every_role_read_back_byte_for_byte() -> None:
    """Each person on one line, by role, with an identity and a commenter's times."""
    text = dump(ISSUE, "# What are archived ideas?\n")
    assert f"labels: []\n{PEOPLE}parent: jira:10002\nlinks: []\ncreated: " in text
    front_matter, body = load(text, "issue.md")
    assert dump(front_matter, body) == text
    second = MOMENT.replace(microsecond=0)
    assert front_matter == replace(ISSUE, created=second, updated=second)
    assert (front_matter.author, front_matter.creator, front_matter.assignee) == (
        "A Person",
        "Another Person",
        "A Person",
    )


def test_a_former_account_reads_as_an_atlassian_identity_and_is_written_as_one() -> None:
    """Plan 041's ``account: account-1`` is the identity ``atlassian:account-1``.

    The Atlassian connectors alone wrote it; the file written again says ``identity``.
    """
    text = dump(ISSUE, "# What are archived ideas?\n")
    former = text.replace(PEOPLE, PEOPLE.replace("identity: 'atlassian:", "account: '"))
    assert "account: 'account-1'" in former
    front_matter, body = load(former, "issue.md")
    assert [person.identity for person in front_matter.people] == [
        person.identity for person in ISSUE.people
    ]
    assert dump(front_matter, body) == text


def test_an_identity_and_people_are_left_out_when_the_source_has_none() -> None:
    """No identity where the source gives none, ``[]`` without people or links; nobody named."""
    page = "people:\n- {role: author, name: A Person}\nparent: confluence:196001\nlinks: []\n"
    assert page in dump(PAGE, "")
    assert "people: []\nparent: null\nlinks: []\n" in dump(ENTRY, "")
    assert (ENTRY.author, ENTRY.creator, ENTRY.assignee) == (None, None, None)
    assert (PAGE.author, PAGE.creator, PAGE.assignee) == ("A Person", None, None)


@pytest.mark.parametrize(
    ("old", "new", "refusal"),
    [
        ("role: creator", "role: reviewer", r"people\[1\]: role: not one of the roles"),
        (
            "identity: 'atlassian:account-2'}",
            "identity: 'atlassian:account-2', email: x}",
            r"people\[1\]: fields other",
        ),
        (
            "{role: creator, name: Another Person",
            "{name: Another Person, role: creator",
            r"people\[1\]: fields other",
        ),
        ("role: creator", "role: author", r"^issue\.md: people: a second author"),
        ("role: assignee", "role: creator", r"^issue\.md: people: a second author"),
        ("role: creator", "role: assignee", r"^issue\.md: people: a second author"),
        (
            "name: A Person, identity: 'atlassian:account-1', at",
            "name: Another Person, identity: 'atlassian:account-2', at",
            r"^issue\.md: people: .* a commenter or a participant twice",
        ),
        (
            (
                "- {role: author, name: A Person, identity: 'atlassian:account-1'}\n"
                "- {role: creator, name: Another Person, identity: 'atlassian:account-2'}\n"
            ),
            (
                "- {role: creator, name: Another Person, identity: 'atlassian:account-2'}\n"
                "- {role: author, name: A Person, identity: 'atlassian:account-1'}\n"
            ),
            r"^issue\.md: people: .* out of the order of the roles$",
        ),
        (
            "identity: 'atlassian:account-1'}",
            "identity: 'atlassian:account-1', at: ['2026-10-20T09:12:00Z']}",
            r"people\[0\]: at: only and always for a commenter",
        ),
        (
            "identity: 'atlassian:account-1', at: ['2026-10-21T08:00:00Z']}",
            "identity: 'atlassian:account-1'}",
            r"people\[4\]: at: only and always for a commenter",
        ),
        ("at: ['2026-10-21T08:00:00Z']}", "at: []}", r"people\[4\]\.at: empty"),
        (
            "identity: 'atlassian:account-1'}",
            "identity: 'atlassian:account-1', at: []}",
            r"people\[0\]\.at: empty",
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
            "name: Another Person, identity: 'atlassian:account-2'}",
            "name: \"Another\\nPerson\", identity: 'atlassian:account-2'}",
            r"people\[1\]: name, identity: empty, or with a line break",
        ),
        (
            "name: Another Person, identity: 'atlassian:account-2'}",
            "name: '', identity: 'atlassian:account-2'}",
            r"people\[1\]: name, identity: empty",
        ),
        (
            "identity: 'atlassian:account-1'}",
            "identity: null}",
            r"people\[0\]\.identity: expected a string",
        ),
        (
            "identity: 'atlassian:account-1'}",
            "identity: account-1}",
            r"people\[0\]: identity: does not match",
        ),
        (
            PEOPLE,
            "author: A Person\nassignee: A Person\n",
            r"^issue\.md: front matter .* mirror's keys, in order, without people$",
        ),
    ],
)
def test_people_off_the_layout_are_refused_by_place(old: str, new: str, refusal: str) -> None:
    """A role, field, repeat, time or name off the layout's rules; the format before 041."""
    text = dump(ISSUE, "")
    assert old in text
    with pytest.raises(RepresentationError, match=refusal):
        load(text.replace(old, new), "issue.md")


# A meeting of the work log: its participants as written, annotation included, and its
# transcript; and that transcript: its speakers, and the two meetings that summarise it.
MEETING = replace(
    ENTRY,
    type="meeting",
    id="m-20261027-payments-stand-up",
    title="Payments stand-up",
    labels=(),
    people=tuple(
        Mention(role="participant", name=name)
        for name in ("Alex Example", "Sam Sample", "Kim (not in the header)")
    ),
    links=(Link(relation="transcript", document="worklog:t-20261027-meeting-1"),),
)
TRANSCRIPT = replace(
    ENTRY,
    type="transcript",
    id="t-20261027-meeting-1",
    title="Meeting 1",
    labels=(),
    people=tuple(Mention(role="participant", name=name) for name in ("Alex Example", "Sam Sample")),
    links=(
        Link(relation="summary", document="worklog:m-20261027-payments-stand-up"),
        Link(relation="summary", document="worklog:m-20261027-payments-stand-up-2"),
    ),
)
# Their people and links as the layout writes them: each entry one line, in flow style.
MEETING_LINES = (
    "people:\n"
    "- {role: participant, name: Alex Example}\n"
    "- {role: participant, name: Sam Sample}\n"
    "- {role: participant, name: Kim (not in the header)}\n"
    "parent: null\n"
    "links:\n"
    "- {relation: transcript, document: 'worklog:t-20261027-meeting-1'}\n"
)
TRANSCRIPT_LINKS = (
    "links:\n"
    "- {relation: summary, document: 'worklog:m-20261027-payments-stand-up'}\n"
    "- {relation: summary, document: 'worklog:m-20261027-payments-stand-up-2'}\n"
)
TRANSCRIPT_LINES = (
    "people:\n"
    "- {role: participant, name: Alex Example}\n"
    "- {role: participant, name: Sam Sample}\n"
    "parent: null\n"
    f"{TRANSCRIPT_LINKS}"
)


@pytest.mark.parametrize(
    ("front", "lines"), [(MEETING, MEETING_LINES), (TRANSCRIPT, TRANSCRIPT_LINES)]
)
def test_participants_and_links_read_back_byte_for_byte(front: FrontMatter, lines: str) -> None:
    """Each participant and each link on one line, the links after the people, by relation."""
    text = dump(front, "# Payments stand-up\n")
    assert f"labels: []\n{lines}created: " in text
    front_matter, body = load(text, "meeting.md")
    assert dump(front_matter, body) == text
    second = MOMENT.replace(microsecond=0)
    assert front_matter == replace(front, created=second, updated=second)


@pytest.mark.parametrize(
    ("old", "new", "refusal"),
    [
        (
            "{relation: summary, document: 'worklog:m-20261027-payments-stand-up'}",
            "{relation: mentions, document: 'worklog:m-20261027-payments-stand-up'}",
            r"^transcript\.md\.links\[0\]: relation: not one of the relations$",
        ),
        (
            "document: 'worklog:m-20261027-payments-stand-up'}",
            "document: 'worklog:m-20261027-payments-stand-up', title: x}",
            r"^transcript\.md\.links\[0\]: fields other than relation, document, or out of order$",
        ),
        (
            "{relation: summary, document: 'worklog:m-20261027-payments-stand-up-2'}",
            "{document: 'worklog:m-20261027-payments-stand-up-2', relation: summary}",
            r"^transcript\.md\.links\[1\]: fields other",
        ),
        (
            "{relation: summary, document: 'worklog:m-20261027-payments-stand-up'}",
            "{relation: summary}",
            r"^transcript\.md\.links\[0\]\.document: missing$",
        ),
        (
            "document: 'worklog:m-20261027-payments-stand-up'}",
            "document: m-20261027-payments-stand-up}",
            r"^transcript\.md\.links\[0\]: document: does not match",
        ),
        (
            "document: 'worklog:m-20261027-payments-stand-up'}",
            "document: 'worklog:../m-20261027-payments-stand-up.md'}",
            r"^transcript\.md\.links\[0\]: document: does not match",
        ),
        (
            "document: 'worklog:m-20261027-payments-stand-up'}",
            "document: 2026}",
            r"^transcript\.md\.links\[0\]\.document: expected a string$",
        ),
        (
            "document: 'worklog:m-20261027-payments-stand-up-2'}",
            "document: 'worklog:t-20261027-meeting-1'}",
            r"^transcript\.md: links: a link to the document itself",
        ),
        (
            "document: 'worklog:m-20261027-payments-stand-up-2'}",
            "document: 'worklog:m-20261027-payments-stand-up'}",
            r"^transcript\.md: links: .* one given twice$",
        ),
        (
            "{role: participant, name: Sam Sample}",
            "{role: participant, name: Alex Example}",
            r"^transcript\.md: people: .* a participant twice",
        ),
        (
            "{role: participant, name: Sam Sample}",
            "{role: participant, name: Sam Sample, at: ['2026-10-27T09:31:00Z']}",
            r"^transcript\.md\.people\[1\]: at: only and always for a commenter$",
        ),
        (
            "{role: participant, name: Sam Sample}",
            "{role: author, name: Sam Sample}",
            r"^transcript\.md: people: .* a participant beside another role",
        ),
        (
            TRANSCRIPT_LINKS,
            "",
            r"^transcript\.md: front matter .* mirror's keys, in order, without links$",
        ),
    ],
)
def test_links_and_participants_off_the_layout_are_refused_by_place(
    old: str, new: str, refusal: str
) -> None:
    """A relation, field, document, self-link or repeat off the layout's rules."""
    text = dump(TRANSCRIPT, "")
    assert text.count(old) == 1
    with pytest.raises(RepresentationError, match=refusal):
        load(text.replace(old, new), "transcript.md")


def test_a_parent_or_a_link_that_is_the_document_itself_is_refused() -> None:
    """A document names itself by its document id: neither its parent nor a link is it."""
    with pytest.raises(RefusedError, match=r"^links: a link to the document itself"):
        replace(ISSUE, links=(Link(relation="summary", document="jira:10000"),))
    with pytest.raises(RefusedError, match=r"^parent: the document itself$"):
        replace(ISSUE, parent="jira:10000")
    assert replace(ISSUE, links=(Link(relation="summary", document="jira:PRB-1"),)).links


# ISSUE, PAGE and the TRANSCRIPT, as the files of plan 058 wrote them.
FORMER_ISSUE = """---
source: jira
type: issue
id: '10000'
key: PRB-1
title: What are archived ideas?
space: null
project: PRB
status: Parking lot
issue_type: Idea
labels: []
people:
- {role: author, name: A Person, identity: 'atlassian:account-1'}
links: []
created: '2026-10-20T21:52:41Z'
updated: '2026-10-20T21:52:41Z'
version: null
revision: 20261020T215241.371000Z
url: null
breadcrumb:
- PRB-3
fetched_at: '2026-10-22T08:15:00Z'
---

# What are archived ideas?
"""


def test_a_front_matter_of_plan_058_reads_as_today_s() -> None:
    """Its space or project is its scope, else the work log's; its issue type, its subtype.

    It has no parent; a link's ref names a document of its own source; its time of fetch
    is left out, and the file written again holds today's keys.
    """
    front_matter, body = load(FORMER_ISSUE, "issue.md")
    assert (front_matter.scope, front_matter.subtype, front_matter.parent) == (
        "project:PRB",
        "Idea",
        None,
    )
    assert front_matter.breadcrumb == ("PRB-3",)
    assert body == "# What are archived ideas?\n"
    assert list(yaml.safe_load(dump(front_matter, body).split("---\n")[1])) == LAYOUT_KEYS
    page = (
        FORMER_ISSUE.replace("source: jira", "source: confluence")
        .replace("type: issue", "type: page")
        .replace("key: PRB-1", "key: null")
        .replace("space: null\nproject: PRB", "space: MFS\nproject: null")
        .replace("issue_type: Idea", "issue_type: null")
    )
    assert load(page, "page.md")[0].scope == "space:MFS"
    transcript = (
        FORMER_ISSUE.replace("source: jira", "source: worklog")
        .replace("project: PRB", "project: null")
        .replace(
            "links: []",
            "links:\n- {relation: summary, ref: m-20261027-payments-stand-up}",
        )
    )
    former, _ = load(transcript, "transcript.md")
    assert former.scope == "folder:worklog"
    assert former.links == (
        Link(relation="summary", document="worklog:m-20261027-payments-stand-up"),
    )


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
    ("old", "new", "lacking"),
    [
        ("status: current\n", "", ", in order, without status$"),
        ("source: confluence\n", "extra: 1\nsource: confluence\n", ", in order$"),
    ],
)
def test_front_matter_with_other_keys_is_refused(old: str, new: str, lacking: str) -> None:
    """A missing, extra or moved key is not the mirror's front matter; a missing one is named."""
    with pytest.raises(RepresentationError, match=f"exactly the mirror's keys{lacking}"):
        load(dump(PAGE, "").replace(old, new), "page.md")


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"type": "transcript", "id": "t-20261020-1"},
        {"type": "transcript", "id": "t-0123456789abcdef"},
        {"id": "e-0123456789abcdef"},
        {"people": (Mention(role="participant", name="A Person"),)},
        {"type": "day", "id": "d-20261028"},
        {"type": "meeting", "id": "m-20261027-payments-stand-up"},
        {"type": "meeting", "id": "m-20261027-payments-stand-up-2"},
        {"type": "meeting", "id": "m-20261027-0123456789abcdef"},
        {"type": "transcript", "id": "t-20261027-meeting-1"},
    ],
)
def test_work_log_front_matter_reads_back_as_written(changes: dict[str, object]) -> None:
    """An entry, a day, a meeting or a transcript, its id and revision of the work log's rules."""
    written = replace(ENTRY, **changes)
    front_matter, _ = load(dump(written, "# Notes\n"), "entry.md")
    second = MOMENT.replace(microsecond=0)
    assert front_matter == replace(written, created=second, updated=second)


def test_a_document_of_a_source_that_no_registry_names_reads_back() -> None:
    """The front matter's rules are every source's: a new source's name, type and ids load."""
    written = replace(ENTRY, source="memo2", type="note", id="n-1_A", revision="r1.2_b-C")
    front_matter, _ = load(dump(written, "# Notes\n"), "memo2/n-1_A.md")
    second = MOMENT.replace(microsecond=0)
    assert front_matter == replace(written, created=second, updated=second)


def test_a_file_without_front_matter_is_refused() -> None:
    """A Markdown file that does not start with front matter is not a document."""
    with pytest.raises(RepresentationError, match="no front matter"):
        load("# Title\n", "page.md")


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [
        ({"source": "Confluence"}, r"^source: does not match"),
        ({"source": "1confluence"}, r"^source: does not match"),
        ({"type": "blog post"}, r"^type: does not match"),
        ({"id": "../196845"}, r"^id: does not match"),
        ({"revision": "000003/2"}, r"^revision: does not match"),
        ({"revision": ""}, r"^revision: does not match"),
        ({"key": "prb-1"}, r"^key: does not match"),
        ({"scope": "M F S"}, r"^scope: does not match"),
        ({"scope": "space"}, r"^scope: does not match"),
        ({"parent": "196001"}, r"^parent: does not match"),
        ({"title": "Two\nlines"}, r"^a text holds a line break$"),
        ({"title": "Two\u2028lines"}, r"^a text holds a line break$"),
        ({"labels": ("one\x85two",)}, r"^a text holds a line break$"),
        ({"created": MOMENT.astimezone(timezone(timedelta(hours=1)))}, r"^a time not in UTC$"),
        (
            {"people": (*PAGE.people, Mention(role="participant", name="Sam Sample"))},
            r"^people: .* a participant beside another role",
        ),
    ],
)
def test_front_matter_off_every_source_s_rules_is_refused(
    changes: dict[str, object], refusal: str
) -> None:
    """A name, id, revision or key off its rule, a line break, a time not in UTC is refused.

    So is a participant beside another role, which keeps a read's front matter within its
    budget, whatever the source.
    """
    with pytest.raises(RefusedError, match=refusal):
        replace(PAGE, **changes)


def test_the_documents_are_every_markdown_file_but_assets_and_hidden_names(
    tmp_path: Path,
) -> None:
    """Every ``.md`` file under docs/, whichever source wrote it, sorted by path.

    But those under ``assets/``, where an attached ``x.md`` is an asset, and those with a
    name beginning with ``_`` or ``.`` on their path; and no other file.
    """
    for name in (
        "x.md",
        "assets/0a1b.md",
        "assets/x/y.md",
        "confluence/MFS/196845-probe.md",
        "confluence/MFS/blog/196900-news.md",
        "confluence/MFS/_tree.md",
        "confluence/MFS/.hidden.md",
        "confluence/MFS/notes.txt",
        "confluence/QM/_x.md",
        "confluence/.trash/blog/1-old.md",
        "jira/_drafts/PRB-9.md",
        "jira/PRB/PRB-1.md",
        "memo/n-1.md",
        "worklog/entries/e-0123456789abcdef-plan.md",
        "worklog/entries/.e-0123456789abcdef-plan.md",
        "worklog/transcripts/t-20261020-1-stand-up.md",
        "worklog/meetings/m-20261027-payments-stand-up.md",
        "worklog/days/d-20261027.md",
        "worklog/other/t-20261020-1-stand-up.md",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", "utf-8")
    (tmp_path / "jira" / "PRB" / "folder.md").mkdir()
    assert [path.relative_to(tmp_path).as_posix() for path in documents(tmp_path)] == [
        "confluence/MFS/196845-probe.md",
        "confluence/MFS/blog/196900-news.md",
        "jira/PRB/PRB-1.md",
        "memo/n-1.md",
        "worklog/days/d-20261027.md",
        "worklog/entries/e-0123456789abcdef-plan.md",
        "worklog/meetings/m-20261027-payments-stand-up.md",
        "worklog/other/t-20261020-1-stand-up.md",
        "worklog/transcripts/t-20261020-1-stand-up.md",
        "x.md",
    ]


def test_each_source_s_file_reads_back_by_its_folder_and_a_source_without_one_has_none(
    tmp_path: Path,
) -> None:
    """``_source.json`` of each source's folder, by the folder's name; no document is it."""
    declared = SourceFile(
        roles={"issue": ("author", "assignee"), "page": ()},
        as_of={"project:PRB": datetime(2026, 11, 10, 8, 30, tzinfo=UTC)},
    )
    (tmp_path / "jira").mkdir()
    (tmp_path / "jira" / SOURCE_FILE).write_bytes(dumped(declared))
    (tmp_path / "memo").mkdir()
    assert source_files(tmp_path) == {"jira": declared}
    assert list(documents(tmp_path)) == []


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("{", "not JSON"),
        ('{"roles": {}}', "keys other than roles, as_of"),
        ('{"as_of": {}, "roles": {}}', "keys other than roles, as_of"),
        ('{"roles": {}, "as_of": {}, "fetched": {}}', "keys other than roles, as_of"),
        ('{"roles": {"issue": ["reviewer"]}, "as_of": {}}', "roles: not of the roles"),
        (
            '{"roles": {"issue": ["assignee", "author"]}, "as_of": {}}',
            "roles: not of the roles, or out",
        ),
        ('{"roles": {"Issue": []}, "as_of": {}}', "roles: does not match"),
        ('{"roles": {"issue": "author"}, "as_of": {}}', r"roles\.issue: expected a list"),
        ('{"roles": {}, "as_of": {"PRB": "2026-11-10T08:30:00Z"}}', "as_of: does not match"),
        (
            '{"roles": {}, "as_of": {"project:PRB": "2026-11-10T08:30:00"}}',
            r"as_of\.project:PRB: expected an ISO 8601 time with an offset",
        ),
        (
            '{"roles": {}, "as_of": {"project:PRB": "2026-11-10T09:30:00+01:00"}}',
            "as_of: a time not in UTC",
        ),
        ('{"roles": {}, "as_of": {"project:PRB": null}}', r"as_of\.project:PRB: expected"),
    ],
)
def test_a_source_s_file_off_its_format_names_it_and_prepare(
    tmp_path: Path, text: str, reason: str
) -> None:
    """Refused by its path, with what is wrong and the command that writes it again."""
    (tmp_path / "jira").mkdir()
    (tmp_path / "jira" / SOURCE_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(
        RepresentationError, match=rf"^jira/_source\.json.*{reason}.*kb-mcp prepare"
    ):
        source_files(tmp_path)
