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
from atlassian_offline_mcp.mirror.domain.mirror import FrontMatter, PersonRole
from atlassian_offline_mcp.mirror.domain.mirror_layout import WORKLOG_FOLDERS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

KEYS = [field.name for field in dataclasses.fields(FrontMatter)]
PERSON = [field.name for field in dataclasses.fields(PersonRole)]
TIME = "%Y-%m-%dT%H:%M:%SZ"
OPENING = "---\n"
CLOSING = "\n---\n"
# The documents of the mirror, relative to <data>/docs, by the step that writes them,
# then all of them; names beginning with _ or . are not documents, and nothing under
# assets/ is.
ATLASSIAN = ("confluence/*/*.md", "confluence/*/blog/*.md", "jira/*/*.md")
WORKLOG = tuple(f"{folder}/*.md" for folder in WORKLOG_FOLDERS.values())
DOCUMENTS = (*ATLASSIAN, *WORKLOG)


class Dumper(yaml.SafeDumper):
    """YAML's safe dumper, which writes each person of the front matter on one line."""

    def represent_person(self, person: PersonRole) -> yaml.MappingNode:
        """Write a person in flow style: role, name, then the account and times if any."""
        values: dict[str, object] = {"role": person.role, "name": person.name}
        if person.account is not None:
            values["account"] = person.account
        if person.at:
            values["at"] = [moment.astimezone(UTC).strftime(TIME) for moment in person.at]
        return self.represent_mapping("tag:yaml.org,2002:map", values, flow_style=True)


Dumper.add_representer(PersonRole, Dumper.represent_person)


def dump(front_matter: FrontMatter, body: str) -> str:
    """Write a document: its front matter, a blank line, then its Markdown body.

    Times are written in UTC to the second, as quoted strings; every string that YAML
    could read as another type (``000003``, ``Yes``) is quoted; each person is one line.
    """
    values: dict[str, object] = {}
    for key in KEYS:
        value = getattr(front_matter, key)
        if isinstance(value, datetime):
            value = value.astimezone(UTC).strftime(TIME)
        values[key] = list(value) if isinstance(value, tuple) else value
    text = yaml.dump(values, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=1_000_000)
    return f"{OPENING}{text}{CLOSING.lstrip()}\n{body}"


def load(text: str, path: str) -> tuple[FrontMatter, str]:
    """Read a document written by ``dump``: its front matter and its body.

    Any other key, order or type is refused, naming ``path`` and the key, as is a
    person's field other than ``PersonRole``'s, or out of their order.
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
    people = []
    for person in fields.objects("people"):
        if list(person.value) != [name for name in PERSON if name in person.value]:
            message = f"{person.path}: fields other than {', '.join(PERSON)}, or out of order"
            raise RepresentationError(message)
        # Each time read as a field of its own, so that a refusal names its place.
        at = person.texts("at") if "at" in person.value else ()
        times = Fields({f"at[{index}]": text for index, text in enumerate(at)}, person.path)
        with person.refusals():
            people.append(
                PersonRole(
                    role=person.text("role"),
                    name=person.text("name"),
                    account=person.text("account") if "account" in person.value else None,
                    at=tuple(times.time(name) for name in times.value),
                )
            )
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
            people=tuple(people),
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
