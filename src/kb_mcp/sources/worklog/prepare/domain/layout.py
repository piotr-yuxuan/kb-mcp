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
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet

    from kb_mcp.sources.worklog.fetch.domain.copies import Copies


def worklog_path(source: str, document_type: str, identifier: str, title: str) -> PurePosixPath:
    """Return where a source's document of the work log, of this type, id and title, goes.

    In its source's folder of the mirror, that of its type. An entry's or a transcript's
    file is its id and its title's slug; a day's or a meeting's, its id alone.
    """
    named_by_id = WORKLOG_TYPES[document_type].named_by_id
    parts = (identifier,) if named_by_id else (identifier, slug(title))
    name = "-".join(part for part in parts if part)
    return PurePosixPath(source, WORKLOG_TYPES[document_type].plural, f"{name}.md")


def places(copies: Copies, source: str) -> dict[PurePosixPath, str]:
    """Give, by its path, the id of each document of a source's ``copies`` that has a file.

    Each document of the store, where ``worklog_path`` places it, whether a run writes it
    or not; each carried over, where the migration found its file.
    """
    carried = {PurePosixPath(each.path): key for key, each in copies.migrated.items()}
    return carried | {
        worklog_path(source, each.type, each.id, each.title): each.id
        for each in copies.documents.values()
    }


def retired(
    stray: Iterable[PurePosixPath], known: AbstractSet[str], written: AbstractSet[str]
) -> set[PurePosixPath]:
    """Return the files of ``stray``, of no document's place, whose name only written ids begin.

    ``worklog_path`` names a file by its id, alone or before a dash and its title's slug,
    so that a name may be that of several ids: ``e-<digest>-2-notes.md`` is
    ``e-<digest>-2``'s titled ``Notes`` and ``e-<digest>``'s titled ``2 notes``. A file
    is retired, as the old file of a document written under another path, when each id of
    ``known`` that begins its name, alone or before a dash, is ``written``, one at least;
    else its owner is not known, and it stays.
    """
    found: set[PurePosixPath] = set()
    for path in stray:
        stem = path.stem
        named = known & {stem, *(stem[:end] for end, mark in enumerate(stem) if mark == "-")}
        if named and named <= written:
            found.add(path)
    return found
