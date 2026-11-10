"""How a document is cut into the chunks that vectors stand for, by each chunking.

``CHUNKERS`` gives each chunking of ``kernel.chunking`` by its name: what it cuts a
document into, as the index keeps each chunk, and the range that ``ask`` returns for a
chunk found. A chunk belongs to the section that holds its middle, and its range is in
the document's body, so that a window may cross sections. ``sections``, 011's, is the
control. Nothing here reads a file or
the index.
"""

from __future__ import annotations

import bisect
import functools
import re
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from kb_mcp.kernel.chunking import CHARACTERS_PER_TOKEN
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.domain.mirror import FrontMatter
from kb_mcp.search.domain.search import HEADING, Section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kb_mcp.kernel.chunking import Chunking

# Each chunk of a document: the index in its sections of the one holding its middle, its
# range in the body, and the text embedded.
type Cut = list[tuple[int, int, int, str]]
# The characters of a chunk of a section that one vector stands for, at most: under the
# 512 tokens of the smaller models' window, with the title, in English and French.
CHUNK = 1200
BLANK_LINE = re.compile(r"\n[ \t]*\n")
NOT_SPACE = re.compile(r"\S")
# A backslash escape of Markdown, before any ASCII punctuation.
ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
# Characters of a document's title that each embedded chunk begins with.
EMBEDDED_TITLE = 200
# Characters of the breadcrumb, and of the heading path, that a chunk is embedded with.
EMBEDDED_PATH = 200
# A window: its length, how far each starts after the last one's start, and the end of
# it where it may stop at a white space instead.
WINDOW = 300 * CHARACTERS_PER_TOKEN
STEP = 240 * CHARACTERS_PER_TOKEN
TENTH = WINDOW // 10
WHITE_SPACE = re.compile(r"\s")
# A chunk of small-to-big, at most, and the unit returned for it, at most.
SMALL = 128 * CHARACTERS_PER_TOKEN
PASSAGE_CHARS = 2400


def chunks(text: str, limit: int = CHUNK) -> list[tuple[int, int]]:
    """Cut a section's text into chunks of at most ``limit`` characters, as ranges.

    A chunk ends at the last blank line that fits; a paragraph longer than the limit is
    cut at its last line break that fits, else its last space, else at the limit. A
    chunk starts at its first character that is not white space, so none is blank.
    """
    breaks = [found.end() for found in BLANK_LINE.finditer(text)]
    ranges: list[tuple[int, int]] = []
    start = 0
    while found := NOT_SPACE.search(text, start):
        start = found.start()
        end = min(start + limit, len(text))
        if end < len(text):
            # The last blank line that fits, found by halves: a long section stays linear.
            at = bisect.bisect_right(breaks, end) - 1
            fitting = breaks[at] if at >= 0 else 0
            # A line break or space just past the limit ends a chunk that fits it exactly.
            line, space = (text.rfind(each, start + 1, end + 1) for each in ("\n", " "))
            cuts = (fitting, line, space) if fitting > start else (line, space)
            end = next((cut for cut in cuts if cut > start), end)
        ranges.append((start, end))
        start = end
    return ranges


def section_chunks(title: str, cut: Sequence[Section]) -> list[tuple[int, int, int, str]]:
    """Give the text to embed for each chunk of a document's sections.

    Each is the section's index in ``cut``, the chunk's range in the body, and the text:
    the title (cut to EMBEDDED_TITLE characters), the section's heading when it is not
    the title, and the chunk, one per line. A section without a body has no chunk.
    """
    found: list[tuple[int, int, int, str]] = []
    for index, section in enumerate(cut):
        heading = section.heading if section.heading != title else ""
        offset = section.body_start
        found += [
            (index, offset + start, offset + end, "\n".join(line for line in lines if line))
            for start, end in chunks(section.body)
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
        lines = (front.title[:EMBEDDED_TITLE], body[start:end].strip())
        text = "\n".join(line for line in lines if line)
        found.append((index, start, end, text))
        following = NOT_SPACE.search(body, end)
        if following is None:
            break
        held = NOT_SPACE.search(body, start + STEP, start + STEP + WINDOW - TENTH)
        start = start + STEP if held else following.start()
    return found


def section_paths(front: FrontMatter, cut: Sequence[Section], limit: int = CHUNK) -> Cut:
    """Give each chunk of a document's sections, embedded with where the chunk sits.

    Chunks are cut as ``chunks`` cuts them, of at most ``limit`` characters. The text is
    the title, the breadcrumb joined by " / ", the section's heading path, each cut to
    EMBEDDED_TITLE or EMBEDDED_PATH characters, and the chunk, one per line; an empty
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
        offset = section.body_start
        found += [
            (index, offset + start, offset + end, "\n".join(line for line in lines if line))
            for start, end in chunks(section.body, limit)
            for lines in [(*context, section.body[start:end].strip())]
        ]
    return found


def around(
    chunk: tuple[int, int], section: tuple[int, int], size: int = PASSAGE_CHARS
) -> tuple[int, int]:
    """Give a chunk's section whole when it fits ``size`` characters, else ``size`` about it.

    The ``size`` characters are centred on the chunk's middle, then moved to stay within
    the section. Every range, given or returned, is in the document's body.
    """
    first, last = section
    start = max(first, min((chunk[0] + chunk[1]) // 2 - size // 2, last - size))
    return section if last - first <= size else (start, start + size)


class Chunker(Record):
    """A chunking: the chunks it cuts a document into, and the unit returned for one."""

    cut: Callable[[FrontMatter, Sequence[Section]], Cut]
    # From a chunk's range and that of the section holding it, both in the body, the range
    # that ``ask`` returns.
    quoted: Callable[[tuple[int, int], tuple[int, int]], tuple[int, int]]


CHUNKERS: Mapping[Chunking, Chunker] = {
    "sections": Chunker(
        cut=lambda front, cut: section_chunks(front.title, cut), quoted=lambda chunk, _: chunk
    ),
    "windows": Chunker(cut=windows, quoted=lambda chunk, _: chunk),
    "section-paths": Chunker(cut=section_paths, quoted=lambda chunk, _: chunk),
    "small-to-big": Chunker(cut=functools.partial(section_paths, limit=SMALL), quoted=around),
}
