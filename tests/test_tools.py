"""The four tools on small mirrors: ranking, filters, reading and browsing."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.mcp.app.tools import UnanswerableError
from atlassian_offline_mcp.search.adapters import sqlite_index
from tests.answers import built, continuation, follow, parts
from tests.mirrors import FILLERS, LOREM, MOMENT, issue, location, page

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

    from atlassian_offline_mcp.mcp.app.tools import Library

NEWER = MOMENT + timedelta(days=1)
HIT = re.compile(r"^\d+\. .*\n {3}(\S+) \|", re.MULTILINE)


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
    assert "| updated 2026-10-20 21:52 UTC | mirrored 2026-10-23\n" in library.search("kafka")
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
    assert "| Done\n" in answer


def test_a_document_shows_ten_labels_at_most(tmp_path: Path) -> None:
    """Labels beyond the tenth are left out of the metadata."""
    labels = tuple(f"label{number}" for number in range(12))
    library = built(tmp_path, [(page("196845", "Kafka", labels=labels), None)])
    shown = parts(library.read("196845"))[1]
    assert f"\nlabels: {', '.join(labels[:10])}\n" in shown
