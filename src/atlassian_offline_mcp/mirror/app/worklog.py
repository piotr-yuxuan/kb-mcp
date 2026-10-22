"""The work log's step: its org files, read in place, as Markdown files of the mirror.

It reads the work log's folder, converts each document whose revision is not the one its
file holds, and hands every file to ``mirror_files``, which writes those that changed and
removes, under ``worklog/`` alone, those of documents gone. A document whose file holds
its revision keeps that file's body, dates and time of fetch, so that an edit elsewhere
in its org file moves neither. A run that reports a problem removes nothing, so that the
last good copy of each file stays.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from atlassian_offline_mcp.mirror.adapters.markdown import WORKLOG, documents, dump, load
from atlassian_offline_mcp.mirror.adapters.mirror_files import Changes, sync, worklog_owned
from atlassian_offline_mcp.mirror.adapters.pandoc import ORG, PandocFailedError
from atlassian_offline_mcp.mirror.app.mirror import Problem
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter
from atlassian_offline_mcp.mirror.domain.mirror_layout import one_line, worklog_path
from atlassian_offline_mcp.sources.worklog.adapters import files
from atlassian_offline_mcp.sources.worklog.domain.worklog import (
    TODO,
    TODO_ARCHIVE,
    TRANSCRIPTS,
    entries,
    revision,
    transcripts,
)

if TYPE_CHECKING:
    from pathlib import Path

    from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc
    from atlassian_offline_mcp.sources.worklog.domain.worklog import Source

SOURCE = "worklog"


@dataclass(frozen=True)
class Outcome:
    """What a run did: documents mirrored, files changed, HTML transcripts left out.

    Problems stop removals; warnings, such as two transcripts of one id, do not.
    """

    documents: int
    changes: Changes
    html: int
    problems: tuple[Problem, ...]
    warnings: tuple[str, ...]


def mirror_worklog(folder: Path, docs: Path, pandoc: Pandoc, *, archives: bool = True) -> Outcome:
    """Mirror the work log under ``folder`` into ``docs/worklog/``, with ``pandoc``.

    Without ``archives``, the archive file, ``transcripts/archive/`` and the subtrees
    tagged ARCHIVE are left out, and so their files removed.
    """
    listing = files.listed(folder, archives=archives)
    problems = [Problem(each.path, each.reason) for each in listing.problems]
    sources: list[Source] = []
    for relative in listing.paths:
        try:
            sources.append(files.source(listing.root, relative))
        except files.UnreadableError as error:
            problems.append(Problem(str(relative), str(error)))
    found = {each.path: each for each in sources}
    named, warnings = transcripts(
        [each for each in sources if each.path.parts[0] == TRANSCRIPTS], archives=archives
    )
    todo, archive = found.get(PurePosixPath(TODO)), found.get(PurePosixPath(TODO_ARCHIVE))
    converter = "\n".join([pandoc.version(), *ORG])
    kept: dict[str, tuple[FrontMatter, str]] = {}
    for file in documents(docs, WORKLOG):
        try:
            matter, body = load(file.read_text(encoding="utf-8"), str(file))
        except OSError, ValueError:
            continue  # the step's own file, damaged: written again or removed
        kept[matter.id] = (matter, body)
    wanted: dict[PurePosixPath, bytes | Path] = {}
    for document in [*entries(todo, archive, archives=archives), *named]:
        name = revision(converter, document.text)
        old, body = kept.get(document.id, (None, ""))
        if old is not None and old.revision == name:
            created, updated, fetched_at = old.created, old.updated, old.fetched_at
        else:
            try:
                body = pandoc.org_markdown(document.text)
            except PandocFailedError as error:
                problems.append(Problem(f"{document.source.path}, {document.id}", str(error)))
                continue
            created, updated = document.dates(None if old is None else old.created)
            fetched_at = document.source.fetched_at
        matter = FrontMatter(
            source=SOURCE,
            type=document.type,
            id=document.id,
            key=None,
            title=one_line(document.title),
            space=None,
            project=None,
            status=one_line(document.status),
            issue_type=None,
            labels=tuple(one_line(label) for label in document.labels),
            author=None,
            assignee=None,
            created=created,
            updated=updated,
            version=None,
            revision=name,
            url=None,
            breadcrumb=tuple(one_line(part) for part in document.breadcrumb),
            fetched_at=fetched_at,
        )
        wanted[worklog_path(document.type, document.id, document.title)] = dump(
            matter, body
        ).encode()
    changes = sync(docs, wanted, worklog_owned, remove=not problems)
    return Outcome(len(wanted), changes, listing.html, tuple(problems), tuple(warnings))
