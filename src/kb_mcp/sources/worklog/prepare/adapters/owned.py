"""The files of the mirror that the work log's preparer owns, and so may remove."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.mirror.adapters.markdown import documents
from kb_mcp.mirror.adapters.mirror_files import regular_files
from kb_mcp.sources.worklog.prepare.domain.layout import worklog_globs

if TYPE_CHECKING:
    from pathlib import Path, PurePosixPath


def worklog_owned(docs: Path, source: str) -> set[PurePosixPath]:
    """Return the files under ``docs`` that the work log's preparer owns for ``source``."""
    return regular_files(docs, documents(docs, worklog_globs(source)))
