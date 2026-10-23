"""``ask``: passages to quote, verbatim, within one budget, by each chunking (plan 019).

Each expected passage is written out by hand from the plan's rules: by words, the
section that holds the question's words, cut after a line break within 2,400
characters; by meaning, the unit of the chunking.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from opentelemetry import trace

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
    from tests.conftest import InMemory

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
# A long section whose question's words are in its last line alone.
TAIL = (
    "# Rules\n\n## Crossings\n\n"
    + "a line of other matters here\n" * 140
    + "zebracrossing quota met\n"
)
FILLER = "a line of other matters here\n" * 140
LINE = "a line of other matters here\n"
# The question's rarest word twice: early, alone within 1,200 characters though the
# other word is 2,000 before it and 2,000 after; late, the other word 1,000 before it,
# 500 from the end.
SCORED = (
    "# Falcons\n\n## Log\n\nledger at the top\n"
    + LINE * 69
    + "falcon early\n"
    + LINE * 69
    + "ledger near the early one\n"
    + LINE * 207
    + "ledger in the middle\n"
    + LINE * 103
    + "ledger before the end\n"
    + LINE * 35
    + "falcon late\n"
    + LINE * 17
)
# Long sections whose question's words are found as the index finds them: capitalised,
# between underscores, with accents, and both words together late, one alone early.
FOUND = {
    "196849": ("Capitals", "Pelicancrossing Quorum reached\n", "pelicancrossing quorum"),
    "196850": ("Keys", "set max_poll_records to 500\n", "max poll records"),
    "196851": ("Accents", "le résumé du plan trimestriel\n", "resume"),
    "196852": ("Together", "the yakshaving tariff applies\n", "yakshaving tariff"),
}
# One short section, near "vacation lunch" by meaning.
HOLIDAY = "# Holiday canteen\n\nLeave for a meal.\n"
UNIT = 2400
ENOUGH = 40  # documents holding a word, more than one answer quotes
GAMMA = "gamma notes " * 40  # so that fewer than 20 of their passages fit one answer
ASK_DOCUMENTS = 20  # the documents that one answer quotes, at most


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
        (page("196848", "Rules"), TAIL),
        (page("196853", "Falcons"), SCORED),
        *(
            (
                page(ref, title),
                f"# {title}\n\n## Log\n\n"
                + ("tariff once\n" if ref == "196852" else "")
                + FILLER
                + tail,
            )
            for ref, (title, tail, _) in FOUND.items()
        ),
        *(
            (page(str(800000 + number), f"Delta {number}"), f"# Delta {number}\n\ndelta\n")
            for number in range(ENOUGH)
        ),
        *(
            (page(str(700000 + number), f"Gamma {number}"), f"# Gamma {number}\n\n{GAMMA}\n")
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


def test_a_long_section_is_quoted_about_the_question_s_words(words: Library) -> None:
    """The words in its last line: 2,400 characters of its end, from a line's start."""
    (first, *_) = passages(words.ask("zebracrossing quota"))
    section = TAIL[TAIL.index("## Crossings") :]
    end = section[-UNIT:]
    assert first["text"] == end[end.index("\n") + 1 :]
    assert first["text"].endswith("zebracrossing quota met\n")


@pytest.mark.parametrize("ref", sorted(FOUND))
def test_the_question_s_words_are_found_as_the_index_finds_them(words: Library, ref: str) -> None:
    """Whatever their case or accents, between underscores, both words where they meet."""
    _, tail, question = FOUND[ref]
    (first, *_) = passages(words.ask(question))
    assert first["ref"] == ref
    assert first["text"].endswith(tail)
    assert len(first["text"]) <= UNIT


def test_the_rarest_word_s_occurrence_with_most_words_about_it_is_the_centre(
    words: Library,
) -> None:
    """Of the rarest word's two, the late one, near the other word: the section's end.

    The passage is the section's last 2,400 characters, from a line's start.
    """
    (first, *_) = passages(words.ask("falcon ledger"))
    end = SCORED[SCORED.index("## Log") :][-UNIT:]
    assert first["text"] == end[end.index("\n") + 1 :]
    assert "ledger before the end" in first["text"]


def test_an_answer_quotes_20_documents_at_most_however_short(words: Library) -> None:
    """Forty documents of a line each: twenty, then the call that continues."""
    answer = words.ask("delta")
    assert len(passages(answer)) == ASK_DOCUMENTS
    assert continuation(answer) is not None


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


def test_what_eval_measures_is_what_ask_s_first_answer_quotes(words: Library) -> None:
    """The same documents and texts, those that fit the budget, fewer than 20 here."""
    shown = words.quoted("gamma notes", "lexical")
    quoted = passages(words.ask("gamma notes"))
    assert [each.path for each in shown] == [words.resolve(each["ref"]) for each in quoted]
    assert [each.text for each in shown] == [each["text"] for each in quoted]
    assert len(shown) < ASK_DOCUMENTS


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


def call_s_span(library: Library, question: str, telemetry: InMemory) -> dict[str, object]:
    """Ask within a span, as the SDK's around a call, and give what ask set on it."""
    with trace.get_tracer(__name__).start_as_current_span("tools/call ask"):
        library.ask(question)
    (span,) = (
        each for each in telemetry.spans.get_finished_spans() if each.name == "tools/call ask"
    )
    return {key: value for key, value in (span.attributes or {}).items() if key.startswith("aom.")}


def test_the_call_s_span_says_the_mode_the_documents_found_and_the_passages_quoted(
    words: Library, telemetry: InMemory
) -> None:
    """Forty documents found by words, fewer passages than twenty within the budget."""
    shown = len(passages(words.ask("gamma notes")))
    said = call_s_span(words, "gamma notes", telemetry)
    assert said == {
        "aom.mode": "lexical",
        "aom.hits": ENOUGH,
        "aom.fallback": False,
        "aom.passages": shown,
    }
    assert 0 < shown < ASK_DOCUMENTS


def test_the_call_s_span_says_that_words_stood_in_for_meaning(
    tmp_path: Path, telemetry: InMemory
) -> None:
    """Hybrid asked of an index built without a model."""
    docs = tmp_path / "docs"
    fillers(docs)
    write(docs, page("196845", "Kafka"), RETENTION)
    build_index(docs, tmp_path / "index.sqlite", MOMENT)
    library = Library(tmp_path / "index.sqlite", docs, Meaning(connector()), "hybrid")
    said = call_s_span(library, "kafka retention", telemetry)
    assert (said["aom.mode"], said["aom.fallback"]) == ("hybrid", True)


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
