"""The concepts page holds no more entries than its ceiling, which stays within the budget.

An entry is a level-three heading under *Core concepts* or *Context vocabulary* of
``docs/reference/concepts.md``. ``ENTRIES`` gives the ceiling and the target, the
budget's most; a plan raises the ceiling only by declaring the new concept in its
*Concepts*, approved by the user.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from markdown_it import MarkdownIt

# The ceiling of the page's entries, then the target.
ENTRIES = (28, 35)
PAGE = Path(__file__).parents[1] / "docs" / "reference" / "concepts.md"
# The sections whose level-three headings are entries.
SECTIONS = frozenset({"Core concepts", "Context vocabulary"})


def entries(text: str) -> int:
    """Count the entries of a concepts page, read as GitHub renders it."""
    section, count = None, 0
    # Each inline token, the text of a heading, follows the token that opens it.
    for before, block in itertools.pairwise(MarkdownIt("commonmark").parse(text)):
        if before.type == "heading_open" and before.tag == "h2":
            section = block.content
        elif before.type == "heading_open" and before.tag == "h3" and section in SECTIONS:
            count += 1
    return count


def test_entries_are_counted_under_both_sections() -> None:
    """A level-three heading under either section counts; no other heading, nor code."""
    page = (
        "# Concepts\n\n### before\n\n## Core concepts\n\n### connector\n\n#### deeper\n\n"
        "```markdown\n### in code\n```\n\n### source\n\n## Context vocabulary\n\n"
        "### account\n\n## Elsewhere\n\n### other\n"
    )
    assert entries(page) == len(["connector", "source", "account"])


def test_the_concepts_stay_within_their_ceiling() -> None:
    """The page's entries are at most the ceiling, itself at most the target."""
    ceiling, target = ENTRIES
    assert entries(PAGE.read_text("utf-8")) <= ceiling <= target
