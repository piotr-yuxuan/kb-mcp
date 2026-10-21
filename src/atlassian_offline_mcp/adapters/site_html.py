"""The site's rendered HTML, made plain for pandoc: the one module that knows its markup.

Confluence's ``view`` bodies and Jira's rendered fields are HTML that the site renders
for its own pages. Every class name, data attribute, macro name and address pattern the
mirror relies on is a constant of this module, and each kind of markup is one small
construct: when the site changes its HTML, the fix is here. Markup that no construct
knows stays visible as a placeholder that names it, with its content kept.

``normalise`` returns HTML that pandoc writes as Markdown without raw HTML, apart from a
table that Markdown cannot hold and ``sub`` and ``sup``: a few tags and attributes,
visible text only, links to the mirror relative, and nothing that runs or fetches.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, override
from urllib.parse import parse_qs, urlsplit

from lxml.html import Element, HtmlElement, fragment_fromstring, tostring

from atlassian_offline_mcp.domain.mirror_layout import visible

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import PurePosixPath

# The attribute of the wrapper that the site renders around a macro's output.
MACRO = "data-macro-name"
# The parts of a panel: its title, and what holds its content.
PANEL_HEADER = "panelHeader"
PANEL_CONTENT = "panelContent"
INFORMATION_BODY = "confluence-information-macro-body"
# A code macro's highlighter parameters, such as "brush: py; gutter: false".
CODE_PARAMETERS = "data-syntaxhighlighter-params"
BRUSH = re.compile(r"(?:^|;)\s*brush:\s*([A-Za-z0-9_+#.-]+)")
PLAIN_BRUSHES = frozenset({"none", "plain", "text"})
EXPAND_TITLE = "expand-control-text"
EXPAND_CONTENT = "expand-content"
# The query of a page properties report, which the site computes in the browser.
REPORT_QUERY = "data-cql"
# An inline task list, and a task that is done.
TASK_LIST = "inline-task-list"
TASK_DONE = "checked"
# What an image or a link names: an attachment by id, within the page that holds it, or
# a page or a blog post by id. The view gives an attachment's id without the "att" that
# the v2 API puts before it.
LINKED_ID = "data-linked-resource-id"
LINKED_TYPE = "data-linked-resource-type"
LINKED_CONTAINER = "data-linked-resource-container-id"
LINKED_NAME = "data-linked-resource-default-alias"
LINKED_ATTACHMENT = "attachment"
LINKED_DOCUMENTS = frozenset({"page", "blogpost"})
ATTACHMENT_PREFIX = "att"

# Addresses on the site: an attached file, a page or a blog post, an issue.
CONFLUENCE_FILE = re.compile(
    r"/wiki/download/(?:attachments|thumbnails)/(?P<owner>[0-9]+)/(?P<name>[^/?#]+)"
)
JIRA_FILE = re.compile(
    r"/(?:rest/api/[23]/attachment/content|secure/attachment|secure/thumbnail)/(?P<id>[0-9]+)"
)
DOCUMENT_ADDRESSES = (
    re.compile(r"/wiki/spaces/[^/]+/pages/(?P<id>[0-9]+)(?:[/?].*)?"),
    re.compile(
        r"/wiki/spaces/[^/]+/blog/(?:[0-9]{4}/[0-9]{2}/[0-9]{2}/)?(?P<id>[0-9]+)(?:[/?].*)?"
    ),
)
VIEW_PAGE = "/wiki/pages/viewpage.action"
VIEW_PAGE_ID = "pageId"
ISSUE_ADDRESS = re.compile(r"/browse/(?P<key>[A-Z][A-Z0-9_]+-[0-9]+)(?:[/?].*)?")
KEPT_SCHEMES = frozenset({"http", "https", "mailto"})
WEB_SCHEMES = frozenset({"http", "https"})

# Elements that are interface or code, never content: removed with what they hold.
REMOVED = (
    "//comment()|//processing-instruction()|//script|//style|//noscript|//template"
    "|//button|//form|//input|//select|//textarea|//link|//meta"
)
# Embedded content that Markdown cannot show: a placeholder names it.
EMBEDDED = "//iframe|//frame|//object|//embed|//video|//audio|//canvas|//svg|//math"
# The tags that pandoc writes as Markdown, kept with these attributes only.
ATTRIBUTES: dict[str, frozenset[str]] = {
    **dict.fromkeys(
        ("p", "br", "hr", "div", "blockquote", "ul", "li", "dl", "dt", "dd", "pre"),
        frozenset[str](),
    ),
    **dict.fromkeys(("h1", "h2", "h3", "h4", "h5", "h6"), frozenset[str]()),
    **dict.fromkeys(("table", "thead", "tbody", "tfoot", "tr", "caption"), frozenset[str]()),
    **dict.fromkeys(("td", "th"), frozenset({"colspan", "rowspan"})),
    **dict.fromkeys(("strong", "b", "em", "i", "s", "del", "strike", "sub", "sup"), frozenset()),
    "ol": frozenset({"start"}),
    "code": frozenset({"class"}),
    "a": frozenset({"href"}),
    "img": frozenset({"src", "alt"}),
}
# Containers of blocks that pandoc would keep as raw HTML: they become plain divisions.
BLOCKS = frozenset(
    {"section", "article", "header", "footer", "main", "aside", "nav", "figure", "figcaption"}
    | {"details", "summary", "center", "address", "fieldset", "legend"}
)
# The only class kept: a code block's language, as pandoc reads it.
LANGUAGE = re.compile(r"language-[A-Za-z0-9_+#.-]+")
HEADING = re.compile(r"h([1-6])")
DEEPEST = 6


@dataclass(frozen=True)
class Mirrored:
    """What a body can point to in the mirror, as paths relative to ``docs/``.

    A document's handle is its content id (Confluence) or its key (Jira). ``documents``
    maps handles to mirror files; ``files`` maps (handle, attachment id) and ``names``
    (handle, file name) to an attachment's asset, or to None when its file was not
    downloaded.
    """

    site: str | None
    documents: Mapping[str, PurePosixPath]
    files: Mapping[tuple[str, str], PurePosixPath | None]
    names: Mapping[tuple[str, str], PurePosixPath | None]


@dataclass(frozen=True)
class Context:
    """The document whose HTML is normalised: its handle, its file, and the mirror.

    ``shift`` moves every heading down by that many levels, for a comment under its own
    heading. ``unsupported`` counts the constructs shown as placeholders, by name.
    """

    owner: str
    here: PurePosixPath
    mirrored: Mirrored
    shift: int = 0
    unsupported: Counter[str] = field(default_factory=Counter[str])

    def relative(self, target: PurePosixPath) -> str:
        """Link a file of the mirror from this document's file."""
        return posixpath.relpath(target, self.here.parent)

    def on_site(self, address: str) -> str | None:
        """Return the path and query of an address on the site, or None elsewhere."""
        try:
            parts, site = urlsplit(address), urlsplit(self.mirrored.site or "")
        except ValueError:
            return None
        own = site.hostname is not None and (parts.scheme, parts.hostname) == (
            site.scheme,
            site.hostname,
        )
        local = not parts.scheme and not parts.netloc and parts.path.startswith("/")
        return parts.path + (f"?{parts.query}" if parts.query else "") if own or local else None

    def absolute(self, address: str) -> str | None:
        """Return an address readers can follow, or None for one they cannot.

        A site path takes the site's address when it is set; http, https and mailto
        addresses elsewhere stay; anything else, such as an in-page anchor or a
        ``javascript:`` address, is None.
        """
        path = self.on_site(address)
        if path is not None:
            return path if self.mirrored.site is None else self.mirrored.site + path
        try:
            scheme = urlsplit(address).scheme
        except ValueError:
            return None
        return address if scheme in KEPT_SCHEMES else None


class Construct(Protocol):
    """One kind of markup, and how it is rewritten in place."""

    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Rewrite this element, which the construct's pass found."""


def replace(element: HtmlElement, new: HtmlElement) -> None:
    """Put a new element where one was, keeping the text that followed it."""
    new.tail = element.tail
    element.getparent().replace(element, new)


def part(element: HtmlElement, name: str) -> HtmlElement | None:
    """Return the first element within, in document order, that has this class.

    An element's own parts come before those of the constructs it holds.
    """
    return next(iter(element.find_class(name)), None)


def new(tag: str, text: str | None = None, *children: HtmlElement | None) -> HtmlElement:
    """Return a new element with this text, then these children, those that exist."""
    created = Element(tag)
    created.text = text
    created.extend(child for child in children if child is not None)
    return created


def placeholder(context: Context, name: str, note: str = "unsupported") -> HtmlElement:
    """Return a visible, bracketed mark standing for a construct not shown, and count it."""
    context.unsupported[name] += 1
    return new("em", f"[{note} {name}]")


class Visible(Construct):
    """Every node: its text, the text that follows it and its attributes made visible.

    It runs first, so that what every other construct reads is clean.
    """

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Remove the characters that show nothing, or reorder what is shown."""
        if element.tail:
            element.tail = visible(element.tail)
        if not isinstance(element.tag, str):  # a comment or a processing instruction
            return
        if element.text:
            element.text = visible(element.text)
        for name, value in element.attrib.items():
            element.set(name, visible(value))


class Removed(Construct):
    """Interface, code and comments: removed with what they hold."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Remove the element, keeping the text that followed it."""
        element.drop_tree()


class Unsupported(Construct):
    """A macro that no construct knows: its name shown, its rendered content kept."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Put a placeholder naming the macro before its content."""
        mark = placeholder(context, f"macro: {element.get(MACRO, '')}")
        mark.tail, element.text = element.text, None
        element.insert(0, mark)
        element.drop_tag()


UNSUPPORTED = Unsupported()


class AsRendered(Construct):
    """A macro whose output reads well as the site renders it: its wrapper goes."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Keep what the macro rendered."""
        element.drop_tag()


AS_RENDERED = AsRendered()


@dataclass(frozen=True)
class Part(Construct):
    """A macro shown by one part of its output, such as an excerpt include's content."""

    name: str  # the class of the part kept

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Keep the part alone, or show the macro as unsupported when it has none."""
        kept = part(element, self.name)
        if kept is None:
            UNSUPPORTED.rewrite(element, context)
            return
        replace(element, kept)
        kept.drop_tag()


@dataclass(frozen=True)
class Panel(Construct):
    """A panel: a blockquote whose first line is its label in bold."""

    label: str | None  # None: the panel's own header names it, or "Panel"
    body: str  # the class of the part that holds its content

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Make the panel a labelled blockquote."""
        body = part(element, self.body)
        if body is None:
            UNSUPPORTED.rewrite(element, context)
            return
        header = part(element, PANEL_HEADER)
        title = "" if header is None else header.text_content().strip()
        label = new("strong", self.label or title or "Panel")
        replace(element, new("blockquote", None, new("p", None, label), body))


class Code(Construct):
    """A code macro: a block of code, with the language of its highlighter."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Make the macro a ``pre`` holding its code, its language as a class."""
        source = next(element.iter("pre"), None)
        if source is None:
            UNSUPPORTED.rewrite(element, context)
            return
        brush = BRUSH.search(source.get(CODE_PARAMETERS, ""))
        language = brush.group(1).lower() if brush else ""
        code = new("code", source.text_content())
        if language and language not in PLAIN_BRUSHES:
            code.set("class", f"language-{language}")
        replace(element, new("pre", None, code))


class Status(Construct):
    """A status lozenge: its text in brackets."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Make the lozenge ``[TEXT]``."""
        text = element.text_content().strip()
        element.clear(keep_tail=True)
        element.text = f"[{text}]"
        element.drop_tag()


class Expand(Construct):
    """An expand: a heading with its title, then its content, always shown."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Make the expand a heading one level below the heading before it."""
        content = part(element, EXPAND_CONTENT)
        if content is None:
            UNSUPPORTED.rewrite(element, context)
            return
        title = part(element, EXPAND_TITLE)
        before = element.xpath(
            "preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6][1]"
        )
        level = int(before[0].tag[1]) + 1 if before else 2  # the title is the first level
        text = "" if title is None else title.text_content().strip()
        heading = new(f"h{min(level, DEEPEST)}", text)
        replace(element, new("div", None, heading, content))


@dataclass(frozen=True)
class Computed(Construct):
    """A report that the site computes in the browser: named, with its query."""

    name: str
    query: str  # the attribute that holds the query

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Replace the report with a placeholder naming it, and its query."""
        query = next((node.get(self.query) for node in element.iter() if node.get(self.query)), "")
        mark = placeholder(context, self.name, "not mirrored:")
        mark.tail = " " if query else None
        replace(element, new("p", None, mark, new("code", query) if query else None))


# What each macro of the site becomes; a macro absent from this table is unsupported.
MACROS: dict[str, Construct] = {
    "info": Panel("Info", INFORMATION_BODY),
    "note": Panel("Note", INFORMATION_BODY),
    "warning": Panel("Warning", INFORMATION_BODY),
    "tip": Panel("Tip", INFORMATION_BODY),
    "panel": Panel(None, PANEL_CONTENT),
    "code": Code(),
    "status": Status(),
    "expand": Expand(),
    "include": AS_RENDERED,
    "excerpt": AS_RENDERED,
    "excerpt-include": Part(PANEL_CONTENT),
    "children": AS_RENDERED,
    "details": AS_RENDERED,
    "jira": AS_RENDERED,
    "blog-posts": AS_RENDERED,
    "detailssummary": Computed("page properties report", REPORT_QUERY),
}


class Macro(Construct):
    """Any macro's wrapper: rewritten as the table of macros says."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Rewrite the macro by its name."""
        MACROS.get(element.get(MACRO, ""), UNSUPPORTED).rewrite(element, context)


class Task(Construct):
    """A task of an inline task list: ``[x]`` when done, ``[ ]`` otherwise."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Mark the task's state before its text."""
        done = TASK_DONE in element.get("class", "").split()
        element.text = ("[x] " if done else "[ ] ") + (element.text or "")


class Image(Construct):
    """An image: its local asset, or a link to where it is, never fetched."""

    @staticmethod
    def attachment(element: HtmlElement, context: Context) -> tuple[bool, PurePosixPath | None]:
        """Say whether the image is an attachment, and return its asset if it has one.

        An attachment is found by its page and id, else by its page and file name.
        """
        files, names = context.mirrored.files, context.mirrored.names
        linked = element.get(LINKED_ID)
        if element.get(LINKED_TYPE) == LINKED_ATTACHMENT and linked:
            owner = element.get(LINKED_CONTAINER) or context.owner
            key = (owner, ATTACHMENT_PREFIX + linked)
            return True, files.get(key) or names.get((owner, element.get(LINKED_NAME, "")))
        path = (context.on_site(element.get("src", "")) or "").partition("?")[0]
        confluence = CONFLUENCE_FILE.fullmatch(path)
        if confluence:
            return True, names.get((confluence["owner"], confluence["name"]))
        jira = JIRA_FILE.match(path)
        if jira:
            return True, files.get((context.owner, jira["id"]))
        return False, None

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Show the asset, or link the image with its alt text."""
        attachment, asset = self.attachment(element, context)
        alt = element.get("alt") or element.get(LINKED_NAME) or "image"
        if asset is not None:
            image = new("img")
            image.set("src", context.relative(asset))
            image.set("alt", alt)
            replace(element, image)
            return
        address = context.absolute(element.get("src", "")) or ""
        link = new("a", alt)
        if urlsplit(address).scheme in WEB_SCHEMES:
            link.set("href", address)
        link.tail = " (image not downloaded)" if attachment else None
        replace(element, new("span", None, link))


class Link(Construct):
    """A link: relative when it leads to a mirrored document, else as readers follow it."""

    @staticmethod
    def handle(element: HtmlElement, context: Context) -> str | None:
        """Return the handle of the document that a link names, if it names one."""
        if element.get(LINKED_TYPE) in LINKED_DOCUMENTS and element.get(LINKED_ID):
            return element.get(LINKED_ID)
        path = context.on_site(element.get("href", "")) or ""
        found = [
            match["id"] for pattern in DOCUMENT_ADDRESSES if (match := pattern.fullmatch(path))
        ]
        issue = ISSUE_ADDRESS.fullmatch(path)
        address = urlsplit(path)
        if address.path == VIEW_PAGE:
            found += parse_qs(address.query).get(VIEW_PAGE_ID, [])
        return found[0] if found else issue["key"] if issue else None

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Point the link at the mirror, at the site, or nowhere, keeping its text."""
        handle = self.handle(element, context)
        target = None if handle is None else context.mirrored.documents.get(handle)
        address = context.absolute(element.get("href", ""))
        if target is not None:
            element.set("href", context.relative(target))
        elif address is not None:
            element.set("href", address)
        else:
            element.drop_tag()


class Embedded(Construct):
    """Embedded content, such as a video or a frame: a placeholder names it."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Replace the element with a placeholder naming its tag."""
        replace(element, placeholder(context, f"element: {element.tag}"))


class TableHead(Construct):
    """A table whose first row is all header cells: that row becomes its head."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Move a first row of header cells into a ``thead``."""
        rows = element.xpath("./tr|./tbody/tr")
        if (
            element.find("thead") is not None
            or not rows
            or {cell.tag for cell in rows[0]} != {"th"}
        ):
            return
        holder = rows[0].getparent()
        head = new("thead", None, rows[0])
        element.insert(element.index(holder) if holder is not element else 0, head)


class Plain(Construct):
    """Any other element: kept if pandoc writes it as Markdown, else its content alone."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Make a container of blocks a division, and unwrap any other unknown tag."""
        if element.tag in BLOCKS:
            element.tag = "div"
        elif element.tag not in ATTRIBUTES:
            element.drop_tag()


class Attributes(Construct):
    """Every element: only its allowed attributes, and its heading level shifted."""

    @override
    def rewrite(self, element: HtmlElement, context: Context) -> None:
        """Keep the allowed attributes, and shift a heading by the context's shift."""
        allowed = ATTRIBUTES.get(element.tag, frozenset())
        kept = {name: value for name, value in element.attrib.items() if name in allowed}
        if "class" in kept and not LANGUAGE.fullmatch(kept["class"]):
            del kept["class"]
        element.attrib.clear()
        element.attrib.update(kept)
        heading = HEADING.fullmatch(element.tag)
        if heading and context.shift:
            element.tag = f"h{min(int(heading[1]) + context.shift, DEEPEST)}"


# Each pass: what it finds, by XPath from the body's root, and the construct that
# rewrites each element found, in document order. Outer elements come first, so a
# construct finds its own parts before the constructs it holds rewrite theirs.
PASSES: tuple[tuple[str, Construct], ...] = (
    ("descendant-or-self::*|//comment()|//processing-instruction()", Visible()),
    (REMOVED, Removed()),
    (f"//*[@{MACRO}]", Macro()),
    (f"//ul[contains(concat(' ', normalize-space(@class), ' '), ' {TASK_LIST} ')]/li", Task()),
    ("//img", Image()),
    ("//a", Link()),
    (EMBEDDED, Embedded()),
    ("//table", TableHead()),
    ("descendant::*", Plain()),
    ("descendant-or-self::*", Attributes()),
)


def normalise(html: str, context: Context) -> str:
    """Return the site's HTML of one body as plain HTML for pandoc.

    Characters that no file could hold, such as lone surrogates, go before parsing; the
    rest of the invisible ones go once parsed, entities included.
    """
    root = fragment_fromstring(visible(html), create_parent="div")
    for path, construct in PASSES:
        for element in root.xpath(path):
            construct.rewrite(element, context)
    return tostring(root, encoding="unicode")
