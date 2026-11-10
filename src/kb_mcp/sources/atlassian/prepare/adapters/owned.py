"""The files of the mirror that Confluence's and Jira's prepares own, and so may remove.

Each source owns its documents, under its own folder, and one of spaces each space's
tree; the attached files under ``assets/`` are theirs together, and a document's file
holds on to those that it links.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.names import ASSETS
from kb_mcp.mirror.adapters.markdown import documents
from kb_mcp.mirror.adapters.mirror_files import regular_files
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.atlassian.prepare.domain.layout import ASSET_NAME, TREE

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path, PurePosixPath

# Where the documents of each class lie in their source's folder of the mirror.
OWNED: dict[type[Page | BlogPost | Issue], str] = {
    Page: "*/*.md",
    BlogPost: "*/blog/*.md",
    Issue: "*/*.md",
}


def owned(
    docs: Path, source: str, document_classes: Collection[type[Page | BlogPost | Issue]]
) -> set[PurePosixPath]:
    """Return the files under ``docs`` that one Atlassian source, of these classes, owns alone.

    They are its documents, and with pages each space's tree. Hidden files, such as one
    left by an interrupted write, and any other file are not its.
    """
    found = list(documents(docs, {f"{source}/{OWNED[each]}" for each in document_classes}))
    if Page in document_classes:
        found += docs.glob(f"{source}/*/{TREE}")
    return regular_files(docs, found)


def attached(docs: Path) -> set[PurePosixPath]:
    """Return the attached files under ``docs``, which Confluence and Jira own together."""
    assets = docs / ASSETS
    found = []
    if assets.is_dir():
        found = [path for path in assets.iterdir() if ASSET_NAME.fullmatch(path.name)]
    return regular_files(docs, found)


def unlinked(
    docs: Path,
    candidates: set[PurePosixPath],
    sources: Mapping[str, Collection[type[Page | BlogPost | Issue]]],
) -> set[PurePosixPath]:
    """Return those of these attached files that no file under ``docs`` of the sources links.

    ``sources`` gives each source's document classes by its name. A file not rebuilt,
    another source's or one that failed to convert, still links
    what its document wanted when it was written. Its link holds the attached file's
    name, a digest, so a mention of it holds the file too. Reads no file without a
    candidate.
    """
    left = set(candidates)
    for source, document_classes in sources.items() if left else ():
        for relative in owned(docs, source, document_classes):
            text = (docs / relative).read_bytes()
            left = {each for each in left if each.name.encode() not in text}
    return left
