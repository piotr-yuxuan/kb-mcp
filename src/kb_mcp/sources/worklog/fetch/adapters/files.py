"""The work log's folder, read in place: never written, and never through git.

A file over a bound, linking out or not UTF-8 is named by its path, never by its content.
"""

from __future__ import annotations

import heapq
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from kb_mcp.kernel.records import Problem, Record
from kb_mcp.sources.worklog.fetch.domain.worklog import (
    ARCHIVED,
    ORG,
    TODO,
    TODO_ARCHIVE,
    TRANSCRIPT_FOLDERS,
    OrgText,
)

MEBIBYTE = 1024 * 1024
FILE_BYTES = 32 * MEBIBYTE
TRANSCRIPT_COUNT = 20_000
HTML = ".html"
# The reason of a file or folder linking out of the work log; a folder not listed has
# its own.
LINKS_OUT = "links outside the work log"


class UnreadableError(OSError):
    """A file of the work log not read; the message says why, never with its content."""


class OrgFiles(Record):
    """The org files found, in path order, the HTML transcripts counted, and problems."""

    root: Path  # the work log's folder, resolved
    paths: tuple[PurePosixPath, ...]  # relative to the root
    html: int
    problems: tuple[Problem, ...]


def listed(folder: Path, *, archives: bool) -> OrgFiles:
    """Find the work log's org files under ``folder``, following links inside it alone.

    Past ``TRANSCRIPT_COUNT`` transcripts in both folders, the first in path order are kept
    and a problem naming the folders is reported.
    """
    root = folder.resolve()
    if not root.is_dir():
        return OrgFiles(
            root=root, paths=(), html=0, problems=(Problem(where=".", reason="not a folder"),)
        )
    problems: list[Problem] = []
    found: list[PurePosixPath] = []  # every file found, of any kind
    seen = {root}
    archive = PurePosixPath(TODO_ARCHIVE)
    # Archived by its path, or by what it links to.
    archived_paths = (
        (root / archive).resolve(),
        *((root / each / ARCHIVED).resolve() for each in TRANSCRIPT_FOLDERS),
    )
    # Paths that cross fewer links come first, then in path order: a folder is read by
    # its own path before any link to it, wherever the link is.
    queue = [
        (int(path.is_symlink()), path)
        for path in (root / TODO, root / archive, *(root / each for each in TRANSCRIPT_FOLDERS))
    ]
    heapq.heapify(queue)
    while queue:
        crossed, path = heapq.heappop(queue)
        relative = PurePosixPath(path.relative_to(root).as_posix())
        real = path.resolve()
        archived = (
            relative == archive
            or relative.parts[:2] in [(each, ARCHIVED) for each in TRANSCRIPT_FOLDERS]
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
            problems.append(Problem(where=str(relative), reason=LINKS_OUT))
        elif real.is_dir() and relative.parts[0] in TRANSCRIPT_FOLDERS:
            seen.add(real)
            try:
                for each in path.iterdir():
                    heapq.heappush(queue, (crossed + each.is_symlink(), each))
            except OSError as error:
                problems.append(
                    Problem(where=str(relative), reason=f"not read ({type(error).__name__})")
                )
        elif real.is_file():
            found.append(relative)
    html = sum(1 for path in found if path.parts[0] in TRANSCRIPT_FOLDERS and path.suffix == HTML)
    others = sorted(path for path in found if path.parts[0] not in TRANSCRIPT_FOLDERS)
    transcripts = sorted(
        path for path in found if path.parts[0] in TRANSCRIPT_FOLDERS and path.suffix == ORG
    )
    if len(transcripts) > TRANSCRIPT_COUNT:
        problems.append(
            Problem(
                where=", ".join(TRANSCRIPT_FOLDERS), reason=f"over {TRANSCRIPT_COUNT} transcripts"
            )
        )
    paths = (*others, *transcripts[:TRANSCRIPT_COUNT])
    return OrgFiles(root=root, paths=paths, html=html, problems=tuple(problems))


def org_text(root: Path, relative: PurePosixPath) -> OrgText:
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
    return OrgText(path=relative, text=text, modified=modified)
