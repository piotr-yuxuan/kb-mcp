# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "certifi>=2024.2",
#     "httpx>=0.28,<1",
#     "pillow>=13,<14",
#     "playwright>=1.64,<2",
#     "truststore>=0.10,<1",
# ]
# ///
"""Probe whether Atlassian Cloud can be read through REST with a browser session.

You sign in once, in a Chrome window that Playwright opens with a dedicated profile.
The probe then makes the same read-only GET requests in three ways: ``fetch`` inside
the signed-in page, Playwright's request context, and httpx with the session's
cookies. For each page given, it compares what REST returns with what the browser
renders.

The report holds only fixed check names, labels such as ``page-1``, built-in macro
names, numbers, media types and exception class names: never a title, text, URL,
identifier, cookie or exception message. See ``spikes/README.md``.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode, urljoin, urlsplit

import certifi
import httpx
import truststore
from PIL import Image, UnidentifiedImageError
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from playwright.sync_api import BrowserContext, Page

SIGN_IN_TIMEOUT_S = 300
SIGN_IN_POLL_MS = 2_000
SETTLE_TIMEOUT_S = 60
SETTLE_POLL_MS = 1_000
STABLE_POLLS = 3
SCROLL_PAUSE_MS = 150
MAX_SCROLL_STEPS = 200
HTTP_TIMEOUT_S = 30
MAX_BODY_BYTES = 25 * 1024 * 1024
MAX_PAGES = 3
MAX_IMAGES_PER_PAGE = 10
MAX_QUERY_RESULTS = 50
COMPARED_RESULTS = 20
# The page properties report's "Number of items to display", when the macro sets none.
REPORT_ROWS = 30
MAX_OPEN_PASSES = 5
WORD_COVERAGE = 0.98
MIN_IMAGE_SIDE = 32
# The pixel size given to an SVG, which scales to any size and has no pixels to compare.
VECTOR = (0, 0)
HTTP_OK = 200
JSON = "application/json"
# Media types the report may name; a server could put any text in a Content-Type.
KNOWN_MEDIA_TYPES = frozenset(
    {JSON, "text/html", "text/plain", "application/octet-stream", "image/png", "image/jpeg",
     "image/gif", "image/webp", "image/svg+xml", "image/bmp", "image/tiff"}
)  # fmt: skip
COOKIES_FILE = "probe-cookies.json"

# Confluence Cloud's own macros. Any other name, a third-party app's for example, is
# reported as custom-N, since it can reveal which apps a company uses.
BUILT_IN_MACROS = frozenset(
    {
        "anchor", "attachments", "blog-posts", "chart", "children", "code", "column",
        "content-report-table", "contentbylabel", "create-from-template", "details",
        "detailssummary", "excerpt", "excerpt-include", "expand", "gallery", "include",
        "info", "jira", "jiraissues", "listlabels", "livesearch", "multimedia",
        "noformat", "note", "page-index", "pagetree", "panel", "popular-labels",
        "profile", "recently-updated", "roadmap", "section", "status",
        "tasks-report-macro", "tip", "toc", "toc-zone", "view-file", "viewpdf",
        "warning", "widget",
        # Not macros: Smart Link lists, of Jira issues (which /jira now inserts) or other.
        "jira-datasource", "smart-link-list",
    }
)  # fmt: skip
# (macro, parameter) pairs whose text is a query that a dynamic macro runs.
QUERY_PARAMETERS = {
    ("jira", "jqlQuery"): "jql",
    ("jira", "key"): "key",
    ("detailssummary", "cql"): "cql",
}
# A Smart Link table of Jira issues, which /jira inserts since April 2026, and a Smart
# Link list of anything else. They are no macros, but the report names them as such.
DATASOURCE = "jira-datasource"
OTHER_DATASOURCE = "smart-link-list"
# Tables drawn from a query, compared by query and not word by word, each with where the
# browser draws it. A macro joins only once its browser selector has been observed. The
# classic jira macro is compared word by word: since April 2026 it renders an error
# unless it points at a Data Center site, and its browser rendering is unobserved.
DYNAMIC_TABLES = {
    DATASOURCE: "[data-testid='renderer-datasource-table']",
    # The innermost such table: a layout table around the report is not the report.
    "detailssummary": (
        "table:has([data-testid='page-properties-report-table-head'])"
        ":not(:has(table [data-testid='page-properties-report-table-head']))"
    ),
}
# Hosts that serve a page's attachments to the browser, besides the site itself.
MEDIA_HOSTS = ("media.atlassian.com", "media-cdn.atlassian.com")
# An excerpt include: its header (the source's title, "Untitled excerpt") is interface,
# and its body is the included page's own renderer document.
EXCERPT_INCLUDE = "[data-testid='excerpt-include-component']"
# Macros that show another page's content: the macros inside them are that page's own.
INCLUDING = frozenset({"include", "excerpt-include"})
# The toggle of a collapsed expand, whose body is hidden until opened.
EXPAND_TOGGLES = (
    "[data-node-type='expand'] > button[aria-expanded='false'],"
    " [data-node-type='nestedExpand'] > button[aria-expanded='false']"
)
VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
     "source", "track", "wbr"}
)  # fmt: skip
WORD = re.compile(r"\w+")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-[0-9]+")
PAGE_ID = re.compile(r"[0-9]+")
# A Confluence attachment id, with or without its prefix, or a Jira attachment id.
ATTACHMENT_ID = re.compile(r"(att)?[0-9]+")

# Fetches a URL from inside the page, so the browser itself carries the session. The
# default credentials mode, same-origin, sends the cookies to the site, and none on the
# redirect of a download to Atlassian's media host, which takes its token in the URL.
FETCH_JS = """async ([url, timeout]) => {
  const response = await fetch(url, {signal: AbortSignal.timeout(timeout)});
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  for (let start = 0; start < bytes.length; start += 32768) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 32768));
  }
  return {status: response.status, type: response.headers.get("content-type") || "",
          body: btoa(binary)};
}"""

# A page's content area: the first of these selectors found, in order of preference.
CONTENT_SELECTORS = (
    ".ak-renderer-document",
    "#main-content",
    "[data-testid='page-content-only']",
    "main",
)

# Reads the content area. Its text is that of visible text nodes outside controls (an
# image's "Open" button, a table's sort button) and outside excerpt include headers.
# Each dynamic table's text is kept apart, in document order, and its images are its
# own (avatars, issue-type icons), as emoji are not the page's. An image served by a host
# other than the site's or Atlassian's media hosts, or inline as data, is external: the
# mirror links to it and never downloads it.
CONTENT_JS = """([selectors, dynamicSelectors, mediaHosts, excerptInclude, toggles, minimum]) => {
  const controls = "button, [role='button'], [role='toolbar'], [aria-hidden='true']";
  const dynamic = dynamicSelectors.join(", ");
  const header = (element) => {
    const include = element.closest(excerptInclude);
    return include !== null && !include.contains(element.closest(".ak-renderer-document"));
  };
  const local = (image) => {
    const url = new URL(image.currentSrc || image.src, location.href);
    if (url.protocol === "blob:") return true;
    return url.protocol.startsWith("http") && (url.host === location.host
      || mediaHosts.some((host) => url.host === host || url.host.endsWith(`.${host}`)));
  };
  for (const selector of selectors) {
    const area = document.querySelector(selector);
    if (area) {
      const walker = document.createTreeWalker(area, NodeFilter.SHOW_TEXT);
      const parts = [];
      const regionParts = new Map();
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const parent = node.parentElement;
        if (!parent || !parent.checkVisibility() || parent.closest(controls) || header(parent)) {
          continue;
        }
        const region = parent.closest(dynamic);
        if (region) {
          regionParts.set(region, [...(regionParts.get(region) || []), node.textContent]);
        } else {
          parts.push(node.textContent);
        }
      }
      const regionTexts = dynamicSelectors.map((tableSelector) =>
        [...area.querySelectorAll(tableSelector)]
          .map((region) => (regionParts.get(region) || []).join(" ")));
      const shown = [...area.querySelectorAll("img")]
        .filter((image) => !image.closest(dynamic) && !image.closest("[data-emoji-id]"))
        .filter((image) => image.naturalWidth > minimum && image.naturalHeight > minimum);
      const kept = shown.filter(local);
      return {text: parts.join(" "), dynamic: regionTexts.flat().join(" "), regionTexts,
              regions: area.querySelectorAll(dynamic).length,
              collapsed: area.querySelectorAll(toggles).length,
              tables: area.querySelectorAll("table").length,
              images: kept.map((image) => [image.naturalWidth, image.naturalHeight]),
              external: shown.length - kept.length};
    }
  }
  return null;
}"""

# Opens the collapsed expands, a toggle in the browser alone, in passes until none is
# left: a nested expand is rebuilt, collapsed, when its parent opens. Then scrolls
# through the content area half a screen at a time and back to the top: the renderer
# fetches an image only once it nears the viewport. Returns the toggles it clicked.
SCROLL_JS = """async ([selectors, toggles, pause, steps, passes]) => {
  const area = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  if (!area) return 0;
  const wait = () => new Promise((resolve) => setTimeout(resolve, pause));
  let clicked = 0;
  for (let pass = 0; pass < passes; pass += 1) {
    const closed = [...area.querySelectorAll(toggles)];
    if (closed.length === 0) break;
    for (const toggle of closed) toggle.click();
    clicked += closed.length;
    await wait();
    await wait();
  }
  let box = area;
  while (box && box !== document.body && !(box.scrollHeight > box.clientHeight
         && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) {
    box = box.parentElement;
  }
  const scroller = box && box !== document.body ? box : document.scrollingElement;
  let taken = 0;
  const step = scroller.clientHeight / 2;
  for (let top = 0; top < scroller.scrollHeight && taken < steps; top += step) {
    scroller.scrollTo(0, top);
    taken += 1;
    await wait();
  }
  scroller.scrollTo(0, 0);
  return clicked;
}"""


@dataclass(frozen=True)
class Reply:
    """What a carrier observed for one GET request; it never holds the URL."""

    status: int
    media_type: str
    body: bytes
    elapsed_ms: int


@dataclass(frozen=True)
class Check:
    """One line of the report: a fixed name, a verdict and content-free detail."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Query:
    """A dynamic table's query, read from the storage format: jql, key or cql."""

    kind: str
    text: str
    macro: str
    # How many results its table shows at once, and its place among its macro's tables.
    rows: int = COMPARED_RESULTS
    ordinal: int = 0


@dataclass(frozen=True)
class Rendered:
    """What the browser shows in a page's content area once it stops changing."""

    text: str
    tables: int
    images: tuple[tuple[int, int], ...]
    external_images: int = 0
    # The text of the dynamic tables, apart from the rest, and how many tables there are.
    dynamic_text: str = ""
    regions: int = 0
    # Each dynamic table's text, by macro, in document order.
    dynamic_tables: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Expand toggles the probe clicked, and expands still collapsed at the end.
    opened: int = 0
    collapsed: int = 0


@dataclass(frozen=True)
class ImageRef:
    """An image of a rendered body: an attachment, an external image, or unmapped."""

    kind: str
    container: str = ""
    attachment: str = ""


@dataclass
class MacroOutput:
    """What a macro wrapper of a rendered body has held so far.

    A wrapper inside an include is the included page's, so it is not counted, and has
    no place among the page's own wrappers of its name.
    """

    name: str
    counted: bool
    position: int
    text: list[str] = field(default_factory=list)
    seen: bool = False


@dataclass(frozen=True)
class MacroUse:
    """One macro of a storage-format body, with the text of its body."""

    name: str
    text: str


type Get = Callable[[str], Reply]


class StorageScanner(HTMLParser):
    """Counts the macros of a storage-format body and reads their queries."""

    def __init__(self) -> None:
        """Start with no macro seen."""
        super().__init__(convert_charrefs=True)
        self.uses: list[MacroUse] = []
        self.queries: list[Query] = []
        # Each open macro: its name, the text of its body so far, and its parameters.
        self._open_macros: list[tuple[str, list[str], dict[str, str]]] = []
        self._parameter: str | None = None
        self._parameter_text: list[str] = []

    @classmethod
    def parse(cls, storage: str) -> StorageScanner:
        """Scan a whole storage-format body."""
        scanner = cls()
        scanner.feed(storage)
        scanner.close()
        return scanner

    @property
    def macros(self) -> Counter[str]:
        """How many macros of each name the body holds, nested ones included."""
        return Counter(use.name for use in self.uses)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open a macro, start reading one of its parameters, or read a Jira table's JQL."""
        attributes = dict(attrs)
        if tag == "ac:structured-macro":
            self._open_macros.append((attributes.get("ac:name") or "", [], {}))
        elif tag == "ac:parameter" and self._open_macros:
            self._parameter = attributes.get("ac:name")
            self._parameter_text = []
        elif tag == "a" and attributes.get("data-datasource"):
            # A Smart Link list: a table of Jira issues when its JSON parameters hold JQL.
            try:
                jql = json.loads(attributes["data-datasource"] or "")["parameters"]["jql"]
            except (ValueError, KeyError, TypeError):
                jql = None
            if isinstance(jql, str):
                self.uses.append(MacroUse(DATASOURCE, ""))
                self._add_query("jql", jql, DATASOURCE, COMPARED_RESULTS)
            else:
                self.uses.append(MacroUse(OTHER_DATASOURCE, ""))

    def handle_endtag(self, tag: str) -> None:
        """Close a macro and keep its queries, or keep a parameter's text."""
        if tag == "ac:structured-macro" and self._open_macros:
            name, text, parameters = self._open_macros.pop()
            self.uses.append(MacroUse(name, " ".join(text)))
            size = parameters.get("pageSize", "")
            rows = int(size) if PAGE_ID.fullmatch(size) else REPORT_ROWS
            for (macro, parameter), kind in QUERY_PARAMETERS.items():
                if macro == name and parameter in parameters:
                    shows = rows if name == "detailssummary" else COMPARED_RESULTS
                    self._add_query(kind, parameters[parameter], name, shows)
        elif tag == "ac:parameter" and self._parameter is not None and self._open_macros:
            self._open_macros[-1][2][self._parameter] = "".join(self._parameter_text).strip()
            self._parameter = None

    def handle_data(self, data: str) -> None:
        """Collect a parameter's text, or the body text of every open macro."""
        if self._parameter is not None:
            self._parameter_text.append(data)
            return
        for _, text, _ in self._open_macros:
            text.append(data)

    def _add_query(self, kind: str, text: str, macro: str, rows: int) -> None:
        ordinal = sum(1 for query in self.queries if query.macro == macro)
        self.queries.append(Query(kind, text, macro, rows, ordinal))


class ViewScanner(HTMLParser):
    """Reads the text, tables, images and macro output of a server-rendered body."""

    def __init__(self) -> None:
        """Start with an empty body."""
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        # The text outside dynamic tables, which are compared by query instead.
        self.static_parts: list[str] = []
        self.tables = 0
        self.images: list[ImageRef] = []
        self.macros_with_output: Counter[str] = Counter()
        # The text of each of the page's own wrappers, by macro name, in document order.
        self.macro_outputs: defaultdict[str, list[str]] = defaultdict(list)
        # Each open element: its tag, and for a macro wrapper what it holds so far.
        self._open: list[tuple[str, MacroOutput | None]] = []
        self._skipped = 0

    @classmethod
    def parse(cls, view: str) -> ViewScanner:
        """Scan a whole rendered body."""
        scanner = cls()
        scanner.feed(view)
        scanner.close()
        return scanner

    @property
    def text(self) -> str:
        """The visible text of the body."""
        return " ".join(self.text_parts)

    @property
    def static_text(self) -> str:
        """The visible text outside dynamic tables."""
        return " ".join(self.static_parts)

    @property
    def local_images(self) -> list[ImageRef]:
        """The images that REST should serve: attachments, and those it cannot map."""
        return [image for image in self.images if image.kind != "external"]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Count tables and images, and open elements and macro wrappers."""
        attributes = dict(attrs)
        classes = attributes.get("class") or ""
        linked = attributes.get("data-linked-resource-type") == "attachment"
        # An icon declares a small size, as the browser's count leaves icons out; an
        # attachment is downloaded at full size, so it is never taken for one.
        icon = not linked and all(
            PAGE_ID.fullmatch(attributes.get(side) or "")
            and int(attributes.get(side) or 0) <= MIN_IMAGE_SIDE
            for side in ("width", "height")
        )
        if tag == "table":
            self.tables += 1
        elif tag == "img" and "emoticon" not in classes and not icon and not self._dynamic():
            self._mark_output()
            container = attributes.get("data-linked-resource-container-id") or ""
            attachment = attributes.get("data-linked-resource-id") or ""
            # Ids go into request paths, so only well-formed ones are used.
            if linked and PAGE_ID.fullmatch(container) and ATTACHMENT_ID.fullmatch(attachment):
                self.images.append(ImageRef("attachment", container, attachment))
            elif "confluence-external-resource" in classes:
                self.images.append(ImageRef("external"))
            else:
                self.images.append(ImageRef("unmapped"))
        elif tag in {"script", "style"}:
            self._skipped += 1
        if tag not in VOID_ELEMENTS:
            # A Smart Link table is rendered as a plain table, without a macro wrapper.
            datasource = tag == "table" and "jiraWorkItemMacroListViewTable" in classes
            name = DATASOURCE if datasource else attributes.get("data-macro-name")
            included = any(outer and outer.name in INCLUDING for _, outer in self._open)
            if name and not included:
                self.macro_outputs[name].append("")
            position = len(self.macro_outputs[name]) - 1 if name else -1
            macro = MacroOutput(name, not included, position) if name else None
            self._open.append((tag, macro))

    def handle_endtag(self, tag: str) -> None:
        """Close the matching element, and any left open inside it."""
        if tag in {"script", "style"} and self._skipped:
            self._skipped -= 1
        if all(open_tag != tag for open_tag, _ in self._open):
            return
        while self._open:
            if self._close_innermost() == tag:
                return

    def handle_data(self, data: str) -> None:
        """Keep visible text, which also counts as output of every open macro."""
        if self._skipped or not data.strip():
            return
        self.text_parts.append(data)
        if not self._dynamic():
            self.static_parts.append(data)
        self._mark_output(data)

    def close(self) -> None:
        """Finish the body, closing the elements it left open."""
        super().close()
        while self._open:
            self._close_innermost()

    def _dynamic(self) -> bool:
        return any(macro and macro.name in DYNAMIC_TABLES for _, macro in self._open)

    def _mark_output(self, text: str = "") -> None:
        for _, macro in self._open:
            if macro is not None:
                macro.seen = True
                macro.text.append(text)

    def _close_innermost(self) -> str:
        tag, macro = self._open.pop()
        if macro is not None and macro.seen and macro.counted:
            self.macros_with_output[macro.name] += 1
            self.macro_outputs[macro.name][macro.position] = " ".join(macro.text)
        return tag


@dataclass(frozen=True)
class PageEvidence:
    """Everything gathered about one page, over REST and in the browser."""

    storage: StorageScanner
    view: ViewScanner
    rendered: Rendered | None
    rest_images: tuple[tuple[int, int] | None, ...]
    results: tuple[tuple[Query, tuple[str, ...] | None], ...]
    rest_ms: int
    render_ms: int


def words(text: str) -> Counter[str]:
    """Count the words of a text, case-folded, ignoring one-character tokens."""
    return Counter(word.casefold() for word in WORD.findall(text) if len(word) > 1)


def coverage(rendered: Counter[str], rest: Counter[str]) -> float:
    """Return the share of rendered words, repeats included, that REST also holds."""
    total = sum(rendered.values())
    return 1.0 if total == 0 else sum((rendered & rest).values()) / total


def macro_labels(names: Iterable[str]) -> dict[str, str]:
    """Map macro names to report labels: built-in names as they are, others custom-N."""
    custom = sorted({name for name in names if name not in BUILT_IN_MACROS})
    numbered = {name: f"custom-{index}" for index, name in enumerate(custom, start=1)}
    return {name: numbered.get(name, name) for name in names}


def shown(kind: str, found: Iterable[str], text: str) -> int:
    """Count the query results that a text shows: issue keys and titles as whole words."""
    if kind == "cql":
        return sum(
            1 for title in found if title and re.search(rf"(?<!\w){re.escape(title)}(?!\w)", text)
        )
    return sum(1 for key in found if re.search(rf"\b{re.escape(key)}\b", text))


def compare_page(label: str, evidence: PageEvidence) -> list[Check]:
    """Compare what REST returned for a page with what the browser rendered."""
    view = evidence.view
    view_words = words(view.text)
    static_words = words(view.static_text)
    labels = macro_labels(evidence.storage.macros)
    checks = []
    # A macro has output in view when view wraps it with output, or, for a macro that
    # renders its body inline without a wrapper, such as an excerpt, when view holds
    # every word of its body. A Smart Link list of another kind is not compared.
    for name, count in sorted(evidence.storage.macros.items(), key=lambda item: labels[item[0]]):
        if name == OTHER_DATASOURCE:
            continue
        inline = sum(
            1
            for use in evidence.storage.uses
            if use.name == name and words(use.text) and not words(use.text) - view_words
        )
        present = max(view.macros_with_output[name], inline)
        detail = f"{present} of {count} with output in view"
        checks.append(Check(f"{label}: macro {labels[name]}", present >= count, detail))
    timing = f"REST {evidence.rest_ms} ms, browser {evidence.render_ms} ms"
    checks.append(Check(f"{label}: timing", passed=True, detail=timing))
    rendered = evidence.rendered
    if rendered is None:
        failure = Check(f"{label}: rendered", passed=False, detail="content area never settled")
        return [failure, *checks]
    # Text outside dynamic tables, word for word; the tables are compared by query.
    rendered_words = words(rendered.text)
    share = coverage(rendered_words, static_words)
    total = sum(rendered_words.values())
    local = view.local_images
    pairs = list(zip(evidence.rest_images, rendered.images, strict=False))
    full = sum(
        1
        for rest, seen in pairs
        if rest and (rest == VECTOR or (rest[0] >= seen[0] and rest[1] >= seen[1]))
    )
    widest_rest = max((rest[0] for rest in evidence.rest_images if rest), default=0)
    widest_seen = max((seen[0] for seen in rendered.images), default=0)
    missing = sum(1 for rest in evidence.rest_images if rest is None)
    external = len(view.images) - len(local)
    missing_words = total - sum((rendered_words & static_words).values())
    checks += [
        Check(
            f"{label}: words",
            share >= WORD_COVERAGE,
            f"{share:.1%} of {total} in view, {missing_words} missing",
        ),
        Check(
            f"{label}: expands",
            rendered.collapsed == 0,
            f"{rendered.opened} toggles clicked, {rendered.collapsed} still collapsed",
        ),
        Check(
            f"{label}: tables",
            rendered.tables == view.tables,
            f"{view.tables} in view, {rendered.tables} rendered",
        ),
        Check(
            f"{label}: images",
            len(local) == len(rendered.images) and full == len(pairs) and not missing,
            f"{len(local)} in view, {len(rendered.images)} rendered, {full} of {len(pairs)}"
            f" compared at full size or larger, {missing} not downloaded; widest {widest_rest}"
            f" px over REST, {widest_seen} px in the browser; external: {external} in view,"
            f" {rendered.external_images} rendered",
        ),
    ]
    return checks + compare_tables(label, evidence, rendered)


def compare_tables(label: str, evidence: PageEvidence, rendered: Rendered) -> list[Check]:
    """Compare each dynamic table's query results with what its own table shows."""
    others = evidence.storage.macros[OTHER_DATASOURCE]
    read = sum(1 for query in evidence.storage.queries if query.macro in DYNAMIC_TABLES)
    # Every table the browser draws under a dynamic selector needs a query read on this
    # page, or nothing compares it: a table from an included page, for one. Smart Link
    # lists of other kinds are drawn there too, and are not compared.
    checks = [
        Check(
            f"{label}: dynamic tables",
            rendered.regions <= read + others,
            f"{rendered.regions} in the browser, {read} with a query read, {others} other lists",
        )
    ]
    if others:
        checks.append(
            Check(f"{label}: smart-link-list", passed=True, detail=f"{others} not compared")
        )
    for index, (query, found) in enumerate(evidence.results, start=1):
        name = f"{label}: {query.kind} {index}"
        if not found:
            # Nothing over REST leaves nothing to compare: a JQL with currentUser(), or
            # one aimed at another site, may still show rows in the browser.
            detail = "query failed" if found is None else "0 over REST"
            checks.append(Check(name, passed=False, detail=detail))
            continue
        tables = rendered.dynamic_tables.get(query.macro, ())
        if query.macro not in DYNAMIC_TABLES:
            browser = f"{rendered.text} {rendered.dynamic_text}"
        elif query.macro == DATASOURCE and others:
            # Lists of other kinds share the selector, so order cannot pair a table.
            browser = " ".join(tables)
        else:
            browser = tables[query.ordinal] if query.ordinal < len(tables) else ""
        outputs = evidence.view.macro_outputs.get(query.macro, [])
        own = outputs[query.ordinal] if query.ordinal < len(outputs) else ""
        in_browser, in_view = shown(query.kind, found, browser), shown(query.kind, found, own)
        # A table shows only its first rows: any of the results may be among them.
        detail = f"{len(found)} over REST, {query.rows} shown at most; "
        detail += f"{in_browser} shown in the browser, {in_view} in view"
        checks.append(Check(name, in_browser >= min(len(found), query.rows), detail))
    return checks


def render_report(checks: Sequence[Check]) -> str:
    """Write the checks as lines of text, then a summary line."""
    lines = [
        f"{'PASS' if check.passed else 'FAIL'}  {check.name}  {check.detail}" for check in checks
    ]
    failed = sum(not check.passed for check in checks)
    lines.append(f"{len(checks) - failed} passed, {failed} failed")
    return "\n".join(lines) + "\n"


def media_type(content_type: str) -> str:
    """Return a Content-Type's media type if known, else its top-level type and other."""
    value = content_type.split(";", 1)[0].strip().lower()
    if value in KNOWN_MEDIA_TYPES:
        return value
    top = value.split("/", 1)[0]
    return f"{top}/other" if top in {"application", "image", "text"} else "other"


def elapsed_ms(started: float) -> int:
    """Return the milliseconds since a time.monotonic() reading."""
    return round((time.monotonic() - started) * 1000)


def in_page_get(page: Page, site: str) -> Get:
    """Carry the session by fetch inside the signed-in page."""

    def get(path: str) -> Reply:
        started = time.monotonic()
        result = page.evaluate(FETCH_JS, [urljoin(site, path), HTTP_TIMEOUT_S * 1000])
        body = base64.b64decode(result["body"])
        return Reply(result["status"], media_type(result["type"]), body, elapsed_ms(started))

    return get


def request_context_get(context: BrowserContext, site: str) -> Get:
    """Carry the session by Playwright's request context, which shares the cookies."""

    def get(path: str) -> Reply:
        started = time.monotonic()
        response = context.request.get(
            urljoin(site, path), timeout=HTTP_TIMEOUT_S * 1000, max_redirects=5
        )
        status, content_type = response.status, response.headers.get("content-type", "")
        try:
            body = response.body()
        finally:
            response.dispose()
        return Reply(status, media_type(content_type), body, elapsed_ms(started))

    return get


def httpx_get(client: httpx.Client) -> Get:
    """Carry the session by httpx, with no browser; the body is read up to a bound."""

    def get(path: str) -> Reply:
        started = time.monotonic()
        with client.stream("GET", path) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    break
            content_type = response.headers.get("content-type", "")
            return Reply(
                response.status_code, media_type(content_type), bytes(body), elapsed_ms(started)
            )

    return get


def attempt(get: Get, path: str) -> Reply:
    """Make one GET, turning a failure into a reply that names only the exception class."""
    started = time.monotonic()
    try:
        return get(path)
    except (PlaywrightError, httpx.HTTPError, OSError, ValueError, KeyError) as error:
        return Reply(0, f"error {type(error).__name__}", b"", elapsed_ms(started))


def json_value(reply: Reply, *keys: str) -> object:
    """Return the value at a path in a JSON reply, or None when either is missing."""
    if reply.status != HTTP_OK or reply.media_type != JSON:
        return None
    try:
        value = json.loads(reply.body)
        for key in keys:
            value = value[key]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return value


def first_image(items: object, media_field: str) -> Mapping[str, object] | None:
    """Return the first attachment in a JSON list that is an image with a well-formed id."""
    if not isinstance(items, list):
        return None
    for item in items:
        if (
            isinstance(item, dict)
            and str(item.get(media_field, "")).startswith("image/")
            and ATTACHMENT_ID.fullmatch(str(item.get("id", "")))
        ):
            return item
    return None


def attachment_path(container: str, attachment: str) -> str:
    """Return the v1 download path of a Confluence attachment, which serves the original."""
    attachment = attachment if attachment.startswith("att") else f"att{attachment}"
    return f"/wiki/rest/api/content/{container}/child/attachment/{attachment}/download"


def image_size(reply: Reply) -> tuple[int, int] | None:
    """Return the pixel size of a downloaded image, VECTOR for an SVG, or None."""
    if reply.status != HTTP_OK or not reply.media_type.startswith("image/"):
        return None
    if reply.media_type == "image/svg+xml":
        return VECTOR
    try:
        with Image.open(BytesIO(reply.body)) as image:
            return image.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return None


def read_check(name: str, reply: Reply, expected: str) -> Check:
    """Pass a read that answered 200 with the expected media type."""
    passed = reply.status == HTTP_OK and reply.media_type.startswith(expected)
    detail = f"{reply.status} {reply.media_type or '-'} {len(reply.body)} B {reply.elapsed_ms} ms"
    return Check(name, passed, detail)


def probe_carrier(name: str, get: Get, page_id: str, jql: str) -> list[Check]:
    """Make the seven reads through one carrier: six JSON reads and one image download."""
    paths = {
        "spaces": "/wiki/api/v2/spaces?limit=1",
        "myself": "/rest/api/3/myself",
        "storage": f"/wiki/api/v2/pages/{page_id}?body-format=storage",
        "view": f"/wiki/api/v2/pages/{page_id}?body-format=view",
        "CQL search": "/wiki/rest/api/search?" + urlencode({"cql": f"id = {page_id}", "limit": 1}),
        "JQL search": "/rest/api/3/search/jql?"
        + urlencode({"jql": jql, "fields": "summary", "maxResults": 5}),
    }
    checks = [
        read_check(f"{name}: {read}", attempt(get, path), JSON) for read, path in paths.items()
    ]
    listing = attempt(get, f"/wiki/api/v2/pages/{page_id}/attachments?limit=25")
    image = first_image(json_value(listing, "results"), "mediaType")
    if image is None:
        failure = Check(f"{name}: image download", passed=False, detail="no image attachment")
        checks.append(failure)
        return checks
    download = attempt(get, attachment_path(page_id, str(image.get("id", ""))))
    checks.append(read_check(f"{name}: image download", download, "image/"))
    return checks


def run_query(get: Get, query: Query, cql_context: str) -> tuple[str, ...] | None:
    """Run a dynamic macro's query over REST; return its issue keys or page titles."""
    if query.kind == "key":
        issue = attempt(get, f"/rest/api/3/issue/{quote(query.text, safe='')}?fields=summary")
        key = json_value(issue, "key")
        return (key,) if isinstance(key, str) else None
    if query.kind == "jql":
        fields = {"jql": query.text, "fields": "summary", "maxResults": MAX_QUERY_RESULTS}
        issues = json_value(attempt(get, "/rest/api/3/search/jql?" + urlencode(fields)), "issues")
        if not isinstance(issues, list):
            return None
        return tuple(str(issue.get("key", "")) for issue in issues if isinstance(issue, dict))
    fields = {"cql": query.text, "cqlcontext": cql_context, "limit": MAX_QUERY_RESULTS}
    results = json_value(attempt(get, "/wiki/rest/api/search?" + urlencode(fields)), "results")
    if not isinstance(results, list):
        return None
    contents = (result.get("content") for result in results if isinstance(result, dict))
    return tuple(str(content.get("title", "")) for content in contents if isinstance(content, dict))


def render_page(page: Page, site: str, page_id: str) -> tuple[Rendered | None, int]:
    """Open a page, let it settle, open its expands and scroll it, and let it settle again.

    The time returned is that of the first render, before the probe's own scrolling.
    """
    started = time.monotonic()
    page.goto(
        urljoin(site, f"/wiki/pages/viewpage.action?pageId={page_id}"),
        timeout=SETTLE_TIMEOUT_S * 1000,
    )
    content = [
        CONTENT_SELECTORS,
        list(DYNAMIC_TABLES.values()),
        MEDIA_HOSTS,
        EXCERPT_INCLUDE,
        EXPAND_TOGGLES,
        MIN_IMAGE_SIDE,
    ]
    snapshot, previous, stable, changed_at, render_ms, clicked = None, None, 0, started, None, 0
    while time.monotonic() - started < SETTLE_TIMEOUT_S:
        page.wait_for_timeout(SETTLE_POLL_MS)
        snapshot = page.evaluate(CONTENT_JS, content)
        # Settled once text, dynamic tables and loaded images stop changing; an empty
        # area, the application's shell, never counts as settled.
        shows = snapshot and (snapshot["text"].strip() or snapshot["dynamic"].strip())
        current = (
            (snapshot["text"], snapshot["dynamic"], snapshot["tables"],
             len(snapshot["images"]), snapshot["collapsed"])
            if shows
            else None
        )  # fmt: skip
        if current is None or current != previous:
            stable, previous, changed_at = 0, current, time.monotonic()
        elif (stable := stable + 1) >= STABLE_POLLS:
            if render_ms is not None:
                break
            render_ms = round((changed_at - started) * 1000)
            scroll = [
                CONTENT_SELECTORS,
                EXPAND_TOGGLES,
                SCROLL_PAUSE_MS,
                MAX_SCROLL_STEPS,
                MAX_OPEN_PASSES,
            ]
            clicked = int(page.evaluate(SCROLL_JS, scroll))
            stable = 0
    else:
        return None, elapsed_ms(started) if render_ms is None else render_ms
    images = tuple((int(width), int(height)) for width, height in snapshot["images"])
    rendered = Rendered(
        snapshot["text"],
        int(snapshot["tables"]),
        images,
        int(snapshot["external"]),
        snapshot["dynamic"],
        int(snapshot["regions"]),
        dict(zip(DYNAMIC_TABLES, map(tuple, snapshot["regionTexts"]), strict=True)),
        clicked,
        int(snapshot["collapsed"]),
    )
    return rendered, render_ms


def gather_page(get: Get, page: Page, site: str, page_id: str) -> PageEvidence | Check:
    """Read a page over REST and render it in the browser; a Check reports a failure."""
    storage_reply = attempt(get, f"/wiki/api/v2/pages/{page_id}?body-format=storage")
    view_reply = attempt(get, f"/wiki/api/v2/pages/{page_id}?body-format=view")
    storage_body = json_value(storage_reply, "body", "storage", "value")
    view_body = json_value(view_reply, "body", "view", "value")
    if not isinstance(storage_body, str) or not isinstance(view_body, str):
        return Check("REST bodies", passed=False, detail="storage or view body missing")
    storage = StorageScanner.parse(storage_body)
    view = ViewScanner.parse(view_body)
    cql_context = ""
    if any(query.kind == "cql" for query in storage.queries):
        space = attempt(get, f"/wiki/api/v2/spaces/{json_value(storage_reply, 'spaceId')}")
        cql_context = json.dumps({"spaceKey": json_value(space, "key"), "contentId": page_id})
    results = tuple((query, run_query(get, query, cql_context)) for query in storage.queries)
    rest_images = tuple(
        image_size(attempt(get, attachment_path(image.container, image.attachment)))
        if image.kind == "attachment"
        else None
        for image in view.local_images[:MAX_IMAGES_PER_PAGE]
    )
    try:
        rendered, render_ms = render_page(page, site, page_id)
    except PlaywrightError as error:
        return Check("rendered", passed=False, detail=f"error {type(error).__name__}")
    rest_ms = storage_reply.elapsed_ms + view_reply.elapsed_ms
    return PageEvidence(storage, view, rendered, rest_images, results, rest_ms, render_ms)


def probe_issue(get: Get, key: str) -> list[Check]:
    """Read an issue with its rendered description, and download its first image."""
    reply = attempt(
        get, f"/rest/api/3/issue/{key}?fields=attachment,description&expand=renderedFields"
    )
    description = json_value(reply, "renderedFields", "description")
    images = ViewScanner.parse(description).images if isinstance(description, str) else []
    checks = [
        read_check("issue: read", reply, JSON),
        Check(
            "issue: description images", bool(images), f"{len(images)} in the rendered description"
        ),
    ]
    image = first_image(json_value(reply, "fields", "attachment"), "mimeType")
    if image is None:
        checks.append(Check("issue: image download", passed=False, detail="no image attachment"))
        return checks
    download = attempt(get, f"/rest/api/3/attachment/content/{image.get('id', '')}")
    size = image_size(download)
    pixels = "vector" if size == VECTOR else f"{size[0]}x{size[1]} px" if size else "not an image"
    detail = f"{download.status} {download.media_type} {len(download.body)} B, {pixels}"
    checks.append(Check("issue: image download", size is not None, detail))
    return checks


def save_cookies(path: Path, cookies: Iterable[Mapping[str, object]]) -> None:
    """Save the session's cookies, readable by the user alone."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)  # also when the file already existed
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump([dict(cookie) for cookie in cookies], file)


def refuse_plain_http(request: httpx.Request) -> None:
    """Refuse a request over plain HTTP, which would carry the session's cookies in clear."""
    if request.url.scheme != "https":
        message = "plain HTTP refused"
        raise httpx.UnsupportedProtocol(message, request=request)


def disable_password_saving(profile: Path) -> None:
    """Stop Chrome offering to save the password typed at sign-in, in this profile.

    Playwright starts Chrome with a mock keychain, so the profile's key is a fixed,
    public one: a saved password would be readable by anyone who reads the profile.
    """
    preferences = profile / "Default" / "Preferences"
    preferences.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        settings = json.loads(preferences.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    settings["credentials_enable_service"] = False
    settings["profile"] = {**(settings.get("profile") or {}), "password_manager_enabled": False}
    settings["autofill"] = {**(settings.get("autofill") or {}), "profile_enabled": False}
    preferences.write_text(json.dumps(settings), encoding="utf-8")


def session_client(site: str, cookies: Iterable[object]) -> httpx.Client:
    """Return an httpx client carrying the session's cookies, verifying TLS with the OS."""
    jar = httpx.Cookies()
    for cookie in cookies:
        if isinstance(cookie, dict) and {"name", "value", "domain"} <= cookie.keys():
            path = str(cookie.get("path") or "/")
            jar.set(
                str(cookie["name"]), str(cookie["value"]), domain=str(cookie["domain"]), path=path
            )
    return httpx.Client(
        base_url=site,
        cookies=jar,
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_S,
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        event_hooks={"request": [refuse_plain_http]},
    )


def sign_in(page: Page, site: str, in_page: Get) -> Check:
    """Open the site, then wait until REST answers from inside the page."""
    started = time.monotonic()
    page.goto(urljoin(site, "/wiki/home"))
    while time.monotonic() - started < SIGN_IN_TIMEOUT_S:
        # No script runs in the identity provider's pages: only once back on the site.
        if urlsplit(page.url).netloc == urlsplit(site).netloc:
            reply = attempt(in_page, "/wiki/api/v2/spaces?limit=1")
            if reply.status == HTTP_OK and reply.media_type == JSON:
                return Check("sign-in", passed=True, detail=f"{elapsed_ms(started) // 1000} s")
        page.wait_for_timeout(SIGN_IN_POLL_MS)
    return Check("sign-in", passed=False, detail=f"no REST answer within {SIGN_IN_TIMEOUT_S} s")


def run_with_browser(arguments: argparse.Namespace, jql: str) -> list[Check]:
    """Sign in, probe the three carriers, then compare each page and the issue."""
    arguments.profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    disable_password_saving(arguments.profile)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            arguments.profile,
            headless=False,
            channel=None if arguments.chrome else "chrome",
            executable_path=arguments.chrome,
            ignore_default_args=["--disable-extensions"] if arguments.keep_extensions else None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            in_page = in_page_get(page, arguments.site)
            checks = [sign_in(page, arguments.site, in_page)]
            if not checks[0].passed:
                return checks
            # Only the site's own cookies: the identity provider's stay in the browser.
            with session_client(arguments.site, context.cookies([arguments.site])) as client:
                carriers = {
                    "httpx": httpx_get(client),
                    "request context": request_context_get(context, arguments.site),
                    "in-page fetch": in_page,
                }
                results = {
                    name: probe_carrier(name, get, arguments.page[0], jql)
                    for name, get in carriers.items()
                }
                for carrier_checks in results.values():
                    checks += carrier_checks
                # The pages are read through the carrier with the most passing reads,
                # the first in this order on a tie: a site without Jira fails some for all.
                best = carriers[max(results, key=lambda name: sum(c.passed for c in results[name]))]
                for index, page_id in enumerate(arguments.page, start=1):
                    evidence = gather_page(best, page, arguments.site, page_id)
                    if isinstance(evidence, Check):
                        checks.append(
                            Check(
                                f"page-{index}: {evidence.name}",
                                passed=False,
                                detail=evidence.detail,
                            )
                        )
                    else:
                        checks += compare_page(f"page-{index}", evidence)
                if arguments.issue:
                    checks += probe_issue(best, arguments.issue)
            save_cookies(arguments.profile / COOKIES_FILE, context.cookies([arguments.site]))
            return checks
        finally:
            context.close()


def run_with_saved_cookies(arguments: argparse.Namespace, jql: str) -> list[Check]:
    """Probe httpx alone with the cookies an earlier run saved: no browser at all."""
    path = arguments.profile / COOKIES_FILE
    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [Check("saved session", passed=False, detail=f"error {type(error).__name__}")]
    with session_client(arguments.site, cookies if isinstance(cookies, list) else []) as client:
        checks = probe_carrier("httpx, saved session", httpx_get(client), arguments.page[0], jql)
        rolled = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
            for cookie in client.cookies.jar
        ]
    save_cookies(path, rolled)
    return checks


def tls_check(site: str) -> Check:
    """Show whether the public CA bundle verifies the site.

    Only a certificate that it cannot verify, the mark of TLS inspection, fails; no
    connection is inconclusive.
    """
    public = ssl.create_default_context(cafile=certifi.where())
    with httpx.Client(timeout=HTTP_TIMEOUT_S, verify=public) as client:
        try:
            response = client.get(urljoin(site, "/wiki/api/v2/spaces?limit=1"))
        except httpx.HTTPError as error:
            cause: BaseException | None = error
            for _ in range(10):
                if cause is None or isinstance(cause, ssl.SSLCertVerificationError):
                    break
                cause = cause.__cause__ or cause.__context__
            if isinstance(cause, ssl.SSLCertVerificationError):
                return Check(
                    "tls: public CA bundle", passed=False, detail="certificate not verified"
                )
            detail = f"inconclusive, error {type(error).__name__}"
            return Check("tls: public CA bundle", passed=True, detail=detail)
    return Check("tls: public CA bundle", passed=True, detail=f"verified, {response.status_code}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and print its report; exit 0 only when every check passes."""
    if sys.platform == "darwin":
        state = Path.home() / "Library" / "Application Support"
    else:
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    parser = argparse.ArgumentParser(
        description="Probe Atlassian Cloud REST through a browser session."
    )
    parser.add_argument("--site", required=True, help="the site, as https://<name>.atlassian.net")
    parser.add_argument("--page", action="append", required=True, help="a page id; up to three")
    parser.add_argument("--issue", help="a Jira issue key whose description holds an image")
    parser.add_argument(
        "--profile",
        type=Path,
        default=state / "atlassian-offline-mcp" / "probe-browser",
        help="the dedicated browser profile; it holds the session's cookies",
    )
    parser.add_argument("--chrome", help="Chrome's executable, where the chrome channel fails")
    parser.add_argument("--keep-extensions", action="store_true", help="let Chrome load extensions")
    parser.add_argument("--no-sign-in", action="store_true", help="reuse saved cookies, no browser")
    arguments = parser.parse_args(argv)
    site = urlsplit(arguments.site)
    # Only a host: no user name, password or port, which the report could not hide.
    if site.scheme != "https" or not site.hostname or site.netloc.lower() != site.hostname:
        parser.error("--site takes an https URL with a host name alone")
    pages = arguments.page
    if len(pages) > MAX_PAGES or not all(PAGE_ID.fullmatch(page) for page in pages):
        parser.error("--page takes up to three numeric page ids")
    if arguments.issue and not ISSUE_KEY.fullmatch(arguments.issue):
        parser.error("--issue takes an issue key such as ABC-123")
    arguments.site = f"https://{site.hostname}"
    jql = f"key = {arguments.issue}" if arguments.issue else "updated >= -30d ORDER BY updated DESC"
    run = run_with_saved_cookies if arguments.no_sign_in else run_with_browser
    try:
        checks = run(arguments, jql)
    except (PlaywrightError, OSError) as error:
        checks = [Check("run", passed=False, detail=f"error {type(error).__name__}")]
    checks.append(tls_check(arguments.site))
    sys.stdout.write(render_report(checks))
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
