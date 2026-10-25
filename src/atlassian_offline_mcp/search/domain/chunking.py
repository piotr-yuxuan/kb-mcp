"""How a document is cut into the pieces that vectors stand for, by each chunking.

``CHUNKERS`` gives each chunking of ``kernel.chunking`` by its name: what it cuts a
document into, as the index keeps each piece, and the span that ``ask`` returns for a
piece found. A piece belongs to the section that holds its middle, and its span is
relative to that section's body (its heading line aside): a window that crosses sections
needs no other schema. ``sections``, 011's, is the control. Nothing here reads a file or
the index.
"""

from __future__ import annotations

import bisect
import functools
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.chunking import CHARACTERS_PER_TOKEN
from atlassian_offline_mcp.search.domain.search import HEADING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from atlassian_offline_mcp.kernel.chunking import Chunking
    from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter
    from atlassian_offline_mcp.search.domain.search import Section

    # Each piece of a document: the index in its sections of the one holding its middle,
    # its span relative to that section's body, and the text embedded.
    type Cut = list[tuple[int, int, int, str]]

# The characters of a piece of a section that one vector stands for, at most: under the
# 512 tokens of the smaller models' window, with the title, in English and French.
PIECE = 1200
BLANK_LINE = re.compile(r"\n[ \t]*\n")
NOT_SPACE = re.compile(r"\S")
# A backslash escape of Markdown, before any ASCII punctuation.
ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
# Characters of a document's title that each embedded piece begins with.
EMBEDDED_TITLE = 200
# Characters of the breadcrumb, and of the heading path, that a piece is embedded with.
EMBEDDED_PATH = 200
# A window: its length, how far each starts after the last one's start, and the end of
# it where it may stop at a white space instead.
WINDOW = 300 * CHARACTERS_PER_TOKEN
STEP = 240 * CHARACTERS_PER_TOKEN
TENTH = WINDOW // 10
WHITE_SPACE = re.compile(r"\s")
# A piece of small-to-big, at most, and the unit returned for it, at most.
SMALL = 128 * CHARACTERS_PER_TOKEN
UNIT = 2400


def pieces(text: str, limit: int = PIECE) -> list[tuple[int, int]]:
    """Cut a section's text into pieces of at most ``limit`` characters, as spans.

    A piece ends at the last blank line that fits; a paragraph longer than the limit is
    cut at its last line break that fits, else its last space, else at the limit. A
    piece starts at its first character that is not white space, so none is blank.
    """
    breaks = [found.end() for found in BLANK_LINE.finditer(text)]
    spans: list[tuple[int, int]] = []
    start = 0
    while found := NOT_SPACE.search(text, start):
        start = found.start()
        end = min(start + limit, len(text))
        if end < len(text):
            # The last blank line that fits, found by halves: a long section stays linear.
            at = bisect.bisect_right(breaks, end) - 1
            fitting = breaks[at] if at >= 0 else 0
            # A line break or space just past the limit ends a piece that fits it exactly.
            line, space = (text.rfind(each, start + 1, end + 1) for each in ("\n", " "))
            cuts = (fitting, line, space) if fitting > start else (line, space)
            end = next((cut for cut in cuts if cut > start), end)
        spans.append((start, end))
        start = end
    return spans


def passages(title: str, cut: Sequence[Section]) -> list[tuple[int, int, int, str]]:
    """Give the text to embed for each piece of a document's sections.

    Each is the section's index in ``cut``, the piece's span in the section's body (its
    heading line aside), and the text: the title (cut to EMBEDDED_TITLE characters), the
    section's heading when it is not the title, and the piece, one per line. A section
    without a body has no piece.
    """
    found: list[tuple[int, int, int, str]] = []
    for index, section in enumerate(cut):
        heading = section.heading if section.heading != title else ""
        found += [
            (index, start, end, "\n".join(line for line in lines if line))
            for start, end in pieces(section.body)
            for lines in [(title[:EMBEDDED_TITLE], heading, section.body[start:end].strip())]
        ]
    return found


def windows(front: FrontMatter, cut: Sequence[Section]) -> Cut:
    """Cut a document's whole body into windows, each embedded with the title.

    A window holds WINDOW characters and starts STEP after the last one's start, so that
    two in a row overlap; when the WINDOW - TENTH characters from there, which a window
    holds at least, are white space alone, it starts instead at the first character after
    the last one's end that is not. One that does not reach the body's end stops instead
    at its last white space within its last TENTH or just past it, when it has one there.
    The first starts at the body's first character that is not white space, the last
    leaves only white space after it, and none is blank.
    """
    body = "".join(section.text for section in cut)
    starts = [section.start for section in cut]
    found: Cut = []
    first = NOT_SPACE.search(body)
    start = first.start() if first else len(body)
    while start < len(body):
        end = min(start + WINDOW, len(body))
        if end < len(body):
            # A white space just past the window ends it at its whole length.
            spaces = WHITE_SPACE.finditer(body, start + WINDOW - TENTH, end + 1)
            end = max((space.start() for space in spaces), default=end)
        index = bisect.bisect_right(starts, (start + end) // 2) - 1
        offset = cut[index].start + len(cut[index].head)
        lines = (front.title[:EMBEDDED_TITLE], body[start:end].strip())
        text = "\n".join(line for line in lines if line)
        found.append((index, start - offset, end - offset, text))
        following = NOT_SPACE.search(body, end)
        if following is None:
            break
        held = NOT_SPACE.search(body, start + STEP, start + STEP + WINDOW - TENTH)
        start = start + STEP if held else following.start()
    return found


def section_paths(front: FrontMatter, cut: Sequence[Section], limit: int = PIECE) -> Cut:
    """Give each piece of a document's sections, embedded with where the piece sits.

    Pieces are cut as ``pieces`` cuts them, of at most ``limit`` characters. The text is
    the title, the breadcrumb joined by " / ", the section's heading path, each cut to
    EMBEDDED_TITLE or EMBEDDED_PATH characters, and the piece, one per line; an empty
    line is left out. A section's heading path joins by " > " its heading and those it
    sits under: the nearest heading before it with fewer #, that one's own, and so on.
    The title, which the mirror writes first as a heading of level 1, escaped as
    Markdown, is left out of every path, since it is said first: a body's first heading
    of level 1, when it reads as the title once its escapes are undone and its white
    space collapsed.
    """
    place = " / ".join(front.breadcrumb)[:EMBEDDED_PATH]
    title = " ".join(front.title.split())
    above: list[tuple[int, str]] = []  # the headings that the next one may sit under
    found: Cut = []
    for index, section in enumerate(cut):
        heading = HEADING.fullmatch(section.head.removesuffix("\n").removesuffix("\r"))
        level = len(heading[1]) if heading else 0
        while above and above[-1][0] >= level:
            above.pop()
        first = section.start == 0 and level == 1
        said = first and " ".join(ESCAPE.sub(r"\1", section.heading).split()) == title
        above.append((level, "" if said else section.heading))
        path = " > ".join(words for _, words in above if words)
        context = (front.title[:EMBEDDED_TITLE], place, path[:EMBEDDED_PATH])
        found += [
            (index, start, end, "\n".join(line for line in lines if line))
            for start, end in pieces(section.body, limit)
            for lines in [(*context, section.body[start:end].strip())]
        ]
    return found


def around(piece: tuple[int, int], section: tuple[int, int], size: int = UNIT) -> tuple[int, int]:
    """Give a piece's section whole when it fits ``size`` characters, else ``size`` about it.

    The ``size`` characters are centred on the piece's middle, then moved to stay within
    the section. Every span, given or returned, is in the document's body.
    """
    first, last = section
    start = max(first, min((piece[0] + piece[1]) // 2 - size // 2, last - size))
    return section if last - first <= size else (start, start + size)


@dataclass(frozen=True)
class Chunker:
    """A chunking: the pieces it cuts a document into, and the unit returned for one."""

    cut: Callable[[FrontMatter, Sequence[Section]], Cut]
    # From a piece's span and that of the section holding it, both in the body, the span
    # that ``ask`` returns.
    unit: Callable[[tuple[int, int], tuple[int, int]], tuple[int, int]]


CHUNKERS: Mapping[Chunking, Chunker] = {
    "sections": Chunker(lambda front, cut: passages(front.title, cut), lambda piece, _: piece),
    "windows": Chunker(windows, lambda piece, _: piece),
    "section-paths": Chunker(section_paths, lambda piece, _: piece),
    "small-to-big": Chunker(functools.partial(section_paths, limit=SMALL), around),
}
