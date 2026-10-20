# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "defusedxml>=0.7,<1", "httpx>=0.28,<1", "pypandoc>=1.13,<2", "pyyaml>=6,<7",
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
import hashlib
import html
import json
import os
import posixpath
import sys
from dataclasses import dataclass
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

import httpx
import pypandoc
import yaml
from defusedxml import ElementTree

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

SPACE_KEY = "QM"
# Storage-format XHTML uses these namespaces; parsing it needs them declared.
NAMESPACES = 'xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource"'
SPACE_NAME = "Quillmoor handbook"
PROPERTY_KEY = "corpus-source"
CORPUS = Path(__file__).parent / "corpus"
HTTP_TIMEOUT_S = 30
# A bound on cursor-paged listings: 20 pages of 250 results.
MAX_LISTING_PAGES = 20
# Languages of fenced code blocks; "text" becomes a code macro without a language.
CODE_LANGUAGES = frozenset({"bash", "python", "sql", "yaml", "json", "go", "typescript", "text"})
# GitHub alerts, as pandoc reads them, to the Confluence panel macros that show them.
PANELS = {"note": "info", "tip": "tip", "important": "note", "warning": "warning"}
PANELS["caution"] = "warning"

Action = Literal["create", "update", "leave"]


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


def cdata(text: str) -> str:
    """Wrap a text in CDATA, splitting any ``]]>`` it holds."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def raw(kind: str, markup: str) -> dict:
    """Make a pandoc node of raw HTML, of kind RawBlock or RawInline."""
    return {"t": kind, "c": ["html", markup]}


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
        return [
            raw(
                "RawBlock",
                f'<ac:structured-macro ac:name="code">{parameter if language != "text" else ""}'
                f"<ac:plain-text-body>{cdata(code)}</ac:plain-text-body></ac:structured-macro>",
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


def seed_pages(client: httpx.Client, pages: Mapping[str, Page], *, check: bool) -> list[str]:
    """Bring the space in line with the corpus, or only compare them; return the problems."""
    found = space(client, create=not check)
    if found is None:
        return [f"space {SPACE_KEY} is absent"]
    space_id = str(found["id"])
    live = read_live(client, space_id)
    matched = match(pages, live, str(found["homepageId"]))
    titles = {key: page.title for key, page in pages.items()}
    ids = {key: found.id for key, found in matched.items()}
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
            problems.append(f"page {key}: would {action}")
        elif action != "leave":
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
    return problems


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


def main(argv: Sequence[str] | None = None) -> int:
    """Seed the sandbox, or check it with --check; exit 1 if a check fails."""
    parser = argparse.ArgumentParser(description="Seed the sandbox with the corpus, or check it.")
    parser.add_argument("--check", action="store_true", help="write nothing; compare the site")
    arguments = parser.parse_args(argv)
    site = urlsplit(os.environ["ATLASSIAN_SITE"])
    if site.scheme != "https" or not site.netloc.endswith(".atlassian.net"):
        parser.error("ATLASSIAN_SITE must be an https://<name>.atlassian.net address")
    auth = (os.environ["ATLASSIAN_EMAIL"], os.environ["ATLASSIAN_API_TOKEN"])
    pages = read_corpus()
    with httpx.Client(
        base_url=f"https://{site.netloc}", auth=auth, timeout=HTTP_TIMEOUT_S
    ) as client:
        problems = seed_pages(client, pages, check=arguments.check)
    for problem in problems:
        sys.stdout.write(f"PROBLEM {problem}\n")
    return 1 if arguments.check and problems else 0


if __name__ == "__main__":
    sys.exit(main())
