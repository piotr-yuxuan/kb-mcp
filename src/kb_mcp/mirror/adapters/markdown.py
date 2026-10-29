"""The mirror's Markdown files: their front matter, and which files are documents.

The mirror writes front matter with ``dump`` and search reads it with ``load``, so the
two agree on every key, type and quotation without either guessing.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.mirror.domain.mirror import FrontMatter, Link, PersonRole
from kb_mcp.mirror.domain.mirror_layout import WORKLOG_FOLDERS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

KEYS = [field.name for field in dataclasses.fields(FrontMatter)]
PERSON = [field.name for field in dataclasses.fields(PersonRole)]
LINK = [field.name for field in dataclasses.fields(Link)]
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
    """YAML's safe dumper, which writes each person and link of the front matter on one line."""

    def represent_person(self, person: PersonRole) -> yaml.MappingNode:
        """Write a person in flow style, its fields in ``PersonRole``'s order, as ``load`` asks.

        A field without a value, an account of None or no times, is left out, as ``load``
        reads its absence.
        """
        values: dict[str, object] = {}
        for name in PERSON:
            value = getattr(person, name)
            if isinstance(value, tuple):
                value = [moment.astimezone(UTC).strftime(TIME) for moment in value]
            if value not in (None, []):
                values[name] = value
        return self.represent_mapping("tag:yaml.org,2002:map", values, flow_style=True)

    def represent_link(self, link: Link) -> yaml.MappingNode:
        """Write a link in flow style, its fields in ``Link``'s order, as ``load`` asks."""
        values = {name: getattr(link, name) for name in LINK}
        return self.represent_mapping("tag:yaml.org,2002:map", values, flow_style=True)


Dumper.add_representer(PersonRole, Dumper.represent_person)
Dumper.add_representer(Link, Dumper.represent_link)


def dump(front_matter: FrontMatter, body: str) -> str:
    """Write a document: its front matter, a blank line, then its Markdown body.

    Times are written in UTC to the second, as quoted strings; every string that YAML
    could read as another type (``000003``, ``Yes``) is quoted; each person and each link
    is one line.
    """
    values: dict[str, object] = {}
    for key in KEYS:
        value = getattr(front_matter, key)
        if isinstance(value, datetime):
            value = value.astimezone(UTC).strftime(TIME)
        values[key] = list(value) if isinstance(value, tuple) else value
    text = yaml.dump(values, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=1_000_000)
    return f"{OPENING}{text}{CLOSING.lstrip()}\n{body}"


def in_order(entry: Fields, names: Sequence[str]) -> None:
    """Refuse an entry of a list whose fields are other than ``names``, or out of their order.

    The refusal names the entry's place, such as ``people[0]``, and the fields.
    """
    if list(entry.value) != [name for name in names if name in entry.value]:
        message = f"{entry.path}: fields other than {', '.join(names)}, or out of order"
        raise RepresentationError(message)


def load(text: str, path: str) -> tuple[FrontMatter, str]:
    """Read a document written by ``dump``: its front matter and its body.

    Any other key, order or type is refused, naming ``path`` and the key, as is a
    person's field other than ``PersonRole``'s, out of their order, or an empty ``at``,
    and a link's field other than ``Link``'s, or out of their order.
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
        # The mirror's keys that it lacks, never the file's own: those could be content.
        lacking = [key for key in KEYS if type(values) is dict and key not in values]
        message = f"{path}: front matter without exactly the mirror's keys, in order" + (
            f", without {', '.join(lacking)}" if lacking else ""
        )
        raise RepresentationError(message)
    fields = Fields(values, path)
    people = []
    for person in fields.objects("people"):
        in_order(person, PERSON)
        # The times go through a Fields of their own, keyed at[0], at[1] and so on, so
        # that Fields.time reads each strictly and a refusal names its place, as objects
        # names an entry's. An empty list, which dump never writes, would read as no
        # times at all.
        at = person.texts("at") if "at" in person.value else None
        if at == ():
            message = f"{person.path}.at: empty"
            raise RepresentationError(message)
        times = Fields({f"at[{index}]": text for index, text in enumerate(at or ())}, person.path)
        with person.refusals():
            people.append(
                PersonRole(
                    role=person.text("role"),
                    name=person.text("name"),
                    account=person.text("account") if "account" in person.value else None,
                    at=tuple(times.time(name) for name in times.value),
                )
            )
    links = []
    for link in fields.objects("links"):
        in_order(link, LINK)
        with link.refusals():
            links.append(Link(relation=link.text("relation"), ref=link.text("ref")))
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
            links=tuple(links),
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
