"""The Markdown mirror's layout: where each file goes, and how a document is laid out.

The paths and rules are those of ``docs/reference/data-layout.md``. A document is laid
out here as plain HTML, which pandoc then writes as Markdown, so that every text the
site gave is escaped by one writer.
"""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath

# The work log's folders, by the type of their documents.
WORKLOG_FOLDERS = {
    "entry": PurePosixPath("worklog/entries"),
    "day": PurePosixPath("worklog/days"),
    "meeting": PurePosixPath("worklog/meetings"),
    "transcript": PurePosixPath("worklog/transcripts"),
}
# Characters that show nothing, reorder what is shown, or cannot be written, apart from
# tab and line feed: controls, format characters (zero-width, bidirectional controls,
# tags), lone surrogates, private use and unassigned code points.
INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
KEPT_CONTROLS = frozenset("\t\n")
# Line and paragraph separators, which Markdown does not know as line breaks.
SEPARATORS = frozenset({"Zl", "Zp"})
# The variation selectors supplement, which no visible text needs.
VARIATION_SUPPLEMENT = range(0xE0100, 0xE01F0)


def visible(text: str) -> str:
    """Remove the characters that show nothing, reorder what is shown, or cannot be written.

    A line or paragraph separator (U+2028, U+2029) becomes a space.
    """
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char in KEPT_CONTROLS or (
            category not in INVISIBLE_CATEGORIES and ord(char) not in VARIATION_SUPPLEMENT
        ):
            kept.append(" " if category in SEPARATORS else char)
    return "".join(kept)


def one_line(text: str) -> str:
    """Make a text one visible line: line breaks of any kind become spaces."""
    return visible(" ".join(text.splitlines()))
