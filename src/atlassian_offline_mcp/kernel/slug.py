"""The slug of a title, as the mirror's file names hold it, named once for every context.

Standard library only.
"""

from __future__ import annotations

import re
import unicodedata

SLUG_LENGTH = 60
NOT_SLUG = re.compile(r"[^a-z0-9]+")


def slug(title: str) -> str:
    """Name a title in a path: ASCII letters and digits, other runs as one ``-``.

    The title is decomposed (NFKD) and lowered, and its combining marks dropped, so that
    an accented letter keeps its base letter. It is cut at 60 characters, without a
    ``-`` at either end; it may be empty.
    """
    decomposed = unicodedata.normalize("NFKD", title).lower()
    kept = "".join(char for char in decomposed if not unicodedata.combining(char))
    return NOT_SLUG.sub("-", kept).strip("-")[:SLUG_LENGTH].rstrip("-")
