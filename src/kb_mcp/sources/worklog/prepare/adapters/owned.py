"""The files of the mirror that the work log's step owns, and so may remove."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.mirror.adapters.markdown import WORKLOG, documents
from kb_mcp.mirror.adapters.mirror_files import regular_files

if TYPE_CHECKING:
    from pathlib import Path, PurePosixPath


def worklog_owned(docs: Path) -> set[PurePosixPath]:
    """Return the files under ``docs`` that the work log's step owns: its documents."""
    return regular_files(docs, documents(docs, WORKLOG))
