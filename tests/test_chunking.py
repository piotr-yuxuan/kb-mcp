"""The four chunkings of plan 019: their cuts, texts and units, by the plan's rules."""

from __future__ import annotations

import functools
import itertools
from typing import TYPE_CHECKING

import numpy as np
import pytest

from atlassian_offline_mcp.kernel.chunking import CHUNKINGS
from atlassian_offline_mcp.search.domain.chunking import CHUNKERS, passages
from atlassian_offline_mcp.search.domain.search import sections
from tests.mirrors import page

if TYPE_CHECKING:
    from atlassian_offline_mcp.search.domain.search import Section

SEED = 19
TEXTS = 3000
# The plan's figures, in characters at 4 a token.
WINDOW = 1200  # 300 tokens
STEP = 960  # 240 tokens
TENTH = 120
SMALL = 512  # 128 tokens
UNIT = 2400
# Two windows in a row share OVERLAP characters, and when no word is longer than WORD,
# OVERLAP_WITH_SHORT_WORDS.
WORD = 40
OVERLAP = range(TENTH, WINDOW - STEP + 1)
OVERLAP_WITH_SHORT_WORDS = range(WINDOW - STEP - WORD, WINDOW - STEP + 1)
# Characters of the title, breadcrumb and heading path embedded, each at most.
CONTEXT = 200
# The random bodies: the chance of a word that may be long, of a heading, and of white
# space alone, for each part; the ends of a paragraph, and white space alone.
LONG_WORD = 0.05
HEADING = 0.2
SPACE = 0.3
ENDS = ("\n\n", "\n", " ")
SPACES = ("\n", "\n\n", "  \n\t\n", " ", "\r\n")
LETTERS = list("abcdefghijklmnopqrstuvwxyzéàç0123456789-.,")
TITLE = "Payout rollback"
FRONT = page("196845", TITLE, breadcrumb=("Handbook", "Payments"))


def absolute(cut: list[Section], index: int, start: int, end: int) -> tuple[int, int]:
    """Give a piece's span in the body, from its section's index and its span in that body."""
    offset = cut[index].start + len(cut[index].head)
    return offset + start, offset + end


def bounds(section: Section) -> tuple[int, int]:
    """Give a section's span in the body, its heading line included."""
    return section.start, section.start + len(section.text)


def words(rng: np.random.Generator, pool: str, count: int, longest: int) -> list[str]:
    """Give ``count`` words cut from ``pool``: of 1 to 8 characters, a few up to ``longest``."""
    lengths = rng.integers(1, 9, size=count)
    long = rng.random(count) < LONG_WORD
    lengths[long] = rng.integers(1, longest + 1, size=int(long.sum()))
    starts = rng.integers(0, len(pool) - longest, size=count)
    return [pool[start : start + length] for start, length in zip(starts, lengths, strict=True)]


@functools.cache
def bodies() -> tuple[str, ...]:
    """Give TEXTS Markdown bodies, seeded: headings, paragraphs and odd white space."""
    rng = np.random.default_rng(SEED)
    pool = "".join(rng.choice(LETTERS, size=100_000))
    found: list[str] = []
    for _ in range(TEXTS):
        longest = (WORD, WORD, 300)[rng.integers(3)]
        parts: list[str] = []
        for _ in range(rng.integers(0, 10)):
            roll = rng.random()
            if roll < HEADING:
                level = "#" * int(rng.integers(1, 7))
                parts.append(f"{level} {words(rng, pool, 1, 8)[0]}\n")
            elif roll < SPACE:
                parts.append(SPACES[rng.integers(len(SPACES))])
            else:
                paragraph = words(rng, pool, int(rng.integers(1, 300)), longest)
                parts.append(" ".join(paragraph) + ENDS[rng.integers(len(ENDS))])
        found.append("".join(parts))
    return tuple(found)


def run_around(body: str, at: int) -> int:
    """Give the length of the run of characters that are not white space holding ``at``."""
    start, end = at, at
    while start > 0 and not body[start - 1].isspace():
        start -= 1
    while end < len(body) and not body[end].isspace():
        end += 1
    return end - start


def test_every_chunking_named_has_its_cut_and_unit() -> None:
    """The table holds the kernel's names, no more, the control first."""
    assert set(CHUNKERS) == set(CHUNKINGS)
    assert CHUNKINGS[0] == "sections"


def test_sections_cuts_as_011_did_and_returns_the_piece() -> None:
    """The control is 011's passages, unchanged; its unit is the piece."""
    cut = sections(f"# {TITLE}\n\nFirst.\n\n## Second\n\nMore.\n")
    assert CHUNKERS["sections"].cut(FRONT, cut) == passages(TITLE, cut)
    assert CHUNKERS["sections"].unit((5, 9), (0, 40)) == (5, 9)


def test_a_window_stops_at_its_last_space_and_the_next_starts_960_after() -> None:
    """2,000 characters of five-letter words: spaces at 4, 9, ..., 1,199, then the rest."""
    body = "abcd " * 400
    cut = sections(body)
    spans = [absolute(cut, *piece[:3]) for piece in CHUNKERS["windows"].cut(FRONT, cut)]
    assert spans == [(0, 1199), (STEP, 2000)]


def test_a_word_longer_than_the_last_tenth_is_cut_at_the_window_s_length() -> None:
    """No white space to stop at: the window ends inside the word."""
    body = "x" * 1300
    cut = sections(body)
    spans = [absolute(cut, *piece[:3]) for piece in CHUNKERS["windows"].cut(FRONT, cut)]
    assert spans == [(0, WINDOW), (STEP, 1300)]


def test_a_window_is_embedded_with_the_title_and_belongs_to_the_section_of_its_middle() -> None:
    """A window across two sections: its span is relative to the body of its middle's."""
    body = "# One\n\n" + "alpha " * 30 + "\n## Two\n\n" + "beta " * 300
    cut = sections(body)
    windows = CHUNKERS["windows"].cut(FRONT, cut)
    index, start, end, text = windows[0]
    assert index == 1
    assert absolute(cut, index, start, end) == (0, WINDOW)
    assert start < 0
    assert text == f"{TITLE}\n{body[0:WINDOW].strip()}"
    assert CHUNKERS["windows"].unit((0, WINDOW), bounds(cut[1])) == (0, WINDOW)


def test_windows_hold_at_most_1200_characters_and_overlap_as_the_plan_says() -> None:
    """Over seeded bodies: lengths, overlaps, coverage, cuts inside words, sections, texts."""
    for body in bodies():
        cut = sections(body)
        windows = CHUNKERS["windows"].cut(FRONT, cut)
        spans = [absolute(cut, *piece[:3]) for piece in windows]
        short_words = max((len(each) for each in body.split()), default=0) <= WORD
        assert not body[: spans[0][0] if spans else len(body)].strip()
        assert not body[spans[-1][1] if spans else 0 :].strip()
        for (start, end), (index, *_, text) in zip(spans, windows, strict=True):
            assert end - start <= WINDOW
            assert bounds(cut[index])[0] <= (start + end) // 2 < bounds(cut[index])[1]
            assert text == "\n".join(line for line in (TITLE, body[start:end].strip()) if line)
        for (start, end), (following, _) in itertools.pairwise(spans):
            assert following == start + STEP
            assert end - following in (OVERLAP_WITH_SHORT_WORDS if short_words else OVERLAP)
            assert body[end].isspace() or run_around(body, end) > TENTH


def test_small_to_big_pieces_hold_512_characters_and_cover_each_section_s_body() -> None:
    """Over seeded bodies: pieces within their section, no character but white space left."""
    for body in bodies():
        cut = sections(body)
        found = CHUNKERS["small-to-big"].cut(FRONT, cut)
        for index, section in enumerate(cut):
            spans = [(start, end) for each, start, end, _ in found if each == index]
            edges = [0, *(edge for span in spans for edge in span), len(section.body)]
            left = [
                section.body[start:end] for start, end in itertools.batched(edges, 2, strict=True)
            ]
            assert all(0 < end - start <= SMALL for start, end in spans)
            assert edges == sorted(edges)
            assert not "".join(left).strip()


def test_a_unit_holds_its_piece_and_is_its_section_when_that_fits() -> None:
    """Over seeded bodies: each small-to-big piece's unit, at most 2,400 characters."""
    for body in bodies():
        cut = sections(body)
        for index, start, end, _ in CHUNKERS["small-to-big"].cut(FRONT, cut):
            piece = absolute(cut, index, start, end)
            section = bounds(cut[index])
            first, last = CHUNKERS["small-to-big"].unit(piece, section)
            assert section[0] <= first <= piece[0] < piece[1] <= last <= section[1]
            assert last - first == min(UNIT, section[1] - section[0])


@pytest.mark.parametrize(
    ("piece", "section", "unit"),
    [
        ((100, 600), (0, UNIT), (0, UNIT)),
        ((2500, 3000), (0, 5000), (1550, 3950)),
        ((0, SMALL), (0, 5000), (0, UNIT)),
        ((4600, 5000), (0, 5000), (2600, 5000)),
    ],
)
def test_a_unit_is_centred_on_its_piece_within_its_section(
    piece: tuple[int, int], section: tuple[int, int], unit: tuple[int, int]
) -> None:
    """2,400 characters about the piece's middle, moved back inside the section."""
    assert CHUNKERS["small-to-big"].unit(piece, section) == unit


def test_section_paths_cuts_as_sections_does() -> None:
    """The same pieces as the control; only their texts differ."""
    for body in bodies()[:300]:
        cut = sections(body)
        control = [piece[:3] for piece in CHUNKERS["sections"].cut(FRONT, cut)]
        assert [piece[:3] for piece in CHUNKERS["section-paths"].cut(FRONT, cut)] == control


def test_a_heading_path_names_each_heading_a_section_sits_under() -> None:
    """Under # A, ## B, ### C, ## D: C's path is A > B > C, and D's A > D."""
    cut = sections("Lead.\n# A\n\na\n## B\n\nb\n### C\n\nc\n## D\n\nd\n")
    texts = [text for *_, text in CHUNKERS["section-paths"].cut(FRONT, cut)]
    place = "Handbook / Payments"
    assert texts == [
        f"{TITLE}\n{place}\nLead.",
        f"{TITLE}\n{place}\nA\na",
        f"{TITLE}\n{place}\nA > B\nb",
        f"{TITLE}\n{place}\nA > B > C\nc",
        f"{TITLE}\n{place}\nA > D\nd",
    ]


def test_the_title_the_breadcrumb_and_the_path_are_each_cut() -> None:
    """Each line that says where a piece sits holds 200 characters at most."""
    front = page("1", "T" * 250, breadcrumb=("B" * 150, "C" * 150))
    cut = sections(f"Intro.\n\n## {'H' * 250}\n\nMore.\n")
    texts = [text for *_, text in CHUNKERS["small-to-big"].cut(front, cut)]
    lines = ("T" * CONTEXT, f"{'B' * 150} / {'C' * (CONTEXT - 153)}")
    assert texts == ["\n".join((*lines, "Intro.")), "\n".join((*lines, "H" * CONTEXT, "More."))]


def test_a_heading_that_is_the_title_is_left_out_of_the_path() -> None:
    """A body begins with its title as a heading, as the mirror writes it: not said twice."""
    cut = sections(f"# {TITLE}\n\nIntro.\n\n## Steps\n\nMore.\n")
    texts = [text for *_, text in CHUNKERS["section-paths"].cut(FRONT, cut)]
    place = "Handbook / Payments"
    assert texts == [f"{TITLE}\n{place}\nIntro.", f"{TITLE}\n{place}\nSteps\nMore."]
