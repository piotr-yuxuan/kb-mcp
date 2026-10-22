"""``ask``: passages to quote, verbatim, within one budget, by each chunking (plan 019).

Each expected passage is written out by hand from the plan's rules: by words, the
section that holds the question's words, cut after a line break within 2,400
characters; by meaning, the unit of the chunking.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from atlassian_offline_mcp.mcp.app.tools import Library, UnanswerableError
from atlassian_offline_mcp.search.app.indexing import Embedding, build_index
from atlassian_offline_mcp.search.app.meaning import Meaning
from tests.answers import BUDGET, built, continuation, estimate, follow, parts
from tests.endpoint import connector, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.tempdir import TempPathFactory

    from atlassian_offline_mcp.kernel.chunking import Chunking
    from atlassian_offline_mcp.mcp.app.tools import SearchFilters

# A passage's two lines about it, then its text, which runs to the next passage.
ABOUT = re.compile(
    r"^(\d+)\. (.*) \| (\S+) \| section (\d+)(?:: (.*))? \| updated (\d{4}-\d\d-\d\d \d\d:\d\d UTC)"
    r" \| mirrored (\d{4}-\d\d-\d\d)\n(.*) \| (read\(.*\))\n",
    re.MULTILINE,
)
RETENTION = (
    "# Kafka\n\nLead.\n\n## Retention\n\nKafka keeps logs for seven days.\n\n## Other\n\nNone.\n"
)
# A section of 4,500 characters, longer than a unit: 150 lines of 30 characters.
LONG = "# Brokers\n\n## Sizing\n\n" + "broker sizing note, kept here\n" * 150
# A section whose only line breaks are in its first lines: cut at 2,400 characters.
PARAGRAPH = "# Pools\n\n## Pooling\n\n" + "pool sizing words " * 250
# One short section, near "vacation lunch" by meaning.
HOLIDAY = "# Holiday canteen\n\nLeave for a meal.\n"
UNIT = 2400
ENOUGH = 40  # documents holding a word, more than one answer quotes


def passages(answer: str) -> list[dict[str, str]]:
    """Read each passage of an answer: what its lines say, and its text."""
    block = parts(answer)[1]
    found = list(ABOUT.finditer(block))
    ends = [match.start() - 2 for match in found[1:]] + [len(block)]
    names = ("number", "title", "ref", "section", "heading", "updated", "mirrored", "address")
    return [
        dict(zip(names, match.groups()[:8], strict=True))
        | {"read": match[9], "text": block[match.end() : end]}
        for match, end in zip(found, ends, strict=True)
    ]


@pytest.fixture(scope="module")
def words(tmp_path_factory: TempPathFactory) -> Library:
    """Serve a mirror by words alone: Kafka's retention, a long section, an issue, many pages."""
    documents = [
        (page("196845", "Kafka", url="https://example.atlassian.net/wiki/x/1"), RETENTION),
        (page("196846", "Brokers"), LONG),
        (issue("PROJ-7", "Upgrade the brokers"), "# Upgrade the brokers\n\nPlanned.\n"),
        (page("196847", "Pools"), PARAGRAPH),
        *(
            (page(str(700000 + number), f"Gamma {number}"), f"# Gamma {number}\n\ngamma notes\n")
            for number in range(ENOUGH)
        ),
    ]
    return built(tmp_path_factory.mktemp("ask"), documents)


def test_a_passage_quotes_the_section_that_holds_the_words(words: Library) -> None:
    """Its text is the section as the mirror holds it; its lines say what and where it is."""
    (first, *_) = passages(words.ask("how long does kafka keep logs?"))
    section = RETENTION[RETENTION.index("## Retention") : RETENTION.index("## Other")]
    assert first["text"] == section
    assert (first["title"], first["ref"], first["section"], first["heading"]) == (
        "Kafka",
        "196845",
        "2",
        "Retention",
    )
    assert (first["updated"], first["mirrored"]) == ("2026-10-20 21:52 UTC", "2026-10-20")
    assert first["address"] == "https://example.atlassian.net/wiki/x/1"
    assert first["read"] == 'read(ref="196845", section=2)'
    assert section in words.read("196845", section=2)


def test_a_long_section_is_cut_after_a_line_within_2400_characters(words: Library) -> None:
    """4,500 characters: the passage ends at the last line break of the first 2,400."""
    (first, *_) = passages(words.ask("broker sizing"))
    section = LONG[LONG.index("## Sizing") :]
    within = section[:UNIT]
    assert first["text"] == within[: within.rfind("\n") + 1]
    assert first["address"] == "confluence/ENG/196846-brokers.md"


def test_a_long_paragraph_is_cut_at_2400_characters(words: Library) -> None:
    """No line break in the second half of the 2,400: none is waited for."""
    (first, *_) = passages(words.ask("pool sizing"))
    assert first["text"] == PARAGRAPH[PARAGRAPH.index("## Pooling") :][:UNIT]


def test_an_answer_is_one_block_within_the_budget_and_goes_on(words: Library) -> None:
    """At most 4,000 estimated tokens; following the calls gives each document once."""
    answer: str | None = words.ask("gamma notes")
    refs: list[str] = []
    while answer is not None:
        assert estimate(answer) <= BUDGET
        assert parts(answer)[1]
        refs += [each["ref"] for each in passages(answer)]
        answer = follow(words, answer)
    assert len(refs) == len(set(refs)) == ENOUGH
    first = words.ask("gamma notes")
    assert continuation(first) is not None
    assert first.startswith(f"Documents found: {ENOUGH}; 1 to ")


def test_an_issue_key_in_the_question_puts_its_issue_first(words: Library) -> None:
    """Named, it comes first, though another document holds the words better."""
    (first, second, *_) = passages(words.ask("is PROJ-7 about kafka retention?"))
    assert (first["ref"], second["ref"]) == ("PROJ-7", "196845")


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ({"spaec": "ENG"}, "filters: no spaec"),
        ({"space": "NOPE"}, "space: no document has"),
        ({"updated_after": "yesterday"}, "updated_after: an ISO 8601 date"),
    ],
)
def test_filters_are_refused_as_search_refuses_them(
    words: Library, filters: SearchFilters, message: str
) -> None:
    """The same refusal, word for word, for ask as for search."""
    with pytest.raises(UnanswerableError, match=message) as by_ask:
        words.ask("kafka", filters=filters)
    with pytest.raises(UnanswerableError) as by_search:
        words.search("kafka", filters=filters)
    assert str(by_ask.value) == str(by_search.value)


def test_filters_narrow_and_a_question_without_words_is_refused(words: Library) -> None:
    """The issue alone in its project; a question of marks alone has nothing to search."""
    found = passages(words.ask("brokers", filters={"project": "proj"}))
    assert [each["ref"] for each in found] == ["PROJ-7"]
    assert words.ask("?!") == "The question has no words to search: ask it in words."


def test_without_vectors_ask_answers_by_words_and_says_why(tmp_path: Path) -> None:
    """Hybrid asked of an index built without a model: by words, with the reason."""
    docs = tmp_path / "docs"
    fillers(docs)
    write(docs, page("196845", "Kafka"), RETENTION)
    build_index(docs, tmp_path / "index.sqlite", MOMENT)
    library = Library(tmp_path / "index.sqlite", docs, Meaning(connector()), "hybrid")
    answer = library.ask("kafka retention")
    assert "Ranked by words alone: the index holds no vectors" in parts(answer)[0]
    assert passages(answer)[0]["ref"] == "196845"


def by_meaning(
    root: Path, chunking: Chunking, body: str, title: str = "Holiday canteen"
) -> Library:
    """Serve a mirror whose page 4002 has ``body``, indexed by ``chunking``, by meaning."""
    docs = root / "docs"
    fillers(docs)
    write(docs, page("4002", title), body)
    embedding = Embedding(tiny(), root / "vectors.sqlite", chunking=chunking)
    build_index(docs, root / "index.sqlite", MOMENT, embedding)
    return Library(root / "index.sqlite", docs, Meaning(connector()), "semantic")


@pytest.mark.parametrize(
    ("chunking", "text"),
    [
        ("sections", "Leave for a meal.\n"),
        ("section-paths", "Leave for a meal.\n"),
        ("windows", HOLIDAY),
        ("small-to-big", HOLIDAY),
    ],
)
def test_by_meaning_each_chunking_quotes_its_unit(
    tmp_path: Path, chunking: Chunking, text: str
) -> None:
    """The piece itself; the window, here the whole body; small-to-big, its section whole."""
    library = by_meaning(tmp_path, chunking, HOLIDAY)
    (first, *_) = passages(library.ask("vacation lunch"))
    assert (first["ref"], first["section"], first["text"]) == ("4002", "1", text)


def test_small_to_big_quotes_2400_characters_of_a_long_section_about_its_piece(
    tmp_path: Path,
) -> None:
    """Of a section of 5,600 characters, 2,400 about the piece near the question.

    The title, embedded with each piece, is near nothing, so the piece alone decides.
    """
    filler = "lorem ipsum dolor sit amet\n\n" * 100
    near = "Leave for a meal.\n\n"
    body = f"# Office notes\n\n{filler}{near}{filler}"
    library = by_meaning(tmp_path, "small-to-big", body, "Office notes")
    (first, *_) = passages(library.ask("vacation lunch"))
    assert len(first["text"]) == UNIT
    assert near in first["text"]
    assert first["text"] in body
