"""Where the work log's documents go in the mirror.

The paths are those of ``docs/reference/data-layout.md``: each document's file is in the
mirror's folder of its type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.slug import slug
from kb_mcp.mirror.domain.mirror_layout import WORKLOG_FOLDERS

if TYPE_CHECKING:
    from pathlib import PurePosixPath

# The work log's types whose id names the file alone: a day's id is its date, and a
# meeting's holds its title's slug already.
NAMED_BY_ID = frozenset({"day", "meeting"})


def worklog_path(document_type: str, identifier: str, title: str) -> PurePosixPath:
    """Return where a document of the work log, of this type, id and title, is mirrored.

    An entry's or a transcript's file is its id and its title's slug; a day's or a
    meeting's, its id alone.
    """
    parts = (identifier,) if document_type in NAMED_BY_ID else (identifier, slug(title))
    name = "-".join(part for part in parts if part)
    return WORKLOG_FOLDERS[document_type] / f"{name}.md"
