"""Build the search index from the Markdown mirror, and from nothing else."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters import markdown, sqlite_index
from atlassian_offline_mcp.adapters.fields import RepresentationError
from atlassian_offline_mcp.domain.search import sections

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


class MirrorMissingError(Exception):
    """No mirror to index; the message names where it was looked for."""


@dataclass
class Report:
    """What a build indexed, and which files it skipped and why."""

    types: Counter[str] = field(default_factory=Counter)  # documents indexed per type
    sections: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # each path and reason


def build_index(docs: Path, index: Path, built_at: datetime) -> Report:
    """Index every document of the mirror at ``docs`` into a new index at ``index``.

    A file that cannot be read, that ``markdown.load`` refuses, or whose document is
    there already is skipped, and named in the report with a reason that holds no
    content. The index replaces the old one only once complete.
    """
    if not docs.is_dir():
        message = f"no mirror at {docs}: build it with `atlassian-offline-mcp mirror`"
        raise MirrorMissingError(message)
    report = Report()
    with sqlite_index.building(index, built_at) as writer:
        for file in markdown.documents(docs):
            path = file.relative_to(docs).as_posix()
            try:
                # Line endings are kept as written, so that a body reads back exactly.
                text = file.read_text(encoding="utf-8", newline="")
                front, body = markdown.load(text, path)
                cut = sections(body)
                writer.add(path, front, cut)
            except UnicodeDecodeError:
                reason = "not UTF-8"
            except OSError as error:
                reason = f"not readable ({type(error).__name__})"
            except (RepresentationError, sqlite_index.DuplicateDocumentError) as error:
                reason = str(error).removeprefix(f"{path}: ")
            else:
                report.types[front.type] += 1
                report.sections += len(cut)
                continue
            writer.skip()
            report.skipped.append((path, reason))
    return report
