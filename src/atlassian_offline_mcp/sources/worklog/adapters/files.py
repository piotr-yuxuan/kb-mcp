"""The work log's folder, read in place: never written, and never through git.

``listed`` finds ``todo.org``, ``todo.org_archive`` and every ``*.org`` under
``transcripts/``, and counts the HTML transcripts, which are never read; ``source`` reads
one of them. Names beginning with ``.`` or ``#`` or ending in ``~`` (hidden files, and
Emacs's lock, autosave and backup files) are passed over. A link is followed only to a
file or a folder inside the work log. A file over a bound, linking out or not UTF-8 is
named by its path, never by its content.
"""

from __future__ import annotations

import heapq
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from atlassian_offline_mcp.sources.worklog.domain.worklog import (
    ARCHIVED,
    ORG,
    TODO,
    TODO_ARCHIVE,
    TRANSCRIPTS,
    Source,
)

if TYPE_CHECKING:
    from pathlib import Path

MEBIBYTE = 1024 * 1024
FILE_BYTES = 32 * MEBIBYTE
TRANSCRIPT_COUNT = 20_000
HTML = ".html"


class UnreadableError(OSError):
    """A file of the work log not read; the message says why, never with its content."""


@dataclass(frozen=True)
class Problem:
    """Something of the work log not read: its path within the folder, and why."""

    path: str
    reason: str


@dataclass(frozen=True)
class Listing:
    """The org files found, in path order, the HTML transcripts counted, and problems."""

    root: Path  # the work log's folder, resolved
    paths: tuple[PurePosixPath, ...]  # relative to the root
    html: int
    problems: tuple[Problem, ...]


def listed(folder: Path, *, archives: bool) -> Listing:
    """Find the work log's org files under ``folder``, following links inside it alone.

    Without ``archives``, ``todo.org_archive`` and ``transcripts/archive/`` are left out.
    Past 20,000 transcripts, the first in path order are kept and a problem is reported.
    """
    root = folder.resolve()
    if not root.is_dir():
        return Listing(root, (), 0, (Problem(".", "not a folder"),))
    problems: list[Problem] = []
    found: list[PurePosixPath] = []  # every file found, of any kind
    seen = {root}
    archive = PurePosixPath(TODO_ARCHIVE)
    # Archived by its path, or by what it links to.
    archived_paths = ((root / archive).resolve(), (root / TRANSCRIPTS / ARCHIVED).resolve())
    # Paths that cross fewer links come first, then in path order: a folder is read by
    # its own path before any link to it, wherever the link is.
    queue = [
        (int(path.is_symlink()), path) for path in (root / TODO, root / archive, root / TRANSCRIPTS)
    ]
    heapq.heapify(queue)
    while queue:
        crossed, path = heapq.heappop(queue)
        relative = PurePosixPath(path.relative_to(root).as_posix())
        real = path.resolve()
        archived = (
            relative == archive
            or relative.parts[:2] == (TRANSCRIPTS, ARCHIVED)
            or any(real.is_relative_to(each) for each in archived_paths)
        )
        if (
            path.name.startswith((".", "#"))
            or path.name.endswith("~")
            or (archived and not archives)
            or real in seen
            or not path.exists()
        ):
            continue
        if not real.is_relative_to(root):
            problems.append(Problem(str(relative), "links outside the work log"))
        elif real.is_dir() and relative.parts[0] == TRANSCRIPTS:
            seen.add(real)
            try:
                for each in path.iterdir():
                    heapq.heappush(queue, (crossed + each.is_symlink(), each))
            except OSError as error:
                problems.append(Problem(str(relative), f"not read ({type(error).__name__})"))
        elif real.is_file():
            found.append(relative)
    # Of the files found, the HTML transcripts are counted; todo.org, todo.org_archive and
    # the org transcripts are read.
    html = sum(1 for path in found if path.parts[0] == TRANSCRIPTS and path.suffix == HTML)
    others = sorted(path for path in found if path.parts[0] != TRANSCRIPTS)
    transcripts = sorted(
        path for path in found if path.parts[0] == TRANSCRIPTS and path.suffix == ORG
    )
    if len(transcripts) > TRANSCRIPT_COUNT:
        problems.append(Problem(TRANSCRIPTS, f"over {TRANSCRIPT_COUNT} transcripts"))
    paths = (*others, *transcripts[:TRANSCRIPT_COUNT])
    return Listing(root, paths, html, tuple(problems))


def source(root: Path, relative: PurePosixPath) -> Source:
    """Read one org file that ``listed`` found under ``root``.

    Raises ``UnreadableError`` for a file that is not regular, is over 32 MiB, is not
    UTF-8, or cannot be read, its time of change included.
    """
    path = root / relative
    data = b""
    try:
        status = path.stat()
        modified = datetime.fromtimestamp(status.st_mtime, UTC).astimezone()
        regular = stat.S_ISREG(status.st_mode) and status.st_size <= FILE_BYTES
        if regular:
            with path.open("rb") as file:
                data = file.read(FILE_BYTES + 1)
    except (OSError, OverflowError, ValueError) as error:
        message = f"not read ({type(error).__name__})"
        raise UnreadableError(message) from None
    if not regular or len(data) > FILE_BYTES:
        message = f"not a file of at most {FILE_BYTES // MEBIBYTE} MiB"
        raise UnreadableError(message)
    try:
        text = data.decode()
    except UnicodeDecodeError:
        message = "not UTF-8"
        raise UnreadableError(message) from None
    return Source(relative, text, modified)
