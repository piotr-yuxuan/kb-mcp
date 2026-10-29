"""The four tools on small mirrors: ranking, filters, reading and browsing."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.mcp.app.tools import UnanswerableError
from atlassian_offline_mcp.mirror.domain.mirror import Link, PersonRole
from atlassian_offline_mcp.search.adapters import sqlite_index
from tests.answers import built, continuation, follow, parts
from tests.mirrors import CREATED, FILLERS, LOREM, MOMENT, PEOPLE, PERSONS, issue, location, page
from tests.test_people import ALEX, ALEX_EXAMPLE, ROBIN, ROBIN_ALONE, SAM_2, SAM_3, SAM_ALONE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

    from atlassian_offline_mcp.mcp.app.tools import Library
    from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter

NEWER = MOMENT + timedelta(days=1)
HIT = re.compile(r"^\d+\. .*\n {3}(\S+) \|", re.MULTILINE)
# A hit's ref, and what ends its second line after the mirror date.
FACTS = re.compile(r"^ {3}(\S+) \| .* \| mirrored \d{4}-\d\d-\d\d \| (.*)$", re.MULTILINE)


def refs(answer: str) -> list[str]:
    """List the refs of a search's hits, in order."""
    return HIT.findall(parts(answer)[1])


def test_words_spread_over_sections_rank_their_page_first(tmp_path: Path) -> None:
    """A page holding each word in another section beats one word in a title."""
    handbook = (
        "# Operations handbook\n\n## Brokers\n\nThe kafka brokers.\n\n"
        "## Storage\n\nThe retention of logs.\n\n## Cleanup\n\nThe compaction of logs.\n"
    )
    library = built(
        tmp_path,
        [(page("196845", "Operations handbook"), handbook), (page("196846", "Kafka"), None)],
    )
    assert refs(library.search("kafka retention compaction"))[:2] == ["196845", "196846"]


def test_an_unaccented_query_finds_an_accented_title(tmp_path: Path) -> None:
    """Diacritics are folded on both sides."""
    library = built(tmp_path, [(page("196845", "Économie générale"), None)])
    assert refs(library.search("economie GENERALE")) == ["196845"]


@pytest.mark.parametrize(
    "query",
    ['"', "*", "NEAR", "-", "(", ":", "^", "AND", "OR", "NOT", 'kafka" OR "x', "NEAR(a b)"],
)
def test_no_query_raises(tmp_path: Path, query: str) -> None:
    """FTS5 syntax in a query is searched as words, or answered with a hint."""
    library = built(tmp_path, [(page("196845", "Kafka NEAR AND OR NOT"), None)])
    header = parts(library.search(query))[0]
    assert header.startswith(("Documents found:", "The query has no words"))


def test_a_page_with_many_matching_sections_is_one_hit(tmp_path: Path) -> None:
    """Twenty sections that match make one hit, opened at the section with every word."""
    parts_of_body = [f"## Part {number}\n\nZookeeper nodes.\n" for number in range(20)]
    body = "# Coordination\n\n" + "\n".join([*parts_of_body, "## Quorum\n\nZookeeper quorum.\n"])
    library = built(tmp_path, [(page("196845", "Coordination"), body)])
    answer = library.search("zookeeper quorum")
    assert refs(answer) == ["196845"]
    assert 'section 22 Quorum: read(ref="196845", section=22)' in answer


def test_a_match_on_the_title_alone_opens_the_first_section(tmp_path: Path) -> None:
    """When no section holds the words, the document opens at its start."""
    body = f"# Grafana dashboards\n\n{LOREM}\n\n## Panels\n\n{LOREM}\n"
    library = built(tmp_path, [(page("196845", "Grafana dashboards"), body)])
    assert 'section 1: read(ref="196845", section=1)' in library.search("grafana")


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("proj-7 kafka", "PROJ-7"),
        ("kafka 196900", "196900"),
        ("https://x.atlassian.net/wiki/spaces/ENG/pages/196900/Kafka kafka", "196900"),
        ("https://x.atlassian.net/browse/PROJ-7 kafka", "PROJ-7"),
    ],
)
def test_identifiers_come_first(tmp_path: Path, query: str, first: str) -> None:
    """A key, an id or an address in the query puts its document above every match."""
    about = "# Kafka\n\nKafka kafka kafka, see PROJ-7 and 196900.\n"
    library = built(
        tmp_path,
        [
            (page("196845", "Kafka"), about),
            (page("196900", "Unrelated"), None),
            (issue("PROJ-7", "Unrelated too"), None),
        ],
    )
    assert refs(library.search(query))[0] == first


def test_an_exact_phrase_beats_the_same_words_scattered(tmp_path: Path) -> None:
    """The phrase decides against a newer document first by path, whose sections are shorter."""
    adjacent = f"# Monitoring\n\n## Signals\n\nConsumer lag. {LOREM}\n"
    scattered = f"# Alerting\n\n## Signals\n\nConsumer. {LOREM}\n\n## Others\n\nLag. {LOREM}\n"
    library = built(
        tmp_path,
        [
            (page("196846", "Monitoring"), adjacent),
            (page("196845", "Alerting", updated=NEWER), scattered),
        ],
    )
    assert location(page("196845", "Alerting")) < location(page("196846", "Monitoring"))
    assert refs(library.search("consumer lag"))[:2] == ["196846", "196845"]


def test_a_long_pages_title_word_keeps_its_rarity(tmp_path: Path) -> None:
    """A title word of a page of 200 sections outweighs a rare word in a newer body.

    Were the title on every section, its word would fill most rows of the index, FTS5
    would count it as worthless, and the newer page, holding the other word, would win.
    """
    long_body = "# Terraform modules\n\n" + "".join(
        f"## Part {number}\n\n{LOREM}\n\n" for number in range(200)
    )
    library = built(
        tmp_path,
        [
            (page("196845", "Terraform modules"), long_body),
            (
                page("196846", "Infrastructure", updated=NEWER),
                f"# Infrastructure\n\nWe watch for drift. {LOREM}\n",
            ),
        ],
    )
    assert refs(library.search("terraform drift"))[:2] == ["196845", "196846"]


def test_a_capped_expression_keeps_its_best_and_says_at_least(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """At its cap, an expression keeps its best documents, and the count is a bound.

    The best come last in the index's own order, so that only ranking keeps them.
    """
    titled = [(page(str(197800 + n), f"Zeta {n}"), None) for n in range(3)]
    mentioned = [(page(str(196900 + n), f"Other {n}"), f"# Other {n}\n\nZeta.\n") for n in range(5)]
    library = built(tmp_path, titled + mentioned)
    monkeypatch.setattr(sqlite_index, "PER_EXPRESSION", 3)
    answer = library.search("zeta")
    assert parts(answer)[0].startswith("Documents found: at least 3;")
    assert sorted(refs(answer)) == ["197800", "197801", "197802"]
    assert parts(library.search("zeta", sort="updated"))[0].startswith("Documents found: 8;")
    assert parts(library.search("zeta", sort="created"))[0].startswith("Documents found: 8;")


def test_the_best_section_is_judged_without_the_title(tmp_path: Path) -> None:
    """A title word that a later section holds too opens that section, not the first."""
    body = f"# Rollback plan\n\n## Overview\n\n{LOREM}\n\n## Steps\n\nRoll the release back.\n"
    library = built(tmp_path, [(page("196845", "Rollback plan"), body)])
    assert 'section 3 Steps: read(ref="196845", section=3)' in library.search("release rollback")


def test_a_later_heading_like_the_title_stays_a_heading(tmp_path: Path) -> None:
    """Only the first section's heading, the title, is left out of the headings."""
    body = f"# Rollback\n\n{LOREM}\n\n## Rollback\n\nSteps.\n"
    library = built(tmp_path, [(page("196845", "Rollback"), body)])
    assert 'section 2 Rollback: read(ref="196845", section=2)' in library.search("rollback")


def test_a_page_id_names_confluence_documents_only(tmp_path: Path) -> None:
    """The number of an issue's id pins nothing: issues are named by their keys."""
    library = built(tmp_path, [(issue("PROJ-7", "Kafka upgrade"), None)])
    assert issue("PROJ-7", "Kafka upgrade").id == "10007"
    assert refs(library.search("10007")) == []


def test_a_decomposed_query_is_composed_first(tmp_path: Path) -> None:
    """A query typed in NFD, as macOS often gives text, finds the composed title."""
    library = built(tmp_path, [(page("196845", "Économie générale"), None)])
    assert refs(library.search("e\u0301conomie")) == ["196845"]


def test_words_beyond_the_tenth_are_said_to_be_left_out(tmp_path: Path) -> None:
    """The answer says when a long query was cut."""
    library = built(tmp_path, [])
    words = " ".join(f"word{number}" for number in range(12))
    assert "Only the first 10 words of the query were searched." in library.search(words)


@pytest.fixture
def varied(tmp_path: Path) -> Library:
    """Serve documents of two spaces and a project, with labels, statuses and dates."""
    midnight = datetime(2026, 10, 20, tzinfo=UTC)
    return built(
        tmp_path,
        [
            (page("196845", "Kafka runbook", labels=("runbook",), updated=NEWER), None),
            (page("196846", "Kafka design", space="OPS", updated=midnight), None),
            (issue("PROJ-7", "Kafka upgrade", status="À faire", updated=midnight), None),
            (issue("PROJ-8", "Kafka rollback", status="Done"), None),
        ],
    )


def test_what_changed_lists_the_newest_first(varied: Library) -> None:
    """With no words, sort="updated" lists documents by update time, newest first."""
    assert refs(varied.search(sort="updated", limit=3)) == ["196845", "PROJ-8", "196846"]


@pytest.mark.parametrize(
    ("query", "filters", "expected"),
    [
        ("kafka", {"space": "ops"}, ["196846"]),
        ("kafka", {"source": "jira"}, ["PROJ-8", "PROJ-7"]),
        ("kafka", {"status": "à faire"}, ["PROJ-7"]),
        ("kafka", {"label": "RUNBOOK"}, ["196845"]),
        ("kafka 196845", {"space": "OPS"}, ["196846"]),
        ("PROJ-7 kafka", {"project": "proj", "status": "Done"}, ["PROJ-8"]),
        ("", {"label": "runbook"}, ["196845"]),
        ("", {"updated_after": "2026-10-20", "source": "jira"}, ["PROJ-8", "PROJ-7"]),
        ("", {"updated_before": "2026-10-20T00:00:01", "project": "PROJ"}, ["PROJ-7"]),
        ("", {"updated_before": "2026-10-20", "project": "PROJ"}, []),
    ],
)
def test_each_filter_narrows(
    varied: Library, query: str, filters: dict[str, str], expected: list[str]
) -> None:
    """Filters narrow a search with words, with identifiers, and with no words."""
    answer = varied.search(query, filters=filters, sort="updated" if not query else "relevance")
    assert refs(answer) == expected


@pytest.mark.parametrize(
    ("filters", "valid"),
    [
        ({"space": "NOPE"}, "ENG, OPS"),
        ({"project": "NOPE"}, "PROJ"),
        ({"status": "Blocked"}, "current, Done, À faire"),
        ({"label": "nope"}, "runbook"),
    ],
)
def test_an_unknown_value_is_refused_with_the_valid_ones(
    varied: Library, filters: dict[str, str], valid: str
) -> None:
    """The refusal lists the values that documents have, inside the block."""
    with pytest.raises(UnanswerableError) as refused:
        varied.search("kafka", filters=filters)
    assert parts(str(refused.value))[1] == valid


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"filters": {"spaec": "ENG"}}, "filters: no spaec"),
        ({"filters": {"updated_after": "yesterday"}}, "updated_after: an ISO 8601 date"),
        ({"filters": {"updated_after": "0001-01-01T00:00:00+05:00"}}, "updated_after: an ISO"),
        ({"filters": {"updated_before": "9999-12-31T23:59:59-05:00"}}, "updated_before: an ISO"),
        ({"filters": {"created_after": "last week"}}, "created_after: an ISO 8601 date"),
        ({"filters": {"created_before": "2026-13-01"}}, "created_before: an ISO 8601 date"),
        ({"query": "x" * 501}, "query: at most 500 characters"),
        ({"query": "kafka", "cursor": "8"}, "cursor: give the one"),
        ({"query": "kafka", "cursor": "8@20200101T000000Z"}, "cursor: the index was rebuilt"),
    ],
)
def test_arguments_that_cannot_be_served_are_refused(
    varied: Library, arguments: dict[str, object], message: str
) -> None:
    """Each refusal names what would do."""
    with pytest.raises(UnanswerableError, match=re.escape(message)):
        varied.search(**arguments)


def test_a_query_without_words_asks_for_words(varied: Library) -> None:
    """Sorting by relevance needs words; the answer says so, without an error."""
    assert "no words to search" in varied.search("***")


@pytest.fixture
def people(tmp_path: Path) -> Library:
    """Serve the made-up people of PEOPLE, beside the fillers, all created before them."""
    return built(tmp_path, [(front, None) for front in PEOPLE])


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"issue_type": "bug"}, ["PROJ-1"]),
        ({"author": "bo sample"}, ["PROJ-1", "196845"]),
        ({"assignee": "ADA EXAMPLE"}, ["PROJ-3", "PROJ-1"]),
        ({"assignee": "helene example"}, ["PROJ-2"]),
        ({"created_after": "2026-10-25"}, ["PROJ-3", "PROJ-1"]),
        ({"created_after": "2026-10-21", "created_before": "2026-10-25"}, ["PROJ-2", "196845"]),
        (
            {"created_after": "2026-10-24", "created_before": "2026-10-25T00:00:01"},
            ["PROJ-3", "PROJ-1"],
        ),
        ({"label": "Résumé"}, ["196845"]),
        ({"label": "RESUME"}, ["PROJ-3", "PROJ-2"]),
    ],
)
def test_people_and_created_dates_narrow_with_words_or_without(
    people: Library, filters: dict[str, str], expected: list[str]
) -> None:
    """Names match without regard to case or accents, a date is its midnight UTC.

    An author is a page's creator or an issue's reporter. A label equal but for case
    goes before a more used one equal but for accents.
    """
    assert refs(people.search(filters=filters, sort="created")) == expected
    assert sorted(refs(people.search("broker", filters=filters))) == sorted(expected)


@pytest.mark.parametrize(
    ("filters", "valid"),
    [
        ({"assignee": "helene"}, "Hélène Example, Ada Example"),
        ({"author": "AMPLE"}, "Bo Sample, Ada Example, A Person"),
        ({"issue_type": "Epic"}, "Bug, Story, Task"),
        ({"label": "resumé"}, "resume, résumé"),
    ],
)
def test_a_refusal_lists_first_the_values_holding_what_was_given(
    people: Library, filters: dict[str, str], valid: str
) -> None:
    """Without regard to case or accents; else, and within each group, the most used first.

    A value that several have but for accents is refused too, rather than one picked.
    """
    with pytest.raises(UnanswerableError) as refused:
        people.search("broker", filters=filters)
    assert parts(str(refused.value))[1] == valid


def test_sorted_by_created_date_newest_first_with_words_or_without(people: Library) -> None:
    """Ties to the newest update; with words, the documents named first, every match counted."""
    newest = ["PROJ-3", "PROJ-1", "PROJ-2", "196845"]
    assert refs(people.search(sort="created", limit=4)) == newest
    answer = people.search("broker", sort="created")
    assert (parts(answer)[0].split(";")[0], refs(answer)) == ("Documents found: 4", newest)
    assert refs(people.search("196845 broker", sort="created")) == ["196845", *newest[:3]]
    assert refs(people.search(sort="updated", limit=4)) == ["PROJ-2", "PROJ-3", "PROJ-1", "196845"]


@pytest.mark.parametrize("query", ["", "broker"])
def test_a_listing_by_created_date_continues_by_its_cursor(people: Library, query: str) -> None:
    """One document a page, each once, in order, with words or without."""
    answer: str | None = people.search(query, filters={"source": "jira"}, sort="created", limit=1)
    found = []
    while answer is not None:
        found += refs(answer)
        answer = follow(people, answer)
    assert found == ["PROJ-3", "PROJ-1", "PROJ-2"]


def test_a_name_matches_whole_as_shown_and_the_value_given_first(tmp_path: Path) -> None:
    """A Hangul name is no other with the same first letters, a kana keeps its voicing.

    Values compare as hits show them, spaces collapsed and composed; of several labels
    that look alike, the one given exactly is kept, else the most used, and since plan
    043 names of one key are one person, an assignee written with a no-break space the
    one without. A value matching several but for accents alone, and none but for case,
    is refused.
    """
    library = built(
        tmp_path,
        [
            (
                issue("PROJ-1", "Broker crash", assignee="에이다 예시", labels=("backend", "café")),
                None,
            ),
            (
                issue(
                    "PROJ-2",
                    "Broker alert",
                    assignee="Ada\u00a0 Example",
                    labels=("backend", "cafe"),
                ),
                None,
            ),
            (issue("PROJ-3", "Broker retention", assignee="はら", labels=("Backend",)), None),
            (issue("PROJ-4", "Broker upgrade", assignee="Ada Example", labels=("\u2102",)), None),
        ],
    )
    for refused in ({"assignee": "오이디 아시"}, {"assignee": "ばら"}, {"label": "CAFÈ"}):
        with pytest.raises(UnanswerableError, match=r"^\S+: no document has "):
            library.search("broker", filters=refused)
    kept = {
        "에이다 예시": ["PROJ-1"],
        "Ada\u00a0 Example": ["PROJ-2", "PROJ-4"],
        "ada example": ["PROJ-2", "PROJ-4"],
    }
    for assignee, expected in kept.items():
        assert refs(library.search(filters={"assignee": assignee}, sort="created")) == expected
    labels = {
        "Backend": ["PROJ-3"],
        "BACKEND": ["PROJ-1", "PROJ-2"],
        "cafe\u0301": ["PROJ-1"],
        "c": ["PROJ-4"],  # the double-struck capital C, a capital once decomposed
    }
    for label, expected in labels.items():
        assert refs(library.search(filters={"label": label}, sort="created")) == expected


# The made-up people of tests/samples.py, each with the account id that Atlassian gives.
ACCOUNTS = {"A Person": "account-1", "Another Person": "account-2"}
EARLIER = CREATED - timedelta(days=7)


def held(role: str, name: str, *at: datetime) -> PersonRole:
    """Give one of ACCOUNTS's people in a role, with their account and comment times."""
    return PersonRole(role=role, name=name, account=ACCOUNTS[name], at=at)


# Four issues, each person in every role. A Person comments three times on PROJ-1 and
# once on PROJ-2, before the comment of Another Person's there; Another Person once on
# each of PROJ-2, PROJ-3 and PROJ-4. PROJ-2's creator is its author; PROJ-3 has none.
COMMENTED = (
    issue(
        "PROJ-1",
        "Broker crash",
        people=(
            held("author", "A Person"),
            held("creator", "Another Person"),
            held("assignee", "A Person"),
            held("commenter", "A Person", *(CREATED + timedelta(hours=n) for n in range(3))),
        ),
    ),
    issue(
        "PROJ-2",
        "Broker alert",
        people=(
            held("author", "Another Person"),
            held("creator", "Another Person"),
            held("commenter", "A Person", EARLIER),
            held("commenter", "Another Person", CREATED),
        ),
    ),
    issue(
        "PROJ-3",
        "Broker retention",
        people=(held("author", "A Person"), held("commenter", "Another Person", EARLIER)),
    ),
    issue(
        "PROJ-4",
        "Broker upgrade",
        people=(
            held("author", "Another Person"),
            held("creator", "A Person"),
            held("commenter", "Another Person", CREATED + timedelta(hours=3)),
        ),
    ),
)


@pytest.fixture
def commented(tmp_path: Path) -> Library:
    """Serve the issues of COMMENTED, beside the fillers."""
    return built(tmp_path, [(front, None) for front in COMMENTED])


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"creator": "another person"}, ["PROJ-1", "PROJ-2"]),
        ({"creator": "A PERSON"}, ["PROJ-4"]),
        ({"author": "another person"}, ["PROJ-2", "PROJ-4"]),
        ({"commenter": "a person"}, ["PROJ-1", "PROJ-2"]),
        ({"commenter": "another person"}, ["PROJ-2", "PROJ-3", "PROJ-4"]),
        ({"creator": "another person", "commenter": "another person"}, ["PROJ-2"]),
        ({"commented_after": "2026-10-25"}, ["PROJ-1", "PROJ-2", "PROJ-4"]),
        ({"commented_before": "2026-10-25"}, ["PROJ-2", "PROJ-3"]),
        ({"commented_after": "2026-10-25T02:00Z"}, ["PROJ-1", "PROJ-4"]),
        (
            {"commented_after": "2026-10-25T02:00:01Z", "commented_before": "2026-10-25T03:00Z"},
            [],
        ),
        ({"commented_after": "2026-10-20", "commented_before": "2026-10-24"}, []),
        ({"commenter": "a person", "commented_after": "2026-10-25"}, ["PROJ-1"]),
        ({"commenter": "another person", "commented_before": "2026-10-25"}, ["PROJ-3"]),
    ],
)
def test_creator_and_commenter_narrow_by_role_and_comment_dates_by_one_comment(
    commented: Library, filters: dict[str, str], expected: list[str]
) -> None:
    """A name matches the people of its role alone; a comment date, the commenter's comments.

    Without a commenter, anyone's. PROJ-2 has a comment of A Person's before the 25th and
    one of Another Person's on it: A Person did not comment there from the 25th on. Both
    dates are met by one comment: neither of PROJ-2's, on the 18th and the 25th, falls
    from the 20th to the 24th, though one is after the 20th and the other before the 24th.
    """
    assert sorted(refs(commented.search(filters=filters, sort="created"))) == expected
    assert sorted(refs(commented.search("broker", filters=filters))) == expected


@pytest.mark.parametrize(
    ("filters", "valid"),
    [
        ({"creator": "nobody"}, "Another Person, A Person"),
        ({"commenter": "nobody"}, "Another Person, A Person"),
        ({"assignee": "another person"}, "A Person"),
    ],
)
def test_a_name_that_no_document_has_in_its_role_is_refused_with_the_valid_ones(
    commented: Library, filters: dict[str, str], valid: str
) -> None:
    """The most frequent first, counted by documents: A Person's four comments are on two."""
    with pytest.raises(UnanswerableError) as refused:
        commented.search("broker", filters=filters)
    header, block, _ = parts(str(refused.value))
    assert (header.partition(":")[0], block) == (next(iter(filters)), valid)


def test_an_issue_s_hit_names_its_creator_only_when_not_its_author(commented: Library) -> None:
    """After the author, so that the usual issue, filed by its creator, costs nothing more."""
    assert dict(FACTS.findall(parts(commented.search("broker"))[1])) == {
        "PROJ-1": (
            "Task | To Do | assignee A Person | author A Person | creator Another Person"
            " | created 2026-10-20"
        ),
        "PROJ-2": "Task | To Do | unassigned | author Another Person | created 2026-10-20",
        "PROJ-3": "Task | To Do | unassigned | author A Person | created 2026-10-20",
        "PROJ-4": (
            "Task | To Do | unassigned | author Another Person | creator A Person"
            " | created 2026-10-20"
        ),
    }


def test_read_shows_each_role_by_name_and_a_commenter_s_count_and_last_day(
    commented: Library,
) -> None:
    """One line per role, in the order of the roles, before the created date."""
    expected = {
        "PROJ-1": [
            "author: A Person",
            "creator: Another Person",
            "assignee: A Person",
            "commenter: A Person (3, last 2026-10-25)",
        ],
        "PROJ-2": [
            "author: Another Person",
            "creator: Another Person",
            "commenter: A Person (1, last 2026-10-18); Another Person (1, last 2026-10-25)",
        ],
    }
    for ref, roles in expected.items():
        lines = parts(commented.read(ref))[1].splitlines()
        start = lines.index(roles[0])
        assert lines[start : start + len(roles) + 1] == [*roles, "created: 2026-10-20 21:52 UTC"]


def test_read_names_ten_people_of_a_role_whole_then_how_many_more(tmp_path: Path) -> None:
    """A name that a hit cuts at 60 characters comes whole; the line, though long, too."""
    names = [f"Person {number:02} {'x' * 60}" for number in range(12)]
    people = (
        PersonRole(role="author", name=names[0]),
        *(PersonRole(role="commenter", name=each, at=(CREATED,)) for each in names),
    )
    library = built(tmp_path, [(issue("PROJ-1", "Broker", people=people), None)])
    assert f"| author {names[0][:59]}… |" in library.search("broker")
    shown = "; ".join(f"{each} (1, last 2026-10-25)" for each in names[:10])
    read = parts(library.read("PROJ-1"))[1]
    assert f"\nauthor: {names[0]}\n" in read
    assert f"\ncommenter: {shown}; 2 more\n" in read


def test_no_answer_holds_an_account_id(commented: Library, tmp_path: Path) -> None:
    """The mirror keeps each person's account id; the tools serve names alone."""
    mirrored = (tmp_path / "docs" / location(COMMENTED[0])).read_text(encoding="utf-8")
    assert ACCOUNTS["A Person"] in mirrored
    answers = [
        commented.search("broker"),
        commented.search(filters={"commenter": "a person"}, sort="created"),
        commented.ask("broker crash"),
        *(commented.read(front.key or front.id) for front in COMMENTED),
        commented.browse(project="PROJ"),
        commented.status(),
    ]
    with pytest.raises(UnanswerableError) as refused:
        commented.search(filters={"commenter": "nobody"})
    served = [*answers, str(refused.value)]
    assert [each for each in served if any(id_ in each for id_ in ACCOUNTS.values())] == []


def worklog(kind: str, id_: str, title: str, *names: str) -> FrontMatter:
    """Give a meeting or a transcript of the work log, its participants by name, in order."""
    return replace(
        page(id_, title),
        source="worklog",
        type=kind,
        space=None,
        people=tuple(PersonRole(role="participant", name=name) for name in names),
        version=None,
        revision="0123456789abcdef",
    )


# Three meetings and three transcripts, beside the fillers, which A Person wrote, and a
# page that Sam Sample wrote. By meetings, then documents: Sam Sample 3 and 4, Alex
# Example 2 and 3, Robin Example 1 and 2, Kim (not in the header) 1 and 1; You, whom the
# caption tool writes, 0 and 3, more documents than Robin's; Unverified 0 and 1. The
# stand-up and its transcript link each other.
MET = (
    page("196845", "Lorem notes", author="Sam Sample"),
    replace(
        worklog(
            "meeting",
            "m-20261027-payments-stand-up",
            "Payments stand-up",
            *("Alex Example", "Sam Sample"),
        ),
        links=(Link(relation="transcript", ref="t-20261027-1"),),
    ),
    worklog(
        "meeting",
        "m-20261027-ledger-review",
        "Ledger review",
        *("Robin Example", "Kim (not in the header)", "Sam Sample"),
    ),
    worklog("meeting", "m-20261027-vendor-call", "Vendor call", "Sam Sample", "Alex Example"),
    replace(
        worklog("transcript", "t-20261027-1", "Stand-up", "Alex Example", "Sam Sample", "You"),
        links=(Link(relation="summary", ref="m-20261027-payments-stand-up"),),
    ),
    worklog("transcript", "t-20261020-1", "Retrospective", "You", "Unverified"),
    worklog("transcript", "t-20261021-1", "Planning", "You", "Robin Example"),
)


@pytest.fixture
def met(tmp_path: Path) -> Library:
    """Serve the documents of MET, beside the fillers."""
    return built(tmp_path, [(front, None) for front in MET])


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "sam sample",
            [
                "m-20261027-ledger-review",
                "m-20261027-payments-stand-up",
                "m-20261027-vendor-call",
                "t-20261027-1",
            ],
        ),
        ("KIM (not in the HEADER)", ["m-20261027-ledger-review"]),
        ("kim", ["m-20261027-ledger-review"]),
        ("you", ["t-20261020-1", "t-20261021-1", "t-20261027-1"]),
    ],
)
def test_participant_narrows_to_the_documents_naming_that_person_in_any_case(
    met: Library, name: str, expected: list[str]
) -> None:
    """A meeting's participants and a transcript's speakers alike, by their whole name.

    Sam Sample's page is not among them: its author is no participant. Since plan 043, a
    trailing part in brackets is no part of a name: Kim is Kim (not in the header).
    """
    filters = {"participant": name}
    assert sorted(refs(met.search(filters=filters, sort="created"))) == expected
    assert sorted(refs(met.search("lorem", filters=filters))) == expected


@pytest.mark.parametrize(
    ("filters", "valid"),
    [
        (
            {"participant": "nobody"},
            "Sam Sample, Alex Example, Robin Example, Kim (not in the header), You, Unverified",
        ),
        (
            {"participant": "robin"},
            "Robin Example, Sam Sample, Alex Example, Kim (not in the header), You, Unverified",
        ),
        (
            {"participant": "a person"},
            "Sam Sample, Alex Example, Robin Example, Kim (not in the header), You, Unverified",
        ),
        ({"author": "alex example"}, "A Person, Sam Sample"),
    ],
)
def test_a_participant_that_no_document_names_is_refused_meetings_first(
    met: Library, filters: dict[str, str], valid: str
) -> None:
    """By the meetings naming them, then the documents: You never leads, nor Unverified.

    A name matches whole, so Robin alone is not Robin Example, listed first as the name
    that holds it. A Person, the fillers' author, is no participant, nor is a participant
    an author.
    """
    with pytest.raises(UnanswerableError) as refused:
        met.search("lorem", filters=filters)
    header, block, _ = parts(str(refused.value))
    assert (header.partition(":")[0], block) == (next(iter(filters)), valid)


def test_read_shows_a_meeting_s_participants_and_its_transcript_and_back(met: Library) -> None:
    """Participants as written, in order, then the link's line, before the created date.

    The ref that the line gives opens the document linked, which links back.
    """
    expected = {
        "m-20261027-payments-stand-up": [
            "participant: Alex Example; Sam Sample",
            "transcript: t-20261027-1",
        ],
        "t-20261027-1": [
            "participant: Alex Example; Sam Sample; You",
            "summary: m-20261027-payments-stand-up",
        ],
    }
    for ref, lines in expected.items():
        shown = parts(met.read(ref))[1].splitlines()
        start = shown.index(lines[0])
        assert shown[start : start + 3] == [*lines, "created: 2026-10-20 21:52 UTC"]
        linked = lines[1].partition(": ")[2]
        assert f"ref: {linked}" in parts(met.read(linked))[1].splitlines()


def test_read_names_ten_links_of_a_relation_whole_then_how_many_more(tmp_path: Path) -> None:
    """Twelve meetings that one transcript summarises, each id of 64 characters after its day."""
    meetings = [f"m-20261027-{number:02}-{'x' * 61}" for number in range(12)]
    links = tuple(Link(relation="summary", ref=each) for each in meetings)
    front = replace(worklog("transcript", "t-20261027-1", "Stand-up"), links=links)
    read = parts(built(tmp_path, [(front, None)]).read("t-20261027-1"))[1]
    assert f"\nsummary: {'; '.join(meetings[:10])}; 2 more\n" in read
    assert "\ntranscript:" not in read


# Plan 043's persons, over the mirror of tests.mirrors.PERSONS: Robin Example's account,
# written Robin Sample on its newest document, wrote a page, created an issue and
# commented twice on another, and attended three meetings, the review's transcript
# naming Robin, who speaks there.
ROBIN_DOCUMENTS = [
    "300001",
    "PAY-1",
    "PAY-2",
    "m-20261020-planning",
    "m-20261020-review",
    "m-20261020-stand-up",
    "t-20261020-1",
]


@pytest.fixture
def persons(tmp_path: Path) -> Library:
    """Serve the documents of PERSONS, beside the fillers, joined without aliases."""
    return built(tmp_path, [(front, None) for front in PERSONS])


@pytest.mark.parametrize("value", ["robin example", "Robin Sample", ROBIN])
def test_a_person_is_found_in_any_role_by_any_of_their_names_or_their_id(
    persons: Library, value: str
) -> None:
    """Plan 043, criterion 6: Robin's page, issues and meetings, of three sources, alike.

    With words or without.
    """
    filters = {"person": value}
    assert sorted(refs(persons.search(filters=filters, sort="created"))) == ROBIN_DOCUMENTS
    assert sorted(refs(persons.search("lorem", filters=filters))) == ROBIN_DOCUMENTS


def test_a_name_of_several_persons_is_refused_listing_each_by_id(persons: Library) -> None:
    """Without aliases, Sam Sample is two accounts and the stand-up's name alone.

    Each by name, id, documents by role then source, and the last day one was updated;
    the id of one keeps that person's documents alone.
    """
    with pytest.raises(UnanswerableError) as refused:
        persons.search("lorem", filters={"person": "Sam Sample"})
    header, block, _ = parts(str(refused.value))
    each = {
        SAM_2: f"Sam Sample, {SAM_2}: author 1; jira 1; last updated 2026-10-21",
        SAM_3: f"Sam Sample, {SAM_3}: author 1; jira 1; last updated 2026-10-20",
        SAM_ALONE: f"Sam Sample, {SAM_ALONE}: participant 2; worklog 2; last updated 2026-10-20",
    }
    assert header.strip() == 'person: "Sam Sample" names 3 people; give the id of one:'
    assert block.splitlines() == [each[person] for person in sorted(each)]
    assert refs(persons.search(filters={"person": SAM_3}, sort="created")) == ["PAY-2"]
    alone = sorted(refs(persons.search(filters={"person": SAM_ALONE}, sort="created")))
    assert alone == ["m-20261020-stand-up", "t-20261020-3"]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"creator": "Robin Sample"}, ["PAY-1"]),
        ({"creator": "robin example"}, ["PAY-1"]),
        ({"commenter": "Robin Sample"}, ["PAY-2"]),
        ({"author": ROBIN}, ["300001"]),
        (
            {"participant": "Alex Example"},
            ["m-20261020-review", "m-20261020-stand-up", "t-20261020-1"],
        ),
        ({"person": ALEX}, ["t-20261021-1", "t-20261021-2"]),
    ],
)
def test_each_filter_of_a_role_keeps_its_person_under_any_of_their_names(
    persons: Library, filters: dict[str, str], expected: list[str]
) -> None:
    """Robin created PAY-1 as Robin Sample, and commented on PAY-2 as Robin Example.

    Alex Example (not in the header) is the stand-up's Alex Example, and Alex the
    review's, by its transcript; Alex in the two unlinked transcripts, a person apart.
    """
    assert sorted(refs(persons.search(filters=filters, sort="created"))) == expected


@pytest.mark.parametrize(
    ("filters", "several"),
    [
        ({"author": "Sam Sample"}, [SAM_2, SAM_3]),
        ({"participant": "robin"}, [ROBIN, ROBIN_ALONE]),
        ({"person": "Alex"}, [ALEX, ALEX_EXAMPLE]),
    ],
)
def test_a_role_s_name_is_refused_when_several_persons_hold_it_there(
    persons: Library, filters: dict[str, str], several: list[str]
) -> None:
    """Only those with a document in the role: the stand-up's Sam Sample wrote nothing.

    The review's Robin is Robin Example's account, the planning's a person apart; the
    review's Alex is Alex Example, the unlinked transcripts' another. By id, in order.
    """
    with pytest.raises(UnanswerableError) as refused:
        persons.search(filters=filters, sort="created")
    header, block, _ = parts(str(refused.value))
    assert header.startswith(f"{next(iter(filters))}: ")
    assert [line.split(", ")[1].partition(":")[0] for line in block.splitlines()] == several


@pytest.mark.parametrize(
    "filters",
    [{"author": "Alex Example"}, {"creator": SAM_3}, {"person": "p-0123456789abcdef"}],
)
def test_a_person_without_a_document_in_the_role_is_refused_with_its_names(
    persons: Library, filters: dict[str, str]
) -> None:
    """As a name that no document has: Alex Example wrote nothing, PAY-2's author created none.

    An id that no person has, likewise.
    """
    with pytest.raises(UnanswerableError, match=r"^\S+: no document has "):
        persons.search(filters=filters, sort="created")


def test_a_person_s_answer_opens_with_who_they_are_and_each_hit_ends_with_their_roles(
    persons: Library,
) -> None:
    """Plan 043, criterion 6, the newest first: Robin's names and how each joined.

    Robin's account is named as on PAY-1, its newest document; its names are written by
    the account, by name in the meetings, and as the review's speaker. The documents by
    role and by source, the most first; the unlinked Robin, perhaps the same, with the
    alias that would join them. Each hit's line of who and when ends with Robin's roles
    there, a commenter's with the comments' count and the last day.
    """
    block = parts(persons.search(filters={"person": "Robin Example"}, sort="updated"))[1]
    header, _, hits = block.partition("\n\n")
    assert header.splitlines() == [
        (
            f"Person: Robin Sample, {ROBIN}: participant 4, author 1, commenter 1, creator 1;"
            " worklog 4, jira 2, confluence 1; last updated 2026-10-21."
        ),
        (
            "Names: Robin Example, Robin Sample by its account; Robin Example, robin EXAMPLE"
            " by name; Robin as a speaker, by the meeting of each transcript."
        ),
        (
            f"Perhaps the same, not joined: {ROBIN_ALONE};"
            f' the alias "Robin" = "{ROBIN}" would join them.'
        ),
    ]
    roles = {ref: facts.rpartition(" | ")[2] for ref, facts in FACTS.findall(hits)}
    assert list(roles.items()) == [
        ("PAY-1", "Robin Sample: creator"),
        ("300001", "Robin Sample: author"),
        ("PAY-2", "Robin Sample: commenter 2 (last 2026-10-20)"),
        ("m-20261020-planning", "Robin Sample: participant"),
        ("m-20261020-review", "Robin Sample: participant"),
        ("m-20261020-stand-up", "Robin Sample: participant"),
        ("t-20261020-1", "Robin Sample: participant"),
    ]


def test_a_person_s_roles_on_a_hit_come_in_the_order_of_the_roles(commented: Library) -> None:
    """A Person wrote PROJ-1, is assigned it and commented three times; created PROJ-4."""
    filters = {"person": "a person", "source": "jira"}
    block = parts(commented.search(filters=filters, sort="created"))[1]
    assert {ref: facts.rpartition(" | ")[2] for ref, facts in FACTS.findall(block)} == {
        "PROJ-1": "A Person: author, assignee, commenter 3 (last 2026-10-25)",
        "PROJ-2": "A Person: commenter 1 (last 2026-10-18)",
        "PROJ-3": "A Person: author",
        "PROJ-4": "A Person: creator",
    }


def test_a_filter_of_a_role_adds_no_person_to_the_answer(persons: Library) -> None:
    """The person and the roles on hits come with person alone."""
    block = parts(persons.search(filters={"creator": "Robin Sample"}, sort="updated"))[1]
    assert dict(FACTS.findall(block)) == {
        "PAY-1": (
            "Task | To Do | unassigned | author Sam Sample | creator Robin Sample"
            " | created 2026-10-20"
        )
    }
    assert not block.startswith("Person:")


def test_no_answer_about_persons_holds_an_account_id(persons: Library) -> None:
    """Plan 043, criterion 6: ids of persons are served, never those of accounts."""
    answers = [
        persons.search(filters={"person": "Robin Example"}, sort="updated"),
        persons.search("ledger", filters={"person": SAM_2}),
        persons.ask("ledger", filters={"person": "Robin Sample"}),
        *(persons.read(front.key or front.id) for front in PERSONS),
        persons.status(),
    ]
    for filters in ({"person": "Sam Sample"}, {"author": "Sam Sample"}, {"person": "nobody"}):
        with pytest.raises(UnanswerableError) as refused:
            persons.search(filters=filters, sort="updated")
        answers.append(str(refused.value))
    assert [answer for answer in answers if "acct-" in answer] == []


@pytest.mark.parametrize(
    "ref",
    [
        "196845",
        "https://x.atlassian.net/wiki/spaces/ENG/pages/196845/Kafka+runbook",
        "confluence/ENG/196845-kafka-runbook.md",
    ],
)
def test_read_finds_a_page_by_id_address_and_path(varied: Library, ref: str) -> None:
    """Every form of ref opens the same page."""
    assert "\ntitle: Kafka runbook\n" in f"\n{parts(varied.read(ref))[1]}"


@pytest.mark.parametrize("ref", ["proj-7", "https://x.atlassian.net/browse/PROJ-7?focus=1"])
def test_read_finds_an_issue_by_key_and_address(varied: Library, ref: str) -> None:
    """An issue opens by its key, in any case, or its address."""
    assert parts(varied.read(ref))[1].startswith("title: Kafka upgrade\n")


@pytest.mark.parametrize("ref", ["999999", "NOPE-1", "jira/NOPE/NOPE-1.md", "kafka"])
def test_an_unknown_ref_is_not_mirrored(varied: Library, ref: str) -> None:
    """A ref that the mirror does not hold is answered, not refused."""
    assert varied.read(ref).startswith("Not mirrored:")


def test_a_section_starts_at_its_heading_and_stops_at_the_next(tmp_path: Path) -> None:
    """Reading a section gives it whole, then names the next section's call."""
    body = "# Kafka\n\nLead.\n\n## Retention\n\nSeven days.\n\n## Compaction\n\nLast value.\n"
    library = built(tmp_path, [(page("196845", "Kafka"), body)])
    answer = library.read("196845", section=2)
    assert parts(answer)[1].split("\n\n", 1)[1] == "## Retention\n\nSeven days.\n\n"
    assert answer.endswith('Next section: read(ref="196845", section=3)')
    assert continuation(library.read("196845", section=3)) is None


def test_offsets_reach_the_last_character_and_stop_there(tmp_path: Path) -> None:
    """The last character of a body or a section is an offset; the end is not."""
    body = "# Kafka\n\nLead.\n\n## Retention\n\nSeven days.\n\n## Compaction\n\nLast value.\n"
    library = built(tmp_path, [(page("196845", "Kafka"), body)])
    last = parts(library.read("196845", offset=len(body) - 1))[1].split("\n\n", 1)[1]
    assert last == "\n"
    with pytest.raises(UnanswerableError, match=f"offset: 0 to {len(body) - 1} here"):
        library.read("196845", offset=len(body))
    end = body.index("## Compaction")
    assert parts(library.read("196845", section=2, offset=end - 1))[1].endswith("\n\n\n")
    with pytest.raises(UnanswerableError, match="offset: "):
        library.read("196845", section=2, offset=end)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"section": 4}, "section: 1 to 3 for this document"),
        ({"section": 0}, "section: 1 to 3 for this document"),
        ({"offset": 10_000}, "offset: 0 to "),
        ({"section": 2, "offset": 0}, "offset: "),
    ],
)
def test_out_of_range_is_refused(tmp_path: Path, arguments: dict[str, int], message: str) -> None:
    """A section or an offset outside the document or its section is refused."""
    body = "# Kafka\n\nLead.\n\n## Retention\n\nSeven days.\n\n## Compaction\n\nLast value.\n"
    library = built(tmp_path, [(page("196845", "Kafka"), body)])
    with pytest.raises(UnanswerableError, match=re.escape(message)):
        library.read("196845", **arguments)


def test_every_slice_carries_the_mirror_date(tmp_path: Path) -> None:
    """The first slice has every key; later ones the title, path and mirror date."""
    library = built(tmp_path, [(page("196845", "Kafka", labels=("ops",)), None)])
    first = library.read("196845", max_chars=20)
    assert "\nlabels: ops\n" in parts(first)[1]
    later = follow(library, first)
    assert later is not None
    frame = parts(later)[1].split("\n\n", 1)[0]
    assert frame.splitlines() == [
        "title: Kafka",
        f"path: {location(page('196845', 'Kafka'))}",
        "mirrored: 2026-10-20 21:52 UTC",
    ]


def tree_lines(answer: str) -> list[str]:
    """List the lines of a browse answer's block, without their dates."""
    return [re.sub(r", updated .*\)$", ")", line) for line in parts(answer)[1].splitlines()]


def test_a_space_is_browsed_depth_first(tmp_path: Path) -> None:
    """Parents come before children, numbers in order, folders as context lines."""
    library = built(
        tmp_path,
        [
            (page("100", "Home", space="DOC"), None),
            (page("101", "A", space="DOC", breadcrumb=("Home",)), None),
            (page("102", "A B", space="DOC", breadcrumb=("Home",)), None),
            (page("103", "Item 10", space="DOC", breadcrumb=("Home", "Folder")), None),
            (page("104", "Item 2", space="DOC", breadcrumb=("Home", "Folder")), None),
            (page("105", "Child", space="DOC", breadcrumb=("Home", "A")), None),
        ],
    )
    assert tree_lines(library.browse(space="doc")) == [
        "- Home (100)",
        "  - A (101)",
        "    - Child (105)",
        "  - A B (102)",
        "  - [Folder]",
        "    - Item 2 (104)",
        "    - Item 10 (103)",
    ]
    assert tree_lines(library.browse(space="DOC", parent="101")) == ["- Child (105)"]


def test_documents_with_one_place_in_the_tree_come_by_path(tmp_path: Path) -> None:
    """Two pages of one title under one parent keep one order, page after page."""
    library = built(
        tmp_path,
        [
            (page("102", "Same", space="DOC"), f"# Same\n\n{LOREM}\n"),
            (page("101", "Same", space="DOC"), f"# Same\n\n{LOREM}\n"),
        ],
    )
    first = library.browse(space="DOC", limit=1)
    second = follow(library, first)
    assert second is not None
    assert [tree_lines(first), tree_lines(second)] == [["- Same (101)"], ["- Same (102)"]]


def test_a_page_of_results_names_the_ancestors_of_its_first_line(tmp_path: Path) -> None:
    """A page that starts inside a subtree begins with one context line."""
    library = built(
        tmp_path,
        [
            (page("100", "Home", space="DOC"), None),
            (page("101", "A", space="DOC", breadcrumb=("Home",)), None),
            (page("105", "Child", space="DOC", breadcrumb=("Home", "A")), None),
        ],
    )
    second = follow(library, library.browse(space="DOC", limit=2))
    assert second is not None
    assert tree_lines(second)[0] == "- [Home / A]"
    assert tree_lines(second)[1] == "    - Child (105)"


def test_a_project_is_browsed_by_parent_chains(tmp_path: Path) -> None:
    """An epic, its story and the story's sub-task nest, whatever their numbers."""
    library = built(
        tmp_path,
        [
            (issue("PROJ-10", "Epic"), None),
            (issue("PROJ-2", "Story", breadcrumb=("PROJ-10",)), None),
            (issue("PROJ-1", "Sub-task", breadcrumb=("PROJ-2",)), None),
            (issue("PROJ-3", "Orphan", breadcrumb=("OTHER-1",)), None),
            (issue("PROJ-20", "Late"), None),
            (issue("PROJ-9", "Early"), None),
        ],
    )
    assert tree_lines(library.browse(project="PROJ")) == [
        "- [OTHER-1]",
        "  - Orphan (PROJ-3)",
        "- Early (PROJ-9)",
        "- Epic (PROJ-10)",
        "  - Story (PROJ-2)",
        "    - Sub-task (PROJ-1)",
        "- Late (PROJ-20)",
    ]


def test_a_deep_chain_still_moves_on(tmp_path: Path) -> None:
    """Sixty levels of long folder titles leave room for one document per page."""
    folders = tuple(f"Folder {level} " + "x" * 190 for level in range(60))
    documents = [page(str(200 + n), f"Deep {n}", space="DOC", breadcrumb=folders) for n in range(3)]
    library = built(tmp_path, [(front, None) for front in documents])
    answer: str | None = library.browse(space="DOC", limit=1)
    seen = []
    while answer is not None:
        seen += re.findall(r"\((\d+), updated", answer)
        answer = follow(library, answer)
    assert seen == ["200", "201", "202"]


def test_browse_needs_space_or_project(varied: Library) -> None:
    """Neither, or both, is refused, listing the spaces and projects."""
    with pytest.raises(UnanswerableError) as refused:
        varied.browse()
    assert parts(str(refused.value))[1] == "space ENG, space OPS, project PROJ"


def test_status_says_what_the_index_holds(varied: Library) -> None:
    """Counts by type, space and project, and the build time."""
    content = parts(varied.status())[1]
    assert "documents: page 32, issue 2; sections: " in content
    assert "spaces: ENG 31, OPS 1\nprojects: PROJ 2\n" in content
    assert content.startswith("built: 2026-10-20 21:52 UTC\n")


def test_no_index_is_refused_with_the_command_that_builds_it(tmp_path: Path) -> None:
    """Every tool says how to build a missing index."""
    library = built(tmp_path, [])
    (tmp_path / "index.sqlite").unlink()
    with pytest.raises(UnanswerableError, match="atlassian-offline-mcp index"):
        library.status()


def test_each_tool_shows_the_mirror_date_apart_from_the_others(tmp_path: Path) -> None:
    """The date of the copy, not of the last edit, is what each answer calls mirrored."""
    fetched, created = MOMENT + timedelta(days=3), MOMENT - timedelta(days=10)
    front = page("196845", "Kafka", fetched_at=fetched, created=created, labels=("ops",))
    library = built(tmp_path, [(front, None)])
    assert "| updated 2026-10-20 21:52 UTC | mirrored 2026-10-23 |" in library.search("kafka")
    first = parts(library.read("196845", max_chars=20))[1]
    for line in ("mirrored: 2026-10-23 21:52 UTC", "created: 2026-10-10 21:52 UTC"):
        assert f"\n{line}\n" in first
    assert "\nupdated: 2026-10-20 21:52 UTC\n" in first
    later = follow(library, library.read("196845", max_chars=20))
    assert later is not None
    assert "\nmirrored: 2026-10-23 21:52 UTC\n" in parts(later)[1]
    assert "(196845, updated 2026-10-20, mirrored 2026-10-23)" in library.browse(space="ENG")
    assert "\nnewest mirror date: 2026-10-23 21:52 UTC\n" in library.status()


def test_what_changed_pages_through_every_document_once(varied: Library) -> None:
    """Following the cursor of a listing by update gives each document once, in order."""
    answer: str | None = varied.search(sort="updated")
    headers, found = [], []
    while answer is not None:
        headers.append(parts(answer)[0])
        found += refs(answer)
        answer = follow(varied, answer)
    every = FILLERS + 4  # the fillers, and the four documents of the fixture
    assert len(found) == len(set(found)) == every
    assert headers[:2] == [
        f"Documents found: {every}; 1 to 8 below. Index built 2026-10-20 21:52 UTC.\n",
        f"Documents found: {every}; 9 to 16 below. Index built 2026-10-20 21:52 UTC.\n",
    ]


@pytest.mark.parametrize("parent", ["999999", "PROJ-7", "196846"])
def test_a_parent_outside_the_space_is_not_mirrored(varied: Library, parent: str) -> None:
    """A parent that the space does not hold lists nothing."""
    assert varied.browse(space="ENG", parent=parent).startswith("Not mirrored:")


def test_only_a_query_of_more_than_ten_words_is_said_cut(tmp_path: Path) -> None:
    """Ten words are all searched; the eleventh is not, and the answer says so."""
    library = built(tmp_path, [])
    note = "Only the first 10 words of the query were searched."
    ten = " ".join(f"word{number}" for number in range(10))
    assert note not in library.search(ten)
    assert note in library.search(f"{ten} word10")


def test_hits_show_a_status_other_than_current(varied: Library) -> None:
    """A page's usual status goes unsaid; an issue's is shown."""
    answer = varied.search("kafka")
    assert "| current" not in answer
    assert "| Task | Done |" in answer


def test_each_hit_ends_its_second_line_with_who_and_when(people: Library) -> None:
    """An issue's type, status, assignee, author and created day; a page's author and day."""
    assert dict(FACTS.findall(parts(people.search("broker"))[1])) == {
        "PROJ-1": "Bug | Done | assignee Ada Example | author Bo Sample | created 2026-10-25",
        "PROJ-2": (
            "Task | To Do | assignee Hélène Example | author Ada Example | created 2026-10-22"
        ),
        "PROJ-3": "Story | To Do | assignee Ada Example | author A Person | created 2026-10-25",
        "196845": "author Bo Sample | created 2026-10-21",
    }


def test_a_hit_cuts_each_name_type_and_status_at_60_characters(tmp_path: Path) -> None:
    """As labels are: 59 characters and an ellipsis."""
    long = "Long name " * 10
    front = issue("PROJ-1", "Broker", issue_type=long, status=long, assignee=long, author=long)
    library = built(tmp_path, [(front, None)])
    cut = f"{long[:59]}…"
    assert dict(FACTS.findall(parts(library.search("broker"))[1])) == {
        "PROJ-1": f"{cut} | {cut} | assignee {cut} | author {cut} | created 2026-10-20"
    }


def test_an_issue_without_assignee_says_so_and_a_work_log_entry_its_status(
    tmp_path: Path,
) -> None:
    """An issue says unassigned, so that none reads it as unknown; an entry has no author."""
    entry = replace(
        page("e-0123456789abcdef-2", "Broker notes", status="WAITING"),
        source="worklog",
        type="entry",
        space=None,
        people=(),
        version=None,
        revision="0123456789abcdef",
        created=MOMENT - timedelta(days=2),
    )
    library = built(tmp_path, [(issue("PROJ-8", "Broker rollback"), None), (entry, None)])
    assert dict(FACTS.findall(parts(library.search("broker"))[1])) == {
        "PROJ-8": "Task | To Do | unassigned | author A Person | created 2026-10-20",
        "e-0123456789abcdef-2": "WAITING | created 2026-10-18",
    }


def test_a_document_shows_ten_labels_at_most(tmp_path: Path) -> None:
    """Labels beyond the tenth are left out of the metadata."""
    labels = tuple(f"label{number}" for number in range(12))
    library = built(tmp_path, [(page("196845", "Kafka", labels=labels), None)])
    shown = parts(library.read("196845"))[1]
    assert f"\nlabels: {', '.join(labels[:10])}\n" in shown
