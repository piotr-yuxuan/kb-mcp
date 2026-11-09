"""The files of the mirror that Confluence's and Jira's prepares own, and so may remove.

Each source owns its documents, under its own folder, and Confluence each space's tree;
the attached files under ``assets/`` are theirs together, and a document's file holds
on to those that it links.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.mirror.adapters.markdown import documents
from kb_mcp.mirror.adapters.mirror_files import regular_files
from kb_mcp.sources.atlassian.fetch.domain.content import ConfluenceDocument
from kb_mcp.sources.atlassian.fetch.domain.names import CONFLUENCE, JIRA
from kb_mcp.sources.atlassian.prepare.domain.layout import ASSET_NAME, ASSETS, TREE

if TYPE_CHECKING:
    from pathlib import Path, PurePosixPath

# The documents of each Atlassian source, by its name, relative to <data>/docs.
ATLASSIAN_OWNED = {
    CONFLUENCE: (f"{CONFLUENCE}/*/*.md", f"{CONFLUENCE}/*/blog/*.md"),
    JIRA: (f"{JIRA}/*/*.md",),
}


def owned(docs: Path, source: str) -> set[PurePosixPath]:
    """Return the files under ``docs`` that one Atlassian source owns alone.

    They are its documents, and for Confluence each space's tree. Hidden files, such as
    one left by an interrupted write, and any other file are not its.
    """
    found = list(documents(docs, ATLASSIAN_OWNED[source]))
    if source == ConfluenceDocument.source:
        found += docs.glob(f"{source}/*/{TREE}")
    return regular_files(docs, found)


def attached(docs: Path) -> set[PurePosixPath]:
    """Return the attached files under ``docs``, which Confluence and Jira own together."""
    assets = docs / ASSETS
    found = []
    if assets.is_dir():
        found = [path for path in assets.iterdir() if ASSET_NAME.fullmatch(path.name)]
    return regular_files(docs, found)


def unlinked(docs: Path, candidates: set[PurePosixPath]) -> set[PurePosixPath]:
    """Return those of these attached files that no file of either source under ``docs`` links.

    A file not rebuilt, the other source's or one that failed to convert, still links
    what its document wanted when it was written. Its link holds the attached file's
    name, a digest, so a mention of it holds the file too. Reads no file without a
    candidate.
    """
    left = set(candidates)
    for source in ATLASSIAN_OWNED if left else ():
        for relative in owned(docs, source):
            text = (docs / relative).read_bytes()
            left = {each for each in left if each.name.encode() not in text}
    return left
