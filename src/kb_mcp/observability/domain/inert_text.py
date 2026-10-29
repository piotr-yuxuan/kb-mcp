"""Text from the site or the mirror made inert on a terminal, before it is shown there.

What this leaves may still read as Rich's markup, such as ``[red]``: the display draws
it as Rich's ``Text``, never as markup.
"""

from __future__ import annotations

import re

# Unicode's bidirectional controls (Bidi_Control in PropList.txt): the marks ALM, LRM
# and RLM, the embeddings and overrides LRE to RLO, and the isolates LRI to PDI, which
# reorder what a terminal shows after them.
BIDI_CONTROLS = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
# The controls, C0, DEL and C1, that a terminal may obey rather than show, as escape
# sequences, bells and backspaces; those that are white space become a space instead.
CONTROLS = [code for code in (*range(0x20), *range(0x7F, 0xA0)) if not chr(code).isspace()]
REMOVED = dict.fromkeys([*CONTROLS, *map(ord, BIDI_CONTROLS)])
SPACES = re.compile(r"\s+")


def printable(text: str, *, width: int) -> str:
    """Show a text on one line of ``width`` characters at most, its controls taken out.

    Controls and bidirectional controls go; runs of white space, line breaks and tabs
    included, become one space, and none is left at either end. A longer text is cut,
    an ellipsis its last character, so ``width`` is 1 at least.
    """
    flat = SPACES.sub(" ", text.translate(REMOVED)).strip()
    return flat if len(flat) <= width else flat[: width - 1] + "…"
