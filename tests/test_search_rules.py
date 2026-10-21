"""Search's pure rules: query plans, identifiers, sections and the order of trees."""

from __future__ import annotations

from datetime import timedelta

import pytest

from atlassian_offline_mcp.domain.search import (
    EMBEDDED_TITLE,
    MAX_WORDS,
    Score,
    fuse,
    identifiers,
    passages,
    pieces,
    plan,
    quote,
    rank,
    sections,
    tree_key,
    tree_paths,
)
from tests.mirrors import MOMENT, issue, page

LIMIT = 26


def test_each_word_is_quoted_and_stop_words_go() -> None:
    """Function words of English and French are not searched; the others are quoted."""
    planned = plan("How do we rotate the Kafka credentials? Comment faire la rotation")
    assert planned.words == ("rotate", "kafka", "credentials", "faire", "rotation")
    assert planned.match == '"rotate" OR "kafka" OR "credentials" OR "faire" OR "rotation"'
    assert planned.expressions[:5] == tuple(f'"{word}"' for word in planned.words)


def test_a_query_of_stop_words_alone_is_searched_whole() -> None:
    """When nothing but stop words is left, they are searched rather than nothing."""
    assert plan("what is it").words == ("what", "is", "it")


def test_the_phrase_is_one_more_expression() -> None:
    """The query's words in order, stop words included, are scored as one phrase."""
    assert plan("rotate the key").expressions[-1] == '"rotate the key"'
    assert plan("kafka").expressions == ('"kafka"',)
    assert len(plan(" ".join(f"w{n}" for n in range(17))).expressions) == MAX_WORDS


@pytest.mark.parametrize(
    "query",
    ['"unclosed', "kafka*", "NEAR(a b)", "-minus", "(a OR", "title:x", "^start", "a AND NOT b"],
)
def test_no_operator_survives_the_plan(query: str) -> None:
    """Quotes, stars, NEAR, minus, brackets, columns and AND, OR, NOT become words."""
    for expression in plan(query).expressions:
        assert expression.startswith('"')
        assert expression.endswith('"')
        assert '"' not in expression[1:-1]


def test_words_beyond_the_limit_are_counted_not_searched() -> None:
    """The first MAX_WORDS distinct words are searched, and the rest are counted."""
    over = 3
    planned = plan(" ".join(f"word{n}" for n in range(MAX_WORDS + over)))
    assert planned.words == tuple(f"word{n}" for n in range(MAX_WORDS))
    assert planned.dropped == over


def test_a_quote_inside_a_string_is_doubled() -> None:
    """FTS5 reads a doubled quote as one quote inside a string."""
    assert quote('say "hi"') == '"say ""hi"""'


def test_keys_and_ids_are_found_in_text_and_addresses() -> None:
    """Keys in any case, numbers alone and the ids in page addresses are identifiers.

    The numbers of a key or a date are not page ids.
    """
    found = identifiers(
        "see proj-12 and PAY-7, page 196845 of 2026-10-20, "
        "https://x.atlassian.net/wiki/spaces/ENG/pages/229377/Some+page, "
        "https://x.atlassian.net/wiki/pages/viewpage.action?pageId=229999 "
        "https://x.atlassian.net/wiki/spaces/ENG/blog/2026/10/20/196900/News "
        "https://x.atlassian.net/browse/OPS-3?focusedCommentId=1"
    )
    assert found.keys == ("PROJ-12", "PAY-7", "OPS-3")
    assert found.ids == ("229377", "229999", "196900", "196845")


def test_a_key_that_breaks_the_rule_is_not_a_key() -> None:
    """A single-letter project or a key inside a longer word is not an issue key."""
    assert identifiers("a-1 xPROJ-1y PROJ-1-2").keys == ()


def test_sections_give_back_the_body_exactly() -> None:
    """Cut before each heading; joined again, the sections are the body."""
    body = "Lead.\n# Title\n\nText.\r\n## Part one ##\nMore.\n### C#\nEnd"
    cut = sections(body)
    assert [section.heading for section in cut] == ["", "Title", "Part one", "C#"]
    assert [section.number for section in cut] == [1, 2, 3, 4]
    assert "".join(section.text for section in cut) == body
    assert all(body[section.start :].startswith(section.text) for section in cut)


def test_a_section_is_its_heading_line_then_its_body() -> None:
    """The heading line is kept apart, so that its words are not counted as body too."""
    first, second = sections("# Title\nLead.\n## Part\nText.")
    assert (first.head, first.body) == ("# Title\n", "Lead.\n")
    assert (second.head, second.body) == ("## Part\n", "Text.")
    assert sections("Lead only.")[0].head == ""


def test_headings_inside_fenced_code_do_not_cut() -> None:
    """A # line in a code block is code; the block ends at its own kind of fence."""
    body = "# Title\n````sh\n# not a heading\n```\n# still code\n````\n## After\n~~~\n# code\n~~~\n"
    assert [section.heading for section in sections(body)] == ["Title", "After"]


@pytest.mark.parametrize("line", ["#hashtag", "    # indented code", "\\# escaped"])
def test_lines_that_are_not_headings_do_not_cut(line: str) -> None:
    """A # without a space, four spaces of indent or an escape is not a heading."""
    assert len(sections(f"# Title\n{line}\n")) == 1


def test_an_empty_body_is_one_empty_section() -> None:
    """Every document has at least one section to open."""
    assert [(section.start, section.text) for section in sections("")] == [(0, "")]


def test_trees_list_depth_first_with_numbers_in_order() -> None:
    """A parent comes before its children, which come before its next sibling."""
    paths = [
        ("Home", "b"),
        ("Home",),
        ("Home", "A", "child"),
        ("PROJ-10",),
        ("Home", "A"),
        ("PROJ-2",),
        ("PROJ-2", "PROJ-11"),
        ("Home", "A B"),
    ]
    assert sorted(paths, key=tree_key) == [
        ("Home",),
        ("Home", "A"),
        ("Home", "A", "child"),
        ("Home", "A B"),
        ("Home", "b"),
        ("PROJ-2",),
        ("PROJ-2", "PROJ-11"),
        ("PROJ-10",),
    ]


def test_jira_trees_follow_parents_and_confluence_trees_breadcrumbs() -> None:
    """A sub-task sits under its story under its epic; a missing parent stays a name."""
    fronts = [
        page("1", "Child", breadcrumb=("Home", "Folder")),
        issue("PROJ-3", "Sub-task", breadcrumb=("PROJ-12",)),
        issue("PROJ-12", "Story", breadcrumb=("PROJ-1",)),
        issue("PROJ-1", "Epic"),
        issue("PROJ-7", "Orphan", breadcrumb=("OTHER-1",)),
        issue("PROJ-8", "Loop", breadcrumb=("PROJ-9",)),
        issue("PROJ-9", "Loop", breadcrumb=("PROJ-8",)),
    ]
    assert tree_paths(fronts) == [
        ("Home", "Folder", "Child"),
        ("PROJ-1", "PROJ-12", "PROJ-3"),
        ("PROJ-1", "PROJ-12"),
        ("PROJ-1",),
        ("OTHER-1", "PROJ-7"),
        ("PROJ-9", "PROJ-8"),
        ("PROJ-8", "PROJ-9"),
    ]


def test_ranking_sums_each_expression_once_per_document() -> None:
    """Pinned documents come first; then the sum of relevance; ties to the newest."""
    newer = MOMENT + timedelta(days=1)
    by_word = [
        {"a.md": Score(1.0, MOMENT), "b.md": Score(3.0, MOMENT), "c.md": Score(1.5, newer)},
        {"a.md": Score(2.5, MOMENT), "d.md": Score(1.5, MOMENT)},
    ]
    assert rank(by_word, ["d.md", "x.md", "d.md"], by_update=False) == [
        "d.md",
        "x.md",
        "a.md",
        "b.md",
        "c.md",
    ]
    assert rank(by_word, [], by_update=True)[:1] == ["c.md"]


def test_pieces_end_at_the_last_blank_line_that_fits() -> None:
    """Paragraphs are packed while they fit; white space never starts a piece."""
    text = "\n\nfirst para\n\nsecond para\n\nthird paragraph here\n"
    spans = pieces(text, limit=LIMIT)
    assert [text[start:end].strip() for start, end in spans] == [
        "first para\n\nsecond para",
        "third paragraph here",
    ]
    assert all(end - start <= LIMIT and not text[start].isspace() for start, end in spans)


def test_a_long_paragraph_is_cut_at_a_line_break_then_a_space_then_anywhere() -> None:
    """Each piece fits the limit, and together they hold every word in order."""
    lines = "one two\nthree four"
    assert [lines[a:b] for a, b in pieces(lines, limit=12)] == ["one two", "three four"]
    words = "alpha beta gamma delta"
    assert [words[a:b] for a, b in pieces(words, limit=10)] == ["alpha beta", "gamma", "delta"]
    solid = "x" * 25
    assert [b - a for a, b in pieces(solid, limit=10)] == [10, 10, 5]


def test_a_blank_text_has_no_piece() -> None:
    """Nothing to embed in white space alone."""
    assert pieces("") == []
    assert pieces("  \n\n\t") == []


def test_fusion_favours_a_document_that_both_rankings_hold() -> None:
    """Fortieth in both beats first in one: 2 / 100 is more than 1 / 61 (not so for k=10)."""
    others = [f"x{n}" for n in range(78)]
    one, two = ["a", *others[:38], "both"], ["b", *others[38:76], "both"]
    updated = dict.fromkeys(["a", "b", "both", *others], MOMENT)
    assert fuse([one, two], updated)[0] == "both"


def test_fusion_ties_go_to_the_newest_then_the_path() -> None:
    """Equal shares: the document updated last comes first, then by path."""
    updated = {"a": MOMENT, "b": MOMENT + timedelta(days=1), "c": MOMENT}
    assert fuse([["a"], ["b"], ["c"]], updated) == ["b", "a", "c"]


def test_each_piece_is_embedded_with_its_title_and_heading() -> None:
    """The title, cut, then the heading unless it is the title, then the piece's text."""
    title = "T" * (EMBEDDED_TITLE + 50)
    cut = sections(f"# {title}\n\nFirst.\n\n## Second\n\nMore.\n\n## Empty\n")
    found = passages(title, cut)
    assert [(index, text) for index, _, _, text in found] == [
        (0, f"{'T' * EMBEDDED_TITLE}\nFirst."),
        (1, f"{'T' * EMBEDDED_TITLE}\nSecond\nMore."),
    ]
    index, start, end, _ = found[1]
    assert cut[index].body[start:end].strip() == "More."
