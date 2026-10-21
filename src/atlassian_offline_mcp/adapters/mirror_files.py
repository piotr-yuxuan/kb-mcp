"""The files of the Markdown mirror under ``<data>/docs/``, written only when they change.

This is the only code that writes there. A file is written through a hidden file
renamed into place, so that a reader never sees half of it, and only when its bytes
differ, so that a run that changes nothing leaves every file and its time as they were.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters.markdown import documents
from atlassian_offline_mcp.domain.mirror_layout import ASSET_NAME, ASSETS, TREE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True)
class Changes:
    """How many files a run wrote, found unchanged, and removed."""

    written: int
    unchanged: int
    removed: int


def owned(docs: Path) -> set[PurePosixPath]:
    """Return the files under ``docs`` that the mirror owns: documents, trees, assets.

    Hidden files, such as one left by an interrupted write, and any other file are not
    the mirror's.
    """
    found = [*documents(docs), *docs.glob(f"confluence/*/{TREE}")]
    assets = docs / ASSETS
    if assets.is_dir():
        found += [path for path in assets.iterdir() if ASSET_NAME.fullmatch(path.name)]
    return {PurePosixPath(path.relative_to(docs).as_posix()) for path in found if path.is_file()}


def sync(
    docs: Path,
    wanted: Mapping[PurePosixPath, bytes | Path],
    *,
    remove: bool,
    retired: Iterable[PurePosixPath] = (),
) -> Changes:
    """Write each wanted file whose bytes differ, then remove the owned files not wanted.

    Each wanted file is given by its bytes, or by the path of a file to copy. Without
    ``remove``, only the ``retired`` files not wanted are removed: those of documents
    known to be gone or moved. A folder left empty by a removal goes too.
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
    unwanted = owned(docs) - set(wanted)
    stale = sorted(unwanted if remove else unwanted & set(retired))
    for relative in stale:
        (docs / relative).unlink()
        folder = (docs / relative).parent
        while folder != docs and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    return Changes(written, unchanged, len(stale))
