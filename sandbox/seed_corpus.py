# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "defusedxml>=0.7,<1", "httpx>=0.28,<1", "pypandoc>=1.13,<2", "pyyaml>=6,<7",
#     "tzdata>=2025.2",
# ]
# ///
"""Seed the sandbox site with the corpus, or check the site against the repository.

It reads ``ATLASSIAN_SITE``, ``ATLASSIAN_EMAIL`` and ``ATLASSIAN_API_TOKEN`` from the
environment, so run it through sops, which gives the token to this process alone::

    sops exec-env <credentials file> 'uv run sandbox/seed_corpus.py'
    sops exec-env <credentials file> 'uv run sandbox/seed_corpus.py --check'

sandbox/README.md describes the corpus; plan 002 describes the design.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import posixpath
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import pypandoc
import yaml
from defusedxml import ElementTree

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

SPACE_KEY = "QM"
SPACE_NAME = "Quillmoor handbook"
IDEAS_PROJECT = "PRB"
# The content and issue property that records what the seeding wrote.
PROPERTY_KEY = "corpus-source"
SANDBOX = Path(__file__).parent
CORPUS = SANDBOX / "corpus"
IDEAS = SANDBOX / "jira" / "ideas"
TICKETS = SANDBOX / "jira" / "eng"
TICKET_PROJECT = "ENG"
TICKET_PROJECT_NAME = "Quillmoor Engineering"
SCRUM_TEMPLATE = "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic"
SPRINT_FIELD = "com.pyxis.greenhopper.jira:gh-sprint"
# A bound on the ticket listing: 30 pages of 100 tickets.
MAX_TICKET_PAGES = 30
# The sprint calendar of sandbox/README.md: sprint n starts SPRINT_DAYS * (n - 1) days
# after sprint 1, and SPRINTS is the active one. Nothing is dated after TODAY.
SPRINT_ONE = datetime(2025, 4, 14, tzinfo=UTC)
SPRINT_DAYS = 14
SPRINTS = 40
TODAY = datetime(2026, 10, 20, 23, 59, tzinfo=UTC)
CLOSED = frozenset({"Done", "Won't Do"})
STATUSES = CLOSED | {"In Progress", "To Do"}
TICKET_TYPES = frozenset({"Story", "Task", "Bug"})
PRIORITIES = frozenset({"Highest", "High", "Medium", "Low", "Lowest"})
# How Jira's REST API writes dates.
JIRA_DATE = "%Y-%m-%dT%H:%M:%S.%f%z"
# The date format to choose in the CSV importer's wizard: yyyy-MM-dd HH:mm. The importer
# reads dates in the importing account's time zone, so they are written in it.
CSV_DATE = "%Y-%m-%d %H:%M"
GOLDEN = SANDBOX / "golden.yaml"
OVERLAPS = frozenset({"identifier", "keyword", "paraphrase"})
# A golden question expects one document, or two when it needs a second hop.
MAX_HOPS = 2
TRAPS = frozenset(
    {
        "synonym",
        "acronym",
        "identifier",
        "near-duplicate",
        "outdated",
        "cross-link",
        "cross-lingual",
    }
)
# Storage-format XHTML uses these namespaces; parsing it needs them declared.
NAMESPACES = 'xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource"'
HTTP_TIMEOUT_S = 30
# A bound on cursor-paged listings: 20 pages of 250 results.
MAX_LISTING_PAGES = 20
# Languages of fenced code blocks; "text" becomes a code macro without a language.
CODE_LANGUAGES = frozenset({"bash", "python", "sql", "yaml", "json", "go", "typescript", "text"})
# GitHub alerts, as pandoc reads them, to the Confluence panel macros that show them.
PANELS = {
    "note": "info",
    "tip": "tip",
    "important": "note",
    "warning": "warning",
    "caution": "warning",
}

Action = Literal["create", "update", "leave"]


@dataclass(frozen=True)
class Question:
    """A golden question: the documents that answer it, and the traps it sets."""

    id: str
    question: str
    overlap: str
    lang: str
    expected: tuple[str, ...]
    partial: tuple[str, ...]
    evidence: Mapping[str, str]
    outdated: tuple[str, ...]
    traps: tuple[str, ...]
    distractors: tuple[str, ...]

    @property
    def documents(self) -> frozenset[str]:
        """Every document the question names."""
        return frozenset((*self.expected, *self.partial, *self.outdated, *self.distractors))


@dataclass(frozen=True)
class Page:
    """A corpus page: its key is its path under the corpus, without ``.md``."""

    key: str
    title: str
    lang: str
    markdown: str

    @property
    def parent(self) -> str | None:
        """The key of the parent page: the section page, or the home page for a section."""
        if self.key == "index":
            return None
        section, _, name = self.key.partition("/")
        return "index" if name == "index" else f"{section}/index"


@dataclass(frozen=True)
class Idea:
    """A Jira Product Discovery idea; its source is its path under the sandbox folder."""

    key: str
    summary: str
    markdown: str
    source: str


@dataclass(frozen=True)
class Ticket:
    """A ticket of the Jira project; an epic has no parent, and its type is Epic."""

    key: str
    type: str
    summary: str
    status: str
    priority: str
    labels: tuple[str, ...]
    markdown: str
    comments: tuple[str, ...]
    parent: str | None
    # The epic's first and last sprints, and the ticket's place among the epic's tickets.
    span: tuple[int, int]
    place: tuple[int, int]
    source: str

    @property
    def jira_status(self) -> tuple[str, str | None]:
        """The ticket's status and resolution in Jira's workflow: Won't Do is a resolution."""
        return ("Done", self.status) if self.status in CLOSED else (self.status, None)


@dataclass(frozen=True)
class Timeline:
    """When a ticket was created, resolved and commented on, and its sprint if any."""

    created: datetime
    resolved: datetime | None
    sprint: int | None
    comments: tuple[datetime, ...]


@dataclass(frozen=True)
class LivePage:
    """A page as the site holds it, with the property the last seeding wrote on it."""

    id: str
    title: str
    parent_id: str | None
    version: int
    source: Mapping[str, object] | None
    property_id: str | None
    property_version: int | None


def read_markdown(path: Path) -> tuple[dict[str, object], str]:
    """Split a Markdown file into its YAML front matter and its body."""
    text = path.read_text(encoding="utf-8")
    head, separator, body = text.removeprefix("---\n").partition("\n---\n")
    if not text.startswith("---\n") or not separator:
        message = f"{path}: no front matter"
        raise ValueError(message)
    meta = yaml.safe_load(head)
    if not isinstance(meta, dict):
        message = f"{path}: front matter is not a mapping"
        raise TypeError(message)
    return meta, body


def read_corpus(root: Path = CORPUS) -> dict[str, Page]:
    """Read every page under the corpus root, keyed by path."""
    pages: dict[str, Page] = {}
    for path in sorted(root.rglob("*.md")):
        key = path.relative_to(root).with_suffix("").as_posix()
        meta, body = read_markdown(path)
        title, lang = meta.get("title"), meta.get("lang", "en")
        if not isinstance(title, str) or lang not in {"en", "fr"} or set(meta) - {"title", "lang"}:
            message = f"{key}: front matter needs a title, and allows only lang: fr"
            raise ValueError(message)
        pages[key] = Page(key, title, str(lang), body)
    return pages


def read_ideas(root: Path = IDEAS) -> dict[str, Idea]:
    """Read every idea, keyed ``jira/<name>``."""
    ideas: dict[str, Idea] = {}
    for path in sorted(root.glob("*.md")):
        meta, body = read_markdown(path)
        if not isinstance(meta.get("summary"), str) or set(meta) != {"summary"}:
            message = f"{path}: front matter holds a summary only"
            raise ValueError(message)
        source = path.relative_to(root.parent.parent).as_posix()
        ideas[f"jira/{path.stem}"] = Idea(f"jira/{path.stem}", str(meta["summary"]), body, source)
    return ideas


def read_tickets(root: Path = TICKETS) -> list[Ticket]:
    """Read every epic file, in order: each epic, then its tickets."""
    tickets: list[Ticket] = []
    for path in sorted(root.glob("*.yaml")):
        source = path.relative_to(root.parent.parent).as_posix()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        epic, children = data["epic"], data["tickets"]
        first, last = (int(number) for number in epic["sprints"])
        if not 1 <= first <= last <= SPRINTS or set(data) != {"epic", "tickets"}:
            message = f"{source}: an epic file holds an epic and its tickets, within the sprints"
            raise ValueError(message)
        status = "Done" if last < SPRINTS else "In Progress"
        items = [{"type": "Epic", "status": status, "priority": "Medium", **epic}, *children]
        for place, item in enumerate(items):
            known = {"key", "type", "summary", "status", "priority", "labels", "description"}
            extra = set(item) - known - {"comments", "sprints"}
            if extra or not known <= set(item) or item["status"] not in STATUSES:
                message = f"{source}: {item.get('key')} has a missing, unknown or invalid field"
                raise ValueError(message)
            if place and (item["type"] not in TICKET_TYPES or item["priority"] not in PRIORITIES):
                message = f"{source}: {item['key']} has an invalid type or priority"
                raise ValueError(message)
            tickets.append(
                Ticket(
                    key=item["key"],
                    type=item["type"],
                    summary=item["summary"],
                    status=item["status"],
                    priority=item["priority"],
                    labels=tuple(item["labels"]),
                    markdown=item["description"],
                    comments=tuple(item.get("comments", ())),
                    parent=epic["key"] if place else None,
                    span=(first, last),
                    place=(place - 1, len(children)) if place else (0, 1),
                    source=source,
                )
            )
    return tickets


def read_golden(path: Path = GOLDEN) -> list[Question]:
    """Read the golden questions, refusing any that breaks the set's schema."""
    lists = ("expected", "partial", "outdated", "traps", "distractors")
    questions = []
    for item in yaml.safe_load(path.read_text(encoding="utf-8")):
        fields = {"id", "question", "overlap", "lang", "evidence", *lists}
        valid = (
            set(item) == fields
            and item["overlap"] in OVERLAPS
            and item["lang"] in {"en", "fr"}
            and 1 <= len(item["expected"]) <= MAX_HOPS
            and set(item["evidence"]) == set(item["expected"])
            and set(item["traps"]) <= TRAPS
        )
        if not valid:
            message = f"{path}: question {item.get('id')} breaks the golden set's schema"
            raise ValueError(message)
        questions.append(
            Question(
                **{name: item[name] for name in ("id", "question", "overlap", "lang")},
                **{name: tuple(item[name]) for name in lists},
                evidence=dict(item["evidence"]),
            )
        )
    return questions


def sprint_start(number: int) -> datetime:
    """Return the start of sprint n, at midnight UTC."""
    return SPRINT_ONE + timedelta(days=SPRINT_DAYS * (number - 1))


def draw(key: str, label: str, low: int, high: int) -> int:
    """Draw a whole number from low to high, the same every time for a key and a label."""
    digest = hashlib.sha256(f"{key}:{label}".encode()).digest()
    return low + int.from_bytes(digest[:8]) % (high - low + 1)


def timeline(ticket: Ticket) -> Timeline:
    """Derive a ticket's dates and sprint from its key, its epic's sprints and its place.

    An epic is created three weeks before its first sprint and, once done, resolved near
    the end of its last. A ticket's planned sprint follows its place in the epic; it is
    created up to 20 days before that sprint starts and, once closed, resolved inside it.
    A ticket in progress is in the active sprint; one to do is in the backlog.
    """
    first, last = ticket.span
    if ticket.parent is None:
        created = sprint_start(first) - timedelta(days=21) + timedelta(hours=10)
        done = ticket.status == "Done"
        resolved = sprint_start(last) + timedelta(days=12, hours=17) if done else None
        sprint = None
    else:
        index, count = ticket.place
        planned = first + index * (last - first + 1) // count
        sprint = {"In Progress": SPRINTS, "To Do": None}.get(ticket.status, planned)
        start = sprint_start(sprint or planned)
        age = timedelta(days=draw(ticket.key, "age", 1, 20), hours=draw(ticket.key, "at", 0, 8))
        created = start - age
        resolved = None
        if ticket.status in CLOSED:
            days = draw(ticket.key, "days", 0, 3 if sprint == SPRINTS else 10)
            resolved = start + timedelta(days=days, hours=draw(ticket.key, "hour", 9, 17))
    end = resolved or TODAY - timedelta(days=1)
    comments = sorted(
        created + (end - created) * draw(ticket.key, f"comment {number}", 1, 999) / 1000
        for number in range(len(ticket.comments))
    )
    return Timeline(created, resolved, sprint, tuple(comments))


def walk(value: object, rewrite: Callable[[dict], list[dict]]) -> object:
    """Rewrite every node of a pandoc AST bottom-up; a node may become several, or none."""
    if isinstance(value, dict):
        return {name: walk(item, rewrite) for name, item in value.items()}
    if not isinstance(value, list):
        return value
    result: list[object] = []
    for item in value:
        walked = walk(item, rewrite)
        result.extend(rewrite(walked) if isinstance(walked, dict) and "t" in walked else [walked])
    return result


def raw(kind: str, markup: str, markup_format: str = "html") -> dict:
    """Make a pandoc node of raw markup, of kind RawBlock or RawInline."""
    return {"t": kind, "c": [markup_format, markup]}


def storage_node(node: dict, key: str, titles: Mapping[str, str], linked: set[str]) -> list[dict]:
    """Rewrite one node for the storage format, adding the keys of linked pages to linked."""
    kind, content = node["t"], node.get("c")
    if kind in {"RawBlock", "RawInline"}:
        message = f"{key}: raw HTML is not allowed"
        raise ValueError(message)
    if kind == "CodeBlock":
        (_, classes, _), code = content
        language = classes[0] if classes else "text"
        if language not in CODE_LANGUAGES:
            message = f"{key}: code language {language!r} is not allowed"
            raise ValueError(message)
        parameter = f'<ac:parameter ac:name="language">{language}</ac:parameter>'
        # CDATA cannot hold ]]>, so it is split across two sections.
        body = "<![CDATA[" + code.replace("]]>", "]]]]><![CDATA[>") + "]]>"
        return [
            raw(
                "RawBlock",
                f'<ac:structured-macro ac:name="code">{parameter if language != "text" else ""}'
                f"<ac:plain-text-body>{body}</ac:plain-text-body></ac:structured-macro>",
            )
        ]
    if kind == "Div" and content[0][1] and content[0][1][0] in PANELS:
        panel = PANELS[content[0][1][0]]
        inner = [
            block
            for block in content[1]
            if not (block["t"] == "Div" and "title" in block["c"][0][1])
        ]
        return [
            raw("RawBlock", f'<ac:structured-macro ac:name="{panel}"><ac:rich-text-body>'),
            *inner,
            raw("RawBlock", "</ac:rich-text-body></ac:structured-macro>"),
        ]
    if kind != "Link" or urlsplit(content[2][0]).scheme in {"https", "mailto"}:
        return [node]
    target = content[2][0]
    page = posixpath.normpath(posixpath.join(posixpath.dirname(key), target)).removesuffix(".md")
    if not target.endswith(".md") or page not in titles:
        message = f"{key}: {target!r} is not a link to a corpus page"
        raise ValueError(message)
    linked.add(page)
    title = html.escape(titles[page])
    opening = f'<ac:link><ri:page ri:space-key="{SPACE_KEY}" ri:content-title="{title}"/>'
    return [
        raw("RawInline", opening + "<ac:link-body>"),
        *content[1],
        raw("RawInline", "</ac:link-body></ac:link>"),
    ]


def to_storage(page: Page, titles: Mapping[str, str]) -> tuple[str, frozenset[str]]:
    """Convert a page to Confluence's storage format; return it and the keys it links to."""
    document = json.loads(pypandoc.convert_text(page.markdown, "json", format="gfm-task_lists"))
    linked: set[str] = set()
    rewritten = walk(document, partial(storage_node, key=page.key, titles=titles, linked=linked))
    storage = pypandoc.convert_text(
        json.dumps(rewritten), "html", format="json", extra_args=["--wrap=none"]
    )
    try:
        ElementTree.fromstring(f"<root {NAMESPACES}>{storage}</root>")
    except ElementTree.ParseError as error:
        message = f"{page.key}: the storage format is not well-formed: {error}"
        raise ValueError(message) from error
    return storage, frozenset(linked)


def jira_node(node: dict, source: str, urls: Mapping[str, str]) -> list[dict]:
    """Rewrite one node for Jira: a link to a corpus page points at the page on the site."""
    kind, content = node["t"], node.get("c")
    if kind in {"RawBlock", "RawInline"}:
        message = f"{source}: raw HTML is not allowed"
        raise ValueError(message)
    if kind == "Header":
        # pandoc's jira writer puts an {anchor} before every heading, even without an id.
        return [{"t": "Para", "c": [raw("RawInline", f"h{content[0]}. ", "jira"), *content[2]]}]
    if kind != "Link" or urlsplit(content[2][0]).scheme in {"https", "mailto"}:
        return [node]
    target = content[2][0]
    path = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
    page = path.removeprefix("corpus/").removesuffix(".md")
    if not (path.startswith("corpus/") and target.endswith(".md")) or page not in urls:
        message = f"{source}: {target!r} is not a link to a page on the site"
        raise ValueError(message)
    return [{"t": "Link", "c": [content[0], content[1], [urls[page], ""]]}]


def to_jira(markdown: str, source: str, urls: Mapping[str, str]) -> str:
    """Convert Markdown to Jira wiki markup, with corpus links pointing at the site's pages."""
    document = json.loads(pypandoc.convert_text(markdown, "json", format="gfm-task_lists"))
    rewritten = walk(document, partial(jira_node, source=source, urls=urls))
    return pypandoc.convert_text(json.dumps(rewritten), "jira", format="json")


def ticket_rows(
    tickets: Sequence[Ticket],
    sprint_ids: Mapping[int, str],
    account: tuple[str, ZoneInfo],
    urls: Mapping[str, str],
) -> list[list[str]]:
    """Lay out tickets as rows of Jira's CSV importer, after a header row.

    Keys and parents go by number; labels and comments take one column each, under
    repeated headers, and a comment reads ``date;account id;text``. Dates are written in
    the importing account's time zone.
    """
    account_id, zone = account
    labels = max((len(ticket.labels) for ticket in tickets), default=0)
    comments = max((len(ticket.comments) for ticket in tickets), default=0)
    rows = [
        [
            *("Work Item Key", "Work item ID", "Parent", "Summary", "Work Type", "Status"),
            *("Resolution", "Priority", "Date Created", "Date Resolved", "Sprint", "Description"),
            *["Labels"] * labels,
            *["Comment"] * comments,
        ]
    ]
    for ticket in tickets:
        line = timeline(ticket)
        status, resolution = ticket.jira_status
        notes = [
            f"{date.astimezone(zone).strftime(CSV_DATE)};{account_id};{text}"
            for date, text in zip(line.comments, ticket.comments, strict=True)
        ]
        rows.append(
            [
                ticket.key,
                ticket.key.removeprefix(f"{TICKET_PROJECT}-"),
                (ticket.parent or "").removeprefix(f"{TICKET_PROJECT}-"),
                ticket.summary,
                ticket.type,
                status,
                resolution or "",
                ticket.priority,
                line.created.astimezone(zone).strftime(CSV_DATE),
                line.resolved.astimezone(zone).strftime(CSV_DATE) if line.resolved else "",
                sprint_ids[line.sprint] if line.sprint else "",
                to_jira(ticket.markdown, ticket.source, urls),
                *ticket.labels,
                *[""] * (labels - len(ticket.labels)),
                *notes,
                *[""] * (comments - len(notes)),
            ]
        )
    return rows


def decide(title: str, parent_id: str | None, digest: str, live: LivePage | None) -> Action:
    """Decide what seeding does to a page, given what the site holds for it."""
    if live is None:
        return "create"
    written = live.source or {}
    if (live.title, live.parent_id, live.version, digest) != (
        title,
        parent_id,
        written.get("version"),
        written.get("sha256"),
    ):
        return "update"
    return "leave"


def call(client: httpx.Client, method: str, path: str, **options: object) -> dict:
    """Make one request, and return its JSON body; any HTTP error stops the run."""
    response = client.request(method, path, **options)
    if response.is_error:
        message = f"{method} {path}: {response.status_code} {response.text[:500]}"
        raise RuntimeError(message)
    return response.json() if response.content else {}


def space(client: httpx.Client, *, create: bool) -> dict | None:
    """Return the corpus's space; if it is absent, create it when asked, else return None."""
    found = call(client, "GET", "/wiki/api/v2/spaces", params={"keys": SPACE_KEY})["results"]
    if found or not create:
        return found[0] if found else None
    return call(client, "POST", "/wiki/api/v2/spaces", json={"key": SPACE_KEY, "name": SPACE_NAME})


def read_live(client: httpx.Client, space_id: str) -> list[LivePage]:
    """List the space's pages with the seeding property of each."""
    pages: list[dict] = []
    path: str | None = f"/wiki/api/v2/spaces/{space_id}/pages"
    params: dict[str, object] | None = {"limit": 250}
    for _ in range(MAX_LISTING_PAGES):
        if path is None:
            break
        listed = call(client, "GET", path, params=params)
        pages.extend(listed["results"])
        path, params = listed.get("_links", {}).get("next"), None
    else:
        message = f"more than {MAX_LISTING_PAGES} listing pages in the space"
        raise RuntimeError(message)
    live = []
    for page in pages:
        properties = call(
            client,
            "GET",
            f"/wiki/api/v2/pages/{page['id']}/properties",
            params={"key": PROPERTY_KEY},
        )["results"]
        found = properties[0] if properties else None
        live.append(
            LivePage(
                id=str(page["id"]),
                title=page["title"],
                parent_id=str(page["parentId"]) if page.get("parentId") else None,
                version=page["version"]["number"],
                source=found["value"] if found else None,
                property_id=str(found["id"]) if found else None,
                property_version=found["version"]["number"] if found else None,
            )
        )
    return live


def match(pages: Mapping[str, Page], live: Sequence[LivePage], home_id: str) -> dict[str, LivePage]:
    """Match each corpus page to a site page: by the key it carries, then by title.

    The corpus's home page is the space's home page, whatever its title.
    """
    by_key = {str(page.source.get("key")): page for page in live if page.source}
    home = next((page for page in live if page.id == home_id), None)
    by_title = {page.title: page for page in live}
    matched = {}
    for key, page in pages.items():
        found = by_key.get(key) or (home if key == "index" else by_title.get(page.title))
        if found is not None:
            matched[key] = found
    return matched


def write_page(
    client: httpx.Client, space_id: str, page: Page, write: tuple[str, str | None, LivePage | None]
) -> str:
    """Create or update a page, then record what was written in its property; return its id."""
    storage, parent_id, live = write
    body = {
        "status": "current",
        "title": page.title,
        "body": {"representation": "storage", "value": storage},
    }
    if parent_id is not None:
        body["parentId"] = parent_id
    if live is None:
        written = call(client, "POST", "/wiki/api/v2/pages", json={"spaceId": space_id, **body})
    else:
        version = {"number": live.version + 1, "message": "Seeded from the corpus"}
        written = call(
            client,
            "PUT",
            f"/wiki/api/v2/pages/{live.id}",
            json={"id": live.id, **body, "version": version},
        )
    page_id = str(written["id"])
    value = {
        "key": page.key,
        "sha256": hashlib.sha256(storage.encode()).hexdigest(),
        "version": written["version"]["number"],
        "pandoc": pypandoc.get_pandoc_version(),
    }
    if live is None or live.property_id is None:
        call(
            client,
            "POST",
            f"/wiki/api/v2/pages/{page_id}/properties",
            json={"key": PROPERTY_KEY, "value": value},
        )
    else:
        call(
            client,
            "PUT",
            f"/wiki/api/v2/pages/{page_id}/properties/{live.property_id}",
            json={
                "key": PROPERTY_KEY,
                "value": value,
                "version": {"number": (live.property_version or 0) + 1},
            },
        )
    return page_id


class LinkTargets(HTMLParser):
    """Collect the ids of pages that a rendered body links to, and whether it shows an error."""

    def __init__(self) -> None:
        """Start with no link and no error."""
        super().__init__()
        self.ids: set[str] = set()
        self.error = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record a page link's target, or an element of class ``error``."""
        attributes = dict(attrs)
        if tag == "a" and attributes.get("data-linked-resource-type") == "page":
            self.ids.add(str(attributes.get("data-linked-resource-id")))
        if "error" in (attributes.get("class") or "").split():
            self.error = True


def seed_pages(
    client: httpx.Client, pages: Mapping[str, Page], *, check: bool
) -> tuple[list[str], dict[str, str]]:
    """Bring the space in line with the corpus, or only compare them.

    Return the problems found, and the id of each corpus page on the site.
    """
    corpus_space = space(client, create=not check)
    if corpus_space is None:
        return [f"space {SPACE_KEY} is absent"], {}
    space_id = str(corpus_space["id"])
    live = read_live(client, space_id)
    matched = match(pages, live, str(corpus_space["homepageId"]))
    titles = {key: page.title for key, page in pages.items()}
    ids = {key: page.id for key, page in matched.items()}
    problems, counts, links = [], dict.fromkeys(("create", "update", "leave"), 0), {}
    # Parents come before their children: the home page, then section pages, then the rest.
    for key in sorted(pages, key=lambda key: (key != "index", not key.endswith("index"), key)):
        page = pages[key]
        storage, links[key] = to_storage(page, titles)
        parent_id = ids.get(page.parent) if page.parent else None
        digest = hashlib.sha256(storage.encode()).hexdigest()
        action = decide(page.title, parent_id, digest, matched.get(key))
        counts[action] += 1
        if check and action != "leave":
            # The hash is of pandoc's output: another pandoc version may write other HTML.
            pandoc = (matched[key].source or {}).get("pandoc") if key in matched else None
            local = pypandoc.get_pandoc_version()
            differs = pandoc and pandoc != local
            cause = f", written with pandoc {pandoc}, here {local}" if differs else ""
            problems.append(f"page {key}: would {action}{cause}")
        elif action != "leave":
            sys.stdout.write(f"{action} page {key}\n")
            sys.stdout.flush()
            ids[key] = write_page(client, space_id, page, (storage, parent_id, matched.get(key)))
    named = set(ids.values())
    problems += [
        f"page not in the corpus: {found.title}" for found in live if found.id not in named
    ]
    if check:
        problems += check_links(client, links, ids)
        listing = sorted((found.title, found.version) for found in matched.values())
        sys.stdout.writelines(f"page\t{version}\t{title}\n" for title, version in listing)
    done = "to create, {} to update" if check else "created, {} updated"
    sys.stdout.write(
        f"pages: {counts['create']} {done.format(counts['update'])}, {counts['leave']} unchanged\n"
    )
    return problems, ids


def check_links(
    client: httpx.Client, links: Mapping[str, frozenset[str]], ids: Mapping[str, str]
) -> list[str]:
    """Compare each page's rendered links with its source's, and look for macro errors."""
    problems = []
    for key, linked in sorted(links.items()):
        if key not in ids:
            continue
        view = call(
            client, "GET", f"/wiki/api/v2/pages/{ids[key]}", params={"body-format": "view"}
        )["body"]["view"]["value"]
        parser = LinkTargets()
        parser.feed(view)
        if parser.ids != {ids.get(target) for target in linked}:
            problems.append(f"page {key}: links differ from the source")
        if parser.error:
            problems.append(f"page {key}: shows an error")
    return problems


def seed_ideas(
    client: httpx.Client, ideas: Mapping[str, Idea], urls: Mapping[str, str], *, check: bool
) -> tuple[list[str], set[str]]:
    """Create or update the ideas, found by summary, or only compare them.

    Return the problems found, and the keys of the ideas that were on the site.
    """
    project = call(
        client, "GET", f"/rest/api/3/project/{IDEAS_PROJECT}", params={"expand": "issueTypes"}
    )
    if project.get("projectTypeKey") != "product_discovery":
        return [f"{IDEAS_PROJECT} is not a Jira Product Discovery project"], set()
    type_id = next(kind["id"] for kind in project["issueTypes"] if kind["name"] == "Idea")
    listed = call(
        client,
        "GET",
        "/rest/api/3/search/jql",
        params={
            "jql": f"project = {IDEAS_PROJECT} AND issuetype = {type_id}",
            "fields": "summary,updated",
            "properties": PROPERTY_KEY,
            "maxResults": 100,
        },
    )
    if listed.get("nextPageToken"):
        message = f"more than 100 ideas in {IDEAS_PROJECT}"
        raise RuntimeError(message)
    issues = {issue["fields"]["summary"]: issue for issue in listed["issues"]}
    summaries = {idea.summary for idea in ideas.values()}
    present = {idea.key for idea in ideas.values() if idea.summary in issues}
    # Search lags writes, so a run soon after another may create an idea twice.
    found = Counter(issue["fields"]["summary"] for issue in listed["issues"])
    problems = [
        f"idea {name!r} is in {IDEAS_PROJECT} {n} times"
        for name, n in found.items()
        if n > 1 and name in summaries
    ]
    counts = dict.fromkeys(("create", "update", "leave"), 0)
    for idea in ideas.values():
        description = to_jira(idea.markdown, idea.source, urls)
        value = {"key": idea.key, "sha256": hashlib.sha256(description.encode()).hexdigest()}
        issue = issues.get(idea.summary)
        unchanged = issue is not None and issue.get("properties", {}).get(PROPERTY_KEY) == value
        action = "leave" if unchanged else "update" if issue else "create"
        counts[action] += 1
        if check and action != "leave":
            problems.append(f"idea {idea.key}: would {action}")
        if check or action == "leave":
            continue
        fields = {"summary": idea.summary, "description": description}
        if issue is None:
            fields |= {"project": {"key": IDEAS_PROJECT}, "issuetype": {"id": type_id}}
            key = call(client, "POST", "/rest/api/2/issue", json={"fields": fields})["key"]
        else:
            key = issue["key"]
            call(client, "PUT", f"/rest/api/2/issue/{key}", json={"fields": fields})
        call(client, "PUT", f"/rest/api/3/issue/{key}/properties/{PROPERTY_KEY}", json=value)
    if check:
        sys.stdout.writelines(
            f"{'idea' if summary in summaries else 'other idea'}\t{issue['key']}"
            f"\t{issue['fields']['updated']}\t{summary}\n"
            for summary, issue in sorted(issues.items(), key=lambda item: item[1]["id"])
        )
    done = "to create, {} to update" if check else "created, {} updated"
    sys.stdout.write(
        f"ideas: {counts['create']} {done.format(counts['update'])}, {counts['leave']} unchanged\n"
    )
    return problems, present


def jira_time(moment: datetime) -> str:
    """Write a moment as Jira's Agile API reads dates."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def prepare_jira(client: httpx.Client, *, check: bool) -> tuple[list[str], dict[int, dict]]:
    """Create the project, its Kanban board and its sprints if absent, or only look for them.

    Return the problems found, and the sprints of the Scrum board by number.
    """
    account = call(client, "GET", "/rest/api/3/myself")["accountId"]
    if client.get(f"/rest/api/3/project/{TICKET_PROJECT}").status_code == httpx.codes.NOT_FOUND:
        if check:
            return [f"project {TICKET_PROJECT} is absent"], {}
        project = {"key": TICKET_PROJECT, "name": TICKET_PROJECT_NAME, "leadAccountId": account}
        project |= {"projectTypeKey": "software", "projectTemplateKey": SCRUM_TEMPLATE}
        call(client, "POST", "/rest/api/3/project", json=project)
    listed = call(client, "GET", "/rest/agile/1.0/board", params={"projectKeyOrId": TICKET_PROJECT})
    boards = {board["type"]: board["id"] for board in listed["values"]}
    problems = [] if "kanban" in boards or not check else ["the Kanban board is absent"]
    if "kanban" not in boards and not check:
        jql = f"project = {TICKET_PROJECT} ORDER BY Rank ASC"
        board_filter = {"name": f"{TICKET_PROJECT} Kanban board", "jql": jql}
        filter_id = call(client, "POST", "/rest/api/3/filter", json=board_filter)["id"]
        location = {"type": "project", "projectKeyOrId": TICKET_PROJECT}
        board = {"name": f"{TICKET_PROJECT} Kanban", "type": "kanban", "filterId": int(filter_id)}
        call(client, "POST", "/rest/agile/1.0/board", json=board | {"location": location})
    sprints: dict[int, dict] = {}
    for start in range(0, SPRINTS * 2, 50):
        page = call(
            client,
            "GET",
            f"/rest/agile/1.0/board/{boards['scrum']}/sprint",
            params={"startAt": start},
        )
        sprints |= {int(sprint["name"].rpartition(" ")[2]): sprint for sprint in page["values"]}
    for number in sorted(set(range(1, SPRINTS + 1)) - set(sprints)):
        if check:
            problems.append(f"sprint {number} is absent")
            continue
        # Jira keeps no dates on a future sprint; they are set when the sprint starts.
        planned = {"name": f"{TICKET_PROJECT} Sprint {number}", "originBoardId": boards["scrum"]}
        sprints[number] = call(client, "POST", "/rest/agile/1.0/sprint", json=planned)
    return problems, sprints


def read_issues(client: httpx.Client) -> tuple[dict[str, dict], str]:
    """List the project's tickets by key, with the id of the Sprint field they carry."""
    fields = call(client, "GET", "/rest/api/3/field")
    sprint_field = next(
        field["id"] for field in fields if field.get("schema", {}).get("custom") == SPRINT_FIELD
    )
    issues: dict[str, dict] = {}
    params = {
        "jql": f"project = {TICKET_PROJECT} ORDER BY key ASC",
        "fields": f"summary,status,resolution,resolutiondate,parent,created,updated,{sprint_field}",
        "maxResults": 100,
    }
    for _ in range(MAX_TICKET_PAGES):
        listed = call(client, "GET", "/rest/api/3/search/jql", params=params)
        issues |= {issue["key"]: issue for issue in listed["issues"]}
        if not listed.get("nextPageToken"):
            return issues, sprint_field
        params["nextPageToken"] = listed["nextPageToken"]
    message = f"more than {MAX_TICKET_PAGES} pages of tickets in {TICKET_PROJECT}"
    raise RuntimeError(message)


def compare_tickets(
    tickets: Sequence[Ticket],
    issues: Mapping[str, dict],
    sprint_field: str,
    sprints: Mapping[int, dict],
) -> list[str]:
    """Compare each ticket with the issue of its key.

    Summary, status, resolution, parent, creation and resolution dates, and sprint.
    """
    problems = []
    for ticket in tickets:
        issue = issues.get(ticket.key)
        if issue is None:
            problems.append(f"ticket {ticket.key} is absent")
            continue
        fields, line = issue["fields"], timeline(ticket)
        dates = [
            datetime.strptime(fields[name], JIRA_DATE).astimezone(UTC) if fields[name] else None
            for name in ("created", "resolutiondate")
        ]
        found = (
            fields["summary"],
            fields["status"]["name"],
            (fields.get("resolution") or {}).get("name"),
            (fields.get("parent") or {}).get("key"),
            *dates,
            {sprint["id"] for sprint in fields.get(sprint_field) or []},
        )
        expected = (
            ticket.summary,
            *ticket.jira_status,
            ticket.parent,
            line.created,
            line.resolved,
            {sprints[line.sprint]["id"]} if line.sprint else set(),
        )
        if found != expected:
            problems.append(f"ticket {ticket.key} differs from its data")
    return problems


def compare_sprints(sprints: Mapping[int, dict]) -> list[str]:
    """Compare each sprint with the calendar: closed but the last, which is active."""
    problems = []
    for number in range(1, SPRINTS + 1):
        sprint = sprints[number]
        state = "active" if number == SPRINTS else "closed"
        dates = [
            datetime.fromisoformat(sprint[name]) if name in sprint else None
            for name in ("startDate", "endDate")
        ]
        if sprint["state"] != state or dates != [sprint_start(number), sprint_start(number + 1)]:
            problems.append(f"sprint {number} differs from the calendar")
    return problems


def advance_sprints(client: httpx.Client, sprints: Mapping[int, dict]) -> None:
    """Start and close each sprint in order, so that only the last one stays active."""
    for number in range(1, SPRINTS + 1):
        state = sprints[number]["state"]
        path = f"/rest/agile/1.0/sprint/{sprints[number]['id']}"
        if state == "future":
            dates = {"startDate": jira_time(sprint_start(number))}
            dates |= {"endDate": jira_time(sprint_start(number + 1))}
            call(client, "POST", path, json={"state": "active", **dates})
        if state != "closed" and number < SPRINTS:
            call(client, "POST", path, json={"state": "closed"})


def seed_tickets(
    client: httpx.Client,
    tickets: Sequence[Ticket],
    urls: Mapping[str, str],
    import_file: Path | None,
    *,
    check: bool,
) -> tuple[list[str], set[str]]:
    """Prepare the project, write the import file of absent tickets, then run the sprints.

    With check, write nothing and compare the project with the ticket data. Return the
    problems found, and the keys of the tickets that were on the site.
    """
    problems, sprints = prepare_jira(client, check=check)
    if problems or len(sprints) < SPRINTS:
        return problems, set()
    issues, sprint_field = read_issues(client)
    absent = [ticket for ticket in tickets if ticket.key not in issues]
    if check:
        sys.stdout.writelines(
            f"ticket\t{key}\t{issue['fields']['updated']}\n" for key, issue in issues.items()
        )
        problems = compare_sprints(sprints) + compare_tickets(
            tickets, issues, sprint_field, sprints
        )
        return problems, set(issues)
    if not absent:
        advance_sprints(client, sprints)
        return [], set(issues)
    if import_file is None:
        note = f"{len(absent)} tickets are absent: pass --import-file to write them for import"
        return [note], set(issues)
    myself = call(client, "GET", "/rest/api/3/myself")
    account = (myself["accountId"], ZoneInfo(myself["timeZone"]))
    sprint_ids = {number: str(sprint["id"]) for number, sprint in sprints.items()}
    with import_file.open("w", newline="", encoding="utf-8") as file:
        csv.writer(file).writerows(ticket_rows(absent, sprint_ids, account, urls))
    note = f"{len(absent)} tickets written to {import_file}: import them, then run again"
    return [note], set(issues)


def main(argv: Sequence[str] | None = None) -> int:
    """Seed the sandbox, or check it with --check; exit 1 if a check fails."""
    parser = argparse.ArgumentParser(description="Seed the sandbox with the corpus, or check it.")
    parser.add_argument("--check", action="store_true", help="write nothing; compare the site")
    parser.add_argument(
        "--import-file", type=Path, help="where to write the CSV of tickets absent from Jira"
    )
    arguments = parser.parse_args(argv)
    site = urlsplit(os.environ["ATLASSIAN_SITE"])
    if site.scheme != "https" or not site.netloc.endswith(".atlassian.net"):
        parser.error("ATLASSIAN_SITE must be an https://<name>.atlassian.net address")
    auth = (os.environ["ATLASSIAN_EMAIL"], os.environ["ATLASSIAN_API_TOKEN"])
    pages, ideas, tickets = read_corpus(), read_ideas(), read_tickets()
    with httpx.Client(
        base_url=f"https://{site.netloc}", auth=auth, timeout=HTTP_TIMEOUT_S
    ) as client:
        problems, ids = seed_pages(client, pages, check=arguments.check)
        urls = {
            key: f"https://{site.netloc}/wiki/spaces/{SPACE_KEY}/pages/{page_id}"
            for key, page_id in ids.items()
        }
        if set(pages) - set(ids):
            problems.append("ideas and tickets not checked: some pages are not on the site")
        else:
            idea_problems, idea_keys = seed_ideas(client, ideas, urls, check=arguments.check)
            ticket_problems, ticket_keys = seed_tickets(
                client, tickets, urls, arguments.import_file, check=arguments.check
            )
            problems += idea_problems + ticket_problems
            on_site = set(ids) | idea_keys | ticket_keys
            problems += [
                f"golden question {question.id} names {key}, which is not on the site"
                for question in (read_golden() if arguments.check else [])
                for key in sorted(question.documents - on_site)
            ]
    label = "PROBLEM" if arguments.check else "NOTE"
    sys.stdout.writelines(f"{label} {problem}\n" for problem in problems)
    return 1 if arguments.check and problems else 0


if __name__ == "__main__":
    sys.exit(main())
