"""The four chunkings of plan 019: their cuts, texts and units, by the plan's rules."""

from __future__ import annotations

import functools
import itertools
from typing import TYPE_CHECKING, get_args

import numpy as np
import pytest

from kb_mcp.kernel.chunking import CHUNKINGS, Chunking
from kb_mcp.search.domain.chunking import CHUNKERS, section_chunks
from kb_mcp.search.domain.search import sections
from tests.mirrors import page

if TYPE_CHECKING:
    from kb_mcp.search.domain.search import Section

SEED = 19
TEXTS = 3000
# The plan's figures, in characters at 4 a token.
WINDOW = 1200  # 300 tokens
STEP = 960  # 240 tokens
TENTH = 120
SMALL = 512  # 128 tokens
PASSAGE_CHARS = 2400
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
SPACES = ("\n", "\n\n", "  \n\t\n", " ", "\r\n", " " * 1500, "\n" * 1100)
LETTERS = list("abcdefghijklmnopqrstuvwxyzéàç0123456789-.,")
TITLE = "Payout rollback"
FRONT = page("196845", TITLE, breadcrumb=("Handbook", "Payments"))


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
    """The table holds the kernel's names, no more, the control first, each named once."""
    assert set(CHUNKERS) == set(CHUNKINGS)
    assert get_args(Chunking.__value__) == CHUNKINGS
    assert CHUNKINGS[0] == "sections"


@pytest.mark.parametrize("chunking", CHUNKINGS)
def test_a_chunk_s_range_is_in_the_body_and_its_section_holds_its_middle(
    chunking: Chunking,
) -> None:
    """Plan 054: positions in a body are offsets from its start, whatever the chunking.

    Over seeded bodies, the text embedded ends with the body's characters of the chunk's
    range, and the section that the chunk names holds the range's middle.
    """
    for body in bodies()[:300]:
        cut = sections(body)
        for index, start, end, text in CHUNKERS[chunking].cut(FRONT, cut):
            assert text.endswith(body[start:end].strip())
            assert bounds(cut[index])[0] <= (start + end) // 2 < bounds(cut[index])[1]


def test_sections_cuts_as_011_did_and_returns_the_chunk() -> None:
    """The control is 011's passages, unchanged; its unit is the chunk."""
    cut = sections(f"# {TITLE}\n\nFirst.\n\n## Second\n\nMore.\n")
    assert CHUNKERS["sections"].cut(FRONT, cut) == section_chunks(TITLE, cut)
    assert CHUNKERS["sections"].quoted((5, 9), (0, 40)) == (5, 9)


def test_a_window_stops_at_its_last_space_and_the_next_starts_960_after() -> None:
    """2,000 characters of five-letter words: spaces at 4, 9, ..., 1,199, then the rest."""
    body = "abcd " * 400
    cut = sections(body)
    spans = [(chunk[1], chunk[2]) for chunk in CHUNKERS["windows"].cut(FRONT, cut)]
    assert spans == [(0, 1199), (STEP, 2000)]


@pytest.mark.parametrize(
    ("body", "spans"),
    [
        # A white space just past 1,200 characters ends the window at its whole length.
        ("x" * 1150 + " " + "y" * 49 + " " + "z" * 100, [(0, WINDOW), (STEP, 1301)]),
        # Nothing but white space after a window: no other.
        ("x" * 1100 + " " * 200, [(0, WINDOW)]),
        # White space alone where the next would start, but less than it holds: no skip.
        ("abcd " * 180 + " " * 400 + "abcd " * 100, [(0, WINDOW), (STEP, 1800)]),
        # White space alone in all the next would hold: past it.
        ("a" + " " * 5000 + "b", [(0, WINDOW), (5001, 5002)]),
    ],
)
def test_a_window_ends_at_white_space_and_none_is_blank(
    body: str, spans: list[tuple[int, int]]
) -> None:
    """Hand-computed cases of the white space that ends windows and that they skip."""
    cut = sections(body)
    assert [(chunk[1], chunk[2]) for chunk in CHUNKERS["windows"].cut(FRONT, cut)] == spans


def test_a_word_longer_than_the_last_tenth_is_cut_at_the_window_s_length() -> None:
    """No white space to stop at: the window ends inside the word."""
    body = "x" * 1300
    cut = sections(body)
    spans = [(chunk[1], chunk[2]) for chunk in CHUNKERS["windows"].cut(FRONT, cut)]
    assert spans == [(0, WINDOW), (STEP, 1300)]


def test_a_window_is_embedded_with_the_title_and_belongs_to_the_section_of_its_middle() -> None:
    """A window across two sections: its range is in the body, its section its middle's."""
    body = "# One\n\n" + "alpha " * 30 + "\n## Two\n\n" + "beta " * 300
    cut = sections(body)
    windows = CHUNKERS["windows"].cut(FRONT, cut)
    index, start, end, text = windows[0]
    assert index == 1
    assert (start, end) == (0, WINDOW)
    assert text == f"{TITLE}\n{body[0:WINDOW].strip()}"
    assert CHUNKERS["windows"].quoted((0, WINDOW), bounds(cut[1])) == (0, WINDOW)


def test_windows_hold_at_most_1200_characters_and_overlap_as_the_plan_says() -> None:
    """Over seeded bodies: lengths, overlaps, coverage, cuts inside words, sections, texts."""
    for body in bodies():
        cut = sections(body)
        windows = CHUNKERS["windows"].cut(FRONT, cut)
        spans = [(chunk[1], chunk[2]) for chunk in windows]
        short_words = max((len(each) for each in body.split()), default=0) <= WORD
        assert not body[: spans[0][0] if spans else len(body)].strip()
        assert not body[spans[-1][1] if spans else 0 :].strip()
        for (start, end), (index, *_, text) in zip(spans, windows, strict=True):
            assert end - start <= WINDOW
            assert body[start:end].strip()
            assert bounds(cut[index])[0] <= (start + end) // 2 < bounds(cut[index])[1]
            assert text == "\n".join(line for line in (TITLE, body[start:end].strip()) if line)
        for (start, end), (following, _) in itertools.pairwise(spans):
            # Past white space alone, the next window starts at the next word.
            skips = not body[start + STEP : start + STEP + WINDOW - TENTH].strip()
            assert following == (len(body) - len(body[end:].lstrip()) if skips else start + STEP)
            overlaps = OVERLAP_WITH_SHORT_WORDS if short_words else OVERLAP
            assert skips or end - following in overlaps
            assert body[end].isspace() or run_around(body, end) > TENTH


def test_small_to_big_chunks_hold_512_characters_and_cover_each_section_s_body() -> None:
    """Over seeded bodies: chunks within their section, no character but white space left."""
    for body in bodies():
        cut = sections(body)
        found = CHUNKERS["small-to-big"].cut(FRONT, cut)
        for index, section in enumerate(cut):
            spans = [(start, end) for each, start, end, _ in found if each == index]
            inner = (edge for span in spans for edge in span)
            edges = [section.body_start, *inner, bounds(section)[1]]
            left = [body[start:end] for start, end in itertools.batched(edges, 2, strict=True)]
            assert all(0 < end - start <= SMALL for start, end in spans)
            assert edges == sorted(edges)
            assert not "".join(left).strip()


def test_a_unit_holds_its_chunk_and_is_its_section_when_that_fits() -> None:
    """Over seeded bodies: each small-to-big chunk's unit, at most 2,400 characters."""
    for body in bodies():
        cut = sections(body)
        for index, start, end, _ in CHUNKERS["small-to-big"].cut(FRONT, cut):
            chunk = (start, end)
            section = bounds(cut[index])
            first, last = CHUNKERS["small-to-big"].quoted(chunk, section)
            assert section[0] <= first <= chunk[0] < chunk[1] <= last <= section[1]
            assert last - first == min(PASSAGE_CHARS, section[1] - section[0])


@pytest.mark.parametrize(
    ("chunk", "section", "unit"),
    [
        ((100, 600), (0, PASSAGE_CHARS), (0, PASSAGE_CHARS)),
        ((2500, 3000), (0, 5000), (1550, 3950)),
        ((0, SMALL), (0, 5000), (0, PASSAGE_CHARS)),
        ((4600, 5000), (0, 5000), (2600, 5000)),
    ],
)
def test_a_unit_is_centred_on_its_chunk_within_its_section(
    chunk: tuple[int, int], section: tuple[int, int], unit: tuple[int, int]
) -> None:
    """2,400 characters about the chunk's middle, moved back inside the section."""
    assert CHUNKERS["small-to-big"].quoted(chunk, section) == unit


def test_section_paths_cuts_as_sections_does() -> None:
    """The same chunks as the control; only their texts differ."""
    for body in bodies()[:300]:
        cut = sections(body)
        control = [chunk[:3] for chunk in CHUNKERS["sections"].cut(FRONT, cut)]
        assert [chunk[:3] for chunk in CHUNKERS["section-paths"].cut(FRONT, cut)] == control


def test_a_heading_path_names_each_heading_a_section_sits_under() -> None:
    """Under # A, ## B, ### C, ## D: C's path is A > B > C, and D's A > D."""
    cut = sections("# A\n\na\n## B\n\nb\n### C\n\nc\n## D\n\nd\n")
    texts = [text for *_, text in CHUNKERS["section-paths"].cut(FRONT, cut)]
    place = "Handbook / Payments"
    assert texts == [
        f"{TITLE}\n{place}\nA\na",
        f"{TITLE}\n{place}\nA > B\nb",
        f"{TITLE}\n{place}\nA > B > C\nc",
        f"{TITLE}\n{place}\nA > D\nd",
    ]


def test_the_title_the_breadcrumb_and_the_path_are_each_cut() -> None:
    """Each line that says where a chunk sits holds 200 characters at most."""
    front = page("1", "T" * 250, breadcrumb=("B" * 150, "C" * 150))
    cut = sections(f"Intro.\n\n## {'H' * 250}\n\nMore.\n")
    texts = [text for *_, text in CHUNKERS["small-to-big"].cut(front, cut)]
    lines = ("T" * CONTEXT, f"{'B' * 150} / {'C' * (CONTEXT - 153)}")
    assert texts == ["\n".join((*lines, "Intro.")), "\n".join((*lines, "H" * CONTEXT, "More."))]


@pytest.mark.parametrize(
    ("title", "heading"),
    [
        ("[RFC] Q&A *plans*", "\\[RFC\\] Q&A \\*plans\\*"),
        (" Payout  rollback\t", "Payout rollback"),
    ],
)
def test_the_title_is_left_out_of_the_path_however_the_mirror_wrote_it(
    title: str, heading: str
) -> None:
    """The body's first heading, of level 1, is the title as pandoc writes it in Markdown."""
    cut = sections(f"# {heading}\n\nIntro.\n\n## Steps\n\nMore.\n")
    texts = [text for *_, text in CHUNKERS["section-paths"].cut(page("1", title), cut)]
    assert texts == [f"{title}\nIntro.", f"{title}\nSteps\nMore."]


@pytest.mark.parametrize(
    ("body", "texts"),
    [
        (f"## {TITLE}\n\nMore.\n", [f"{TITLE}\n{TITLE}\nMore."]),
        (f"Lead.\n\n# {TITLE}\n\nMore.\n", [f"{TITLE}\nLead.", f"{TITLE}\n{TITLE}\nMore."]),
    ],
)
def test_only_a_body_s_first_heading_of_level_1_is_taken_for_the_title(
    body: str, texts: list[str]
) -> None:
    """The title's words in a heading of another level, or after text, stay in the path."""
    cut = sections(body)
    assert [text for *_, text in CHUNKERS["section-paths"].cut(page("1", TITLE), cut)] == texts


def test_a_heading_that_is_the_title_is_left_out_of_the_path() -> None:
    """A body begins with its title as a heading, as the mirror writes it: not said twice."""
    cut = sections(f"# {TITLE}\n\nIntro.\n\n## Steps\n\nMore.\n")
    texts = [text for *_, text in CHUNKERS["section-paths"].cut(FRONT, cut)]
    place = "Handbook / Payments"
    assert texts == [f"{TITLE}\n{place}\nIntro.", f"{TITLE}\n{place}\nSteps\nMore."]
