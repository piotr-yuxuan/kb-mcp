"""The mirror's Markdown files: their front matter, and which files are documents.

The mirror writes front matter with ``dump`` and search reads it with ``load``, so the
two agree on every key, type and quotation without either guessing.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

from atlassian_offline_mcp.kernel.fields import Fields, RepresentationError
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter
from atlassian_offline_mcp.mirror.domain.mirror_layout import WORKLOG_FOLDERS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

KEYS = [field.name for field in dataclasses.fields(FrontMatter)]
TIME = "%Y-%m-%dT%H:%M:%SZ"
OPENING = "---\n"
CLOSING = "\n---\n"
# The documents of the mirror, relative to <data>/docs, by the step that writes them,
# then all of them; names beginning with _ or . are not documents, and nothing under
# assets/ is.
ATLASSIAN = ("confluence/*/*.md", "confluence/*/blog/*.md", "jira/*/*.md")
WORKLOG = tuple(f"{folder}/*.md" for folder in WORKLOG_FOLDERS.values())
DOCUMENTS = (*ATLASSIAN, *WORKLOG)


def dump(front_matter: FrontMatter, body: str) -> str:
    """Write a document: its front matter, a blank line, then its Markdown body.

    Times are written in UTC to the second, as quoted strings; every string that YAML
    could read as another type (``000003``, ``Yes``) is quoted.
    """
    values: dict[str, object] = {}
    for key in KEYS:
        value = getattr(front_matter, key)
        if isinstance(value, datetime):
            value = value.astimezone(UTC).strftime(TIME)
        values[key] = list(value) if isinstance(value, tuple) else value
    text = yaml.safe_dump(values, sort_keys=False, allow_unicode=True, width=1_000_000)
    return f"{OPENING}{text}{CLOSING.lstrip()}\n{body}"


def load(text: str, path: str) -> tuple[FrontMatter, str]:
    """Read a document written by ``dump``: its front matter and its body.

    Any other key, order or type is refused, naming ``path`` and the key.
    """
    end = text.find(CLOSING, len(OPENING) - 1)
    if not text.startswith(OPENING) or end < 0:
        message = f"{path}: no front matter"
        raise RepresentationError(message)
    try:
        values = yaml.safe_load(text[len(OPENING) : end + 1])
    except yaml.YAMLError:
        values = None
    if type(values) is not dict or list(values) != KEYS:
        message = f"{path}: front matter without exactly the mirror's keys, in order"
        raise RepresentationError(message)
    fields = Fields(values, path)
    with fields.refusals():
        front_matter = FrontMatter(
            source=fields.text("source"),
            type=fields.text("type"),
            id=fields.text("id"),
            key=fields.optional_text("key"),
            title=fields.text("title"),
            space=fields.optional_text("space"),
            project=fields.optional_text("project"),
            status=fields.text("status"),
            issue_type=fields.optional_text("issue_type"),
            labels=fields.texts("labels"),
            author=fields.optional_text("author"),
            assignee=fields.optional_text("assignee"),
            created=fields.time("created"),
            updated=fields.time("updated"),
            version=fields.optional_integer("version"),
            revision=fields.text("revision"),
            url=fields.optional_text("url"),
            breadcrumb=fields.texts("breadcrumb"),
            fetched_at=fields.time("fetched_at"),
        )
    return front_matter, text[end + len(CLOSING) :].removeprefix("\n")


def documents(docs: Path, patterns: Iterable[str] = DOCUMENTS) -> Iterator[Path]:
    """Yield every document file under ``docs`` that the patterns find, in a stable order.

    No name on the way to a document begins with ``_`` or ``.``.
    """
    for pattern in patterns:
        for path in sorted(docs.glob(pattern)):
            names = path.relative_to(docs).parts
            if path.is_file() and not any(name.startswith(("_", ".")) for name in names):
                yield path
