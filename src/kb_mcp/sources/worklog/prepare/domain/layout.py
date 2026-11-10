"""Where the work log's documents go in the mirror.

The paths are those of ``docs/reference/data-layout.md``: each document's file is in its
source's folder of the mirror, in that of its type.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from kb_mcp.kernel.names import WORKLOG_TYPES
from kb_mcp.kernel.slug import slug


def worklog_globs(source: str) -> tuple[str, ...]:
    """Give where a work log source's documents lie, relative to <data>/docs: its folders."""
    return tuple(f"{source}/{each.plural}/*.md" for each in WORKLOG_TYPES.values())


def worklog_path(source: str, document_type: str, identifier: str, title: str) -> PurePosixPath:
    """Return where a source's document of the work log, of this type, id and title, goes.

    In its source's folder of the mirror, that of its type. An entry's or a transcript's
    file is its id and its title's slug; a day's or a meeting's, its id alone.
    """
    named_by_id = WORKLOG_TYPES[document_type].named_by_id
    parts = (identifier,) if named_by_id else (identifier, slug(title))
    name = "-".join(part for part in parts if part)
    return PurePosixPath(source, WORKLOG_TYPES[document_type].plural, f"{name}.md")
