"""Where the work log's documents go in the mirror.

The paths are those of ``docs/reference/data-layout.md``: each document's file is in its
source's folder of the mirror, in that of its type, the folders that the fetch's
``worklog_globs`` finds, so that its migration reads them too.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from kb_mcp.kernel.names import WORKLOG_TYPES
from kb_mcp.kernel.slug import slug

if TYPE_CHECKING:
    from collections.abc import Container


def worklog_path(source: str, document_type: str, identifier: str, title: str) -> PurePosixPath:
    """Return where a source's document of the work log, of this type, id and title, goes.

    In its source's folder of the mirror, that of its type. An entry's or a transcript's
    file is its id and its title's slug; a day's or a meeting's, its id alone.
    """
    named_by_id = WORKLOG_TYPES[document_type].named_by_id
    parts = (identifier,) if named_by_id else (identifier, slug(title))
    name = "-".join(part for part in parts if part)
    return PurePosixPath(source, WORKLOG_TYPES[document_type].plural, f"{name}.md")


def named_id(path: PurePosixPath, identifiers: Container[str]) -> str | None:
    """Return the id among ``identifiers`` that the name of the file at ``path`` carries.

    ``worklog_path`` names a file by its id, alone or before a dash and its title's slug:
    of the ids that so begin the name, the longest, so that ``e-<digest>-2-notes.md`` is
    ``e-<digest>-2``'s, not ``e-<digest>``'s; None when none does. A file of an id not
    among them, such as a document's gone, whose name begins with one and a dash, is
    given that one.
    """
    stem = path.stem
    ends = [index for index, character in enumerate(stem) if character == "-"]
    return next(
        (stem[:end] for end in [len(stem), *reversed(ends)] if stem[:end] in identifiers), None
    )
