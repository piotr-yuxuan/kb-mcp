"""The memo source's preparer: a folder's text files, as the mirror's documents.

The memo's declaration names this module, a ``Preparer``: ``preflight`` refuses a
folder that is not one before any source starts, and ``prepare`` writes each ``*.txt``
file as ``docs/memo/<id>.md`` through the mirror's writer, which leaves a file that has
not changed and removes those of notes gone, under ``docs/memo/`` alone. A note's times
are its file's, so that a run that finds it unchanged writes the same bytes; its id is a
digest of its file's name, so that any name makes an id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from kb_mcp.kernel.outcome import Outcome
from kb_mcp.mirror.adapters.markdown import documents, dump
from kb_mcp.mirror.adapters.mirror_files import Changes, regular_files, write_changed
from kb_mcp.mirror.domain.mirror import FrontMatter
from kb_mcp.mirror.domain.mirror_text import one_line

if TYPE_CHECKING:
    from pathlib import Path

    from kb_mcp.kernel.output import Detail
    from kb_mcp.sources.stages import SourceRun

# The source's name, which is its folder of the mirror too, as the registry's rule has it.
SOURCE = "memo"


class MemoCounts(Changes):
    """The files that a prepare changed."""

    def text(self, _detail: Detail) -> str:
        """Write the files that it changed, whichever the detail."""
        return f"written: {self.written}\nunchanged: {self.unchanged}\nremoved: {self.removed}\n"


def owned(docs: Path) -> set[PurePosixPath]:
    """Return the files under ``docs`` that the source may remove: its documents alone."""
    return regular_files(docs, documents(docs, (f"{SOURCE}/*.md",)))


def preflight(run: SourceRun) -> str | None:
    """Refuse a folder of notes that is not one, by its setting, before any source starts."""
    return None if run.source_table.folder.is_dir() else f"sources.{SOURCE}.folder: not a folder"


def prepare(run: SourceRun) -> Outcome[MemoCounts]:
    """Write a document per note and remove those of notes gone, unless a dry run."""
    if run.dry_run:
        return Outcome(ending="not run")
    wanted: dict[PurePosixPath, bytes | Path] = {}
    for path in sorted(run.source_table.folder.glob("*.txt")):
        text = path.read_text("utf-8", errors="replace")
        when = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        identifier = sha256(path.name.encode()).hexdigest()[:16]
        matter = FrontMatter(
            source=SOURCE,
            type="note",
            id=identifier,
            key=None,
            title=one_line(path.stem),
            space=None,
            project=None,
            status="",
            issue_type=None,
            labels=(),
            people=(),
            links=(),
            created=when,
            updated=when,
            version=None,
            revision=sha256(text.encode()).hexdigest(),
            url=None,
            breadcrumb=(),
            fetched_at=when,
        )
        wanted[PurePosixPath(SOURCE, f"{identifier}.md")] = dump(matter, text).encode()
    changes = write_changed(run.settings.docs, wanted, owned, remove=True)
    return Outcome(ending="done", counts=MemoCounts(**dict(changes)))
