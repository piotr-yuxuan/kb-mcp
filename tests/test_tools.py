"""The four tools on small mirrors: ranking, filters, reading and browsing."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.adapters import sqlite_index
from atlassian_offline_mcp.app.tools import UnanswerableError
from tests.answers import built, continuation, follow, parts
from tests.mirrors import LOREM, MOMENT, issue, location, page

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

    from atlassian_offline_mcp.app.tools import Library

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


def test_a_long_pages_title_beats_a_newer_body_match(tmp_path: Path) -> None:
    """A title word of a page of 200 sections keeps its rarity, and so its weight."""
    long_body = "# Terraform modules\n\n" + "".join(
        f"## Part {number}\n\n{LOREM}\n\n" for number in range(200)
    )
    library = built(
        tmp_path,
        [
            (page("196845", "Terraform modules"), long_body),
            (
                page("196846", "Infrastructure", updated=NEWER),
                f"# Infrastructure\n\nWe use terraform. {LOREM}\n",
            ),
        ],
    )
    assert refs(library.search("terraform"))[:2] == ["196845", "196846"]


def test_a_capped_expression_says_at_least(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """When an expression reaches its cap of documents, the count is a lower bound."""
    library = built(tmp_path, [])
    monkeypatch.setattr(sqlite_index, "PER_EXPRESSION", 3)
    assert parts(library.search("lorem"))[0].startswith("Documents found: at least 3;")
    assert parts(library.search("lorem", sort="updated"))[0].startswith("Documents found: 30;")


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
        ],
    )
    assert tree_lines(library.browse(project="PROJ")) == [
        "- [OTHER-1]",
        "  - Orphan (PROJ-3)",
        "- Epic (PROJ-10)",
        "  - Story (PROJ-2)",
        "    - Sub-task (PROJ-1)",
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
