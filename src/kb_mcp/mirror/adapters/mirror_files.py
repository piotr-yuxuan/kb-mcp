"""The files of the Markdown mirror under ``<data>/docs/``, written only when they change.

This is the only code that writes there. A file is written through a hidden file
renamed into place, so that a reader never sees half of it, and only when its bytes
differ, so that a run that changes nothing leaves every file and its time as they were.
Each step removes only the files it owns, as its source's ``owned`` finds them:
Confluence's mirror those under ``confluence/``, Jira's those under ``jira/``, each the
attached files under ``assets/`` that no document wants or links, the work log's step
those under ``worklog/``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping


class Changes(Record):
    """How many files a run wrote, found unchanged, and removed."""

    written: int
    unchanged: int
    removed: int


def regular_files(docs: Path, found: Iterable[Path]) -> set[PurePosixPath]:
    """Return the regular files found, relative to ``docs``."""
    return {PurePosixPath(path.relative_to(docs).as_posix()) for path in found if path.is_file()}


def write_changed(
    docs: Path,
    wanted: Mapping[PurePosixPath, bytes | Path],
    owner: Callable[[Path], set[PurePosixPath]],
    *,
    remove: bool,
    retired: Iterable[PurePosixPath] = (),
) -> Changes:
    """Write each wanted file whose bytes differ, then remove the files not wanted.

    Each wanted file is given by its bytes, or by the path of a file to copy. The files
    removed are among those that ``owner`` (``owned`` or ``worklog_owned``) finds under
    ``docs``; without ``remove``, only the ``retired`` files not wanted are: those of
    documents known to be gone or moved. A folder left empty by a removal goes too.
    """
    written = unchanged = 0
    for relative, content in sorted(wanted.items()):
        target = docs / relative
        data = content.read_bytes() if isinstance(content, Path) else content
        if target.is_file() and target.read_bytes() == data:
            unchanged += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, hidden = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            Path(hidden).replace(target)
        finally:
            Path(hidden).unlink(missing_ok=True)
        written += 1
    unwanted = owner(docs) - set(wanted)
    stale = sorted(unwanted if remove else unwanted & set(retired))
    for relative in stale:
        (docs / relative).unlink()
        folder = (docs / relative).parent
        while folder != docs and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    return Changes(written=written, unchanged=unchanged, removed=len(stale))
