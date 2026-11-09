"""The pure rules of reranking: the text a document is scored by, and an order in a cursor.

A search's next page must follow the order of its first without scoring again, so the
cursor that continues a reranked page carries that order, one character for each
document reranked: its place among the documents that the first ranking gave.
"""

from __future__ import annotations

import string

from kb_mcp.kernel.reranking import LONGEST_TEXT

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

    No cursor gives no order, ``None``: a first page, which reranks. A cursor without an
    order gives an empty one: a page continuing a first that was not reranked, and is
    not now. Raises ValueError for an order that is not one: a character not a place, or
    a place repeated or past the others.
    """
    if cursor is None:
        return None, None
    base, _, places = cursor.partition(".")
    order = tuple(PLACES.find(each) for each in places)
    if sorted(order) != list(range(len(order))):
        message = "an order of places that is not one"
        raise ValueError(message)
    return base, order
