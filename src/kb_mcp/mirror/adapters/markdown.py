"""The mirror's Markdown files: their front matter, and which files are documents.

The mirror writes front matter with ``dump`` and search reads it with ``load``, so the
two agree on every key, type and quotation without either guessing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

from kb_mcp.kernel.fields import Fields, RepresentationError
from kb_mcp.kernel.names import ASSETS, ATLASSIAN_ISSUER
from kb_mcp.mirror.domain.mirror import FrontMatter, Link, Mention, document_id

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

FRONT_MATTER_KEYS = list(FrontMatter.model_fields)
PERSON = list(Mention.model_fields)
LINK = list(Link.model_fields)
# The keys of the front matter that the files of plan 058 hold, which ``load`` reads until
# every file has been prepared once after the upgrade; a later plan removes them.
FORMER_KEYS = [
    *("source", "type", "id", "key", "title", "space", "project", "status", "issue_type"),
    *("labels", "people", "links", "created", "updated", "version", "revision", "url"),
    *("breadcrumb", "fetched_at"),
]
TIME = "%Y-%m-%dT%H:%M:%SZ"
OPENING = "---\n"
CLOSING = "\n---\n"
# The documents of the mirror, relative to <data>/docs: every Markdown file, whichever
# source wrote it, but those under assets/, where an attached x.md is an asset, and
# those with a name beginning with _ or . on their path.
DOCUMENT_GLOBS = ("**/*.md",)


class Dumper(yaml.SafeDumper):
    """YAML's safe dumper, which writes each person and link of the front matter on one line."""

    def represent_person(self, person: Mention) -> yaml.MappingNode:
        """Write a person in flow style, its fields in ``Mention``'s order, as ``load`` asks.

        A field without a value, an identity of None or no times, is left out, as ``load``
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


Dumper.add_representer(Mention, Dumper.represent_person)
Dumper.add_representer(Link, Dumper.represent_link)


def dump(front_matter: FrontMatter, body: str) -> str:
    """Write a document: its front matter, a blank line, then its Markdown body.

    Times are written in UTC to the second, as quoted strings; every string that YAML
    could read as another type (``000003``, ``Yes``) is quoted; each person and each link
    is one line.
    """
    values: dict[str, object] = {}
    for key in FRONT_MATTER_KEYS:
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
    person's field other than ``Mention``'s, out of their order, or an empty ``at``,
    and a link's field other than ``Link``'s, or out of their order. Until every file has
    been prepared once after the upgrade, as a later plan removes it: a person's
    ``account``, which plan 041's files hold in place of ``identity`` and the Atlassian
    connectors alone wrote, reads as an identity of ATLASSIAN_ISSUER's; and a front
    matter of FORMER_KEYS reads as today's: its ``space`` or ``project`` as its scope,
    else the work log's one scope, ``folder:<source>``; its ``issue_type`` as its
    subtype; no parent; each link's ``ref``, a key or id of its own source, as the
    document of that id; ``fetched_at`` left out.
    """
    end = text.find(CLOSING, len(OPENING) - 1)
    if not text.startswith(OPENING) or end < 0:
        message = f"{path}: no front matter"
        raise RepresentationError(message)
    try:
        values = yaml.safe_load(text[len(OPENING) : end + 1])
    except yaml.YAMLError:
        values = None
    if type(values) is not dict or list(values) not in (FRONT_MATTER_KEYS, FORMER_KEYS):
        # The mirror's keys that it lacks, never the file's own: those could be content.
        lacking = [key for key in FRONT_MATTER_KEYS if type(values) is dict and key not in values]
        message = f"{path}: front matter without exactly the mirror's keys, in order" + (
            f", without {', '.join(lacking)}" if lacking else ""
        )
        raise RepresentationError(message)
    fields = Fields(values, path)
    former = list(values) == FORMER_KEYS
    people = []
    for person in fields.objects("people"):
        held = "account" if "account" in person.value else "identity"
        in_order(person, [held if name == "identity" else name for name in PERSON])
        value = person.text(held) if held in person.value else None
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
                Mention(
                    role=person.text("role"),
                    name=person.text("name"),
                    identity=f"{ATLASSIAN_ISSUER}:{value}" if held == "account" else value,
                    at=tuple(times.time(name) for name in times.value),
                )
            )
    source, links = fields.text("source"), []
    for link in fields.objects("links"):
        held = "ref" if former else "document"
        in_order(link, [held if name == "document" else name for name in LINK])
        other = link.text(held)
        with link.refusals():
            links.append(
                Link(
                    relation=link.text("relation"),
                    document=document_id(source, other) if former else other,
                )
            )
    if former:
        named = [
            f"{name}:{key}" for name in ("space", "project") if (key := fields.optional_text(name))
        ]
        scope, subtype, parent = (named or [f"folder:{source}"])[0], "issue_type", None
    else:
        scope, subtype = fields.text("scope"), "subtype"
        parent = fields.optional_text("parent")
    with fields.refusals():
        front_matter = FrontMatter(
            source=source,
            type=fields.text("type"),
            id=fields.text("id"),
            key=fields.optional_text("key"),
            title=fields.text("title"),
            scope=scope,
            status=fields.text("status"),
            subtype=fields.optional_text(subtype),
            labels=fields.texts("labels"),
            people=tuple(people),
            parent=parent,
            links=tuple(links),
            created=fields.time("created"),
            updated=fields.time("updated"),
            version=fields.optional_integer("version"),
            revision=fields.text("revision"),
            url=fields.optional_text("url"),
            breadcrumb=fields.texts("breadcrumb"),
        )
    return front_matter, text[end + len(CLOSING) :].removeprefix("\n")


def documents(docs: Path, patterns: Iterable[str] = DOCUMENT_GLOBS) -> Iterator[Path]:
    """Yield every document file under ``docs`` that the patterns find, sorted by path.

    None is under ``assets/``, and no name on the way to one begins with ``_`` or ``.``.
    """
    for path in sorted({path for pattern in patterns for path in docs.glob(pattern)}):
        names = path.relative_to(docs).parts
        if (
            path.is_file()
            and names[0] != ASSETS
            and not any(name.startswith(("_", ".")) for name in names)
        ):
            yield path
