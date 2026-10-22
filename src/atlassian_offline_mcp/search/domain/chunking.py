"""How a document's sections are cut into the pieces that vectors stand for.

Each piece is a span of a section's body, embedded with the document's title and the
section's heading. Nothing here reads a file or the index.
"""

from __future__ import annotations

import bisect
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from atlassian_offline_mcp.search.domain.search import Section

# The characters of a piece of a section that one vector stands for, at most: under the
# 512 tokens of the smaller models' window, with the title, in English and French.
PIECE = 1200
BLANK_LINE = re.compile(r"\n[ \t]*\n")
NOT_SPACE = re.compile(r"\S")
# Characters of a document's title that each embedded piece begins with.
EMBEDDED_TITLE = 200


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
