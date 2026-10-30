"""The files of the mirror that Confluence's and Jira's step owns, and so may remove."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.mirror.adapters.markdown import documents
from kb_mcp.mirror.adapters.mirror_files import regular_files
from kb_mcp.sources.atlassian.prepare.domain.layout import ASSET_NAME, ASSETS, TREE

if TYPE_CHECKING:
    from pathlib import Path, PurePosixPath

# The documents of Confluence and Jira, relative to <data>/docs.
ATLASSIAN = ("confluence/*/*.md", "confluence/*/blog/*.md", "jira/*/*.md")


def owned(docs: Path) -> set[PurePosixPath]:
    """Return the files under ``docs`` that the mirror owns: documents, trees, assets.

    Hidden files, such as one left by an interrupted write, and any other file are not
    the mirror's.
    """
    found = [*documents(docs, ATLASSIAN), *docs.glob(f"confluence/*/{TREE}")]
    assets = docs / ASSETS
    if assets.is_dir():
        found += [path for path in assets.iterdir() if ASSET_NAME.fullmatch(path.name)]
    return regular_files(docs, found)
