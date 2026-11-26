"""The pure rules of reranking: the text a document is scored by, and an order in a cursor.

A cursor carries a reranked page's order, one character a document, so that its next
pages are not scored again.
"""

from __future__ import annotations

import string

from kb_mcp.kernel.names import LONGEST_TEXT

# The text that a document is scored by: its title and the heading of its section, each
# cut to these, a line each, then this much of the section about its best place.
TITLE_CHARS = 150
HEADING_CHARS = 150
BODY_CHARS = LONGEST_TEXT - TITLE_CHARS - HEADING_CHARS - 2
# Base64url's alphabet: one character for each place, as many as MOST_TEXTS.
PLACES = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"


def written(order: tuple[int, ...]) -> str:
    """Write an order as a cursor ends with it: a dot, then each place; nothing for none."""
    return "." + "".join(PLACES[place] for place in order) if order else ""


def split_order(cursor: str | None) -> tuple[str | None, tuple[int, ...] | None]:
    """Part a cursor into what every cursor holds, offset and build, and the order it carries.

    No cursor gives None, for a first page, which reranks; a cursor without an order, an
    empty one, as its first page was not reranked. Raises ValueError for an order that is
    not one: a character not a place, or a place repeated or past the others.
    """
    if cursor is None:
        return None, None
    base, _, places = cursor.partition(".")
    order = tuple(PLACES.find(each) for each in places)
    if sorted(order) != list(range(len(order))):
        message = "an order of places that is not one"
        raise ValueError(message)
    return base, order
