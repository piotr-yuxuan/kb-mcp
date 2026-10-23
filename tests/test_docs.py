"""The pages stay true to the checkout and to the code they describe.

Plan 020 walks the checkout for Markdown and reads each page as GitHub renders it: a
relative link reaches a file, or a heading, of the checkout, and a link into ``src/``
whose text is code names what that file defines. Plan 015 checks that the
command lines of its two how-tos, ``AGENTS.md`` and the guides it changed parse, plan
017 those of its two; plan 019 that the reference names each tool and prompt served.
"""

from __future__ import annotations

import ast
import inspect
import itertools
import posixpath
import re
import shlex
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import unquote, urlsplit

import pytest
from markdown_it import MarkdownIt

from atlassian_offline_mcp.cli.main import parser
from atlassian_offline_mcp.kernel.tools import TOOLS
from atlassian_offline_mcp.mcp.app.surface import surface
from atlassian_offline_mcp.mcp.app.tools import Library

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).parents[1]
PAGES = (
    "AGENTS.md",
    "docs/how-to/agents.md",
    "docs/how-to/api-token-with-sops.md",
    "docs/how-to/evaluate-with-agents.md",
    "docs/how-to/first-download.md",
    "docs/how-to/golden-questions.md",
    "docs/how-to/shell-completions.md",
    "docs/how-to/sync.md",
    "docs/how-to/work-log.md",
)
# Folders whose Markdown is seeded into the sandbox site: its content, not pages here.
SEEDED = frozenset({"sandbox/corpus", "sandbox/jira"})
# Markdown as GitHub reads it, tables included, so that code is never read as a link.
PARSER = MarkdownIt("commonmark").enable("table")
# What GitHub drops from a heading's text to make its anchor: all but letters, digits,
# underscores, hyphens and spaces.
UNSLUGGED = re.compile(r"[^\w\- ]")
# A fragment naming lines, as GitHub's view of a file reads it: lines move, names stay.
LINES = re.compile(r"L\d+(-L\d+)?")
# A block of shell commands in Markdown.
BASH = re.compile(r"^```bash\n(.*?)^```", re.MULTILINE | re.DOTALL)
# The program's name as a word of its own, not part of a path or of another name.
PROGRAM = re.compile(r"(?<![\w/.~-])atlassian-offline-mcp(?![\w/.-])")
# What ends the arguments of a command: a quote, as around the command that sops runs, a
# parenthesis, a pipe, a list, a redirection.
END = re.compile(r"['\")|;&>]")


class Link(NamedTuple):
    """A link of a page, its target resolved from the checkout's root, as GitHub does.

    ``path`` is ``None`` for a link off the checkout, a URL with a scheme or a host, and
    the page itself for an anchor alone; ``code`` is the text when it is one code span.
    """

    line: int
    target: str
    path: str | None
    anchor: str
    code: str | None


class Page(NamedTuple):
    """What the checks read of a page: its links, and the anchors of its headings."""

    links: list[Link]
    anchors: frozenset[str]


@pytest.fixture(scope="module")
def checkout() -> frozenset[str]:
    """Walk the checkout for its files and folders, as paths from its root.

    Walked, not asked of git, which Ruff refuses to run (S603, S607); without dot-folders,
    caches and the seeded folders. So a link to a file that git does not track passes
    here, and fails in CI's fresh clone.
    """
    found = set()
    for folder, folders, files in ROOT.walk():
        here = folder.relative_to(ROOT)
        folders[:] = [
            name
            for name in folders
            if not name.startswith(".")
            and name != "__pycache__"
            and (here / name).as_posix() not in SEEDED
        ]
        found.update((here / name).as_posix() for name in [*folders, *files])
    return frozenset(found)


def read(page: str) -> Page:
    """Parse a page of the checkout, by its path from the root, as GitHub renders it.

    A heading's anchor is its text in lower case, without punctuation, each space a
    hyphen; one met again takes ``-1``, then ``-2``, and so on. A link's line counts the
    line breaks before it in its paragraph, cell or heading.
    """
    links = []
    slugs: Counter[str] = Counter()
    anchors = set()
    # Each inline token, the text of a block, follows the token that opens its block.
    for before, block in itertools.pairwise(PARSER.parse((ROOT / page).read_text("utf-8"))):
        children = block.children or []
        if before.type == "heading_open":
            text = "".join(
                child.content for child in children if child.type in {"text", "code_inline"}
            )
            slug = UNSLUGGED.sub("", text.lower()).replace(" ", "-")
            anchors.add(f"{slug}-{slugs[slug]}" if slugs[slug] else slug)
            slugs[slug] += 1
        breaks = 0
        for index, child in enumerate(children):
            if child.type in {"softbreak", "hardbreak"}:
                breaks += 1
            elif child.type == "link_open":
                target = str(child.attrs["href"])
                parts = urlsplit(target)
                if parts.scheme or parts.netloc:
                    path = None
                elif parts.path:
                    relative = posixpath.join(posixpath.dirname(page), unquote(parts.path))
                    path = posixpath.normpath(relative)
                else:
                    path = page
                inside = [token.type for token in children[index + 1 : index + 3]]
                links.append(
                    Link(
                        line=block.map[0] + 1 + breaks,
                        target=target,
                        path=path,
                        anchor=unquote(parts.fragment),
                        code=children[index + 1].content
                        if inside == ["code_inline", "link_close"]
                        else None,
                    )
                )
    return Page(links, frozenset(anchors))


def test_each_relative_link_reaches_a_file_or_folder_and_each_anchor_a_heading(
    checkout: frozenset[str],
) -> None:
    """In every Markdown page, as GitHub resolves its links; no link names lines.

    An anchor needs a Markdown target with that heading. Lines are refused off the
    checkout too: a claim links the code it describes by name.
    """
    broken = []
    for page in sorted(path for path in checkout if path.endswith(".md")):
        for link in read(page).links:
            where = f"{page}:{link.line}: {link.target}"
            if LINES.fullmatch(link.anchor):
                broken.append(f"{where} names lines, not code")
            elif link.path is None:
                continue
            elif link.path not in checkout:
                broken.append(f"{where} reaches no file or folder")
            elif link.anchor and (
                not link.path.endswith(".md") or link.anchor not in read(link.path).anchors
            ):
                broken.append(f"{where} names no heading of {link.path}")
    assert broken == []


def defined(statements: Iterable[ast.stmt]) -> set[str]:
    """Name the functions, classes and assigned names that statements define."""
    names = set()
    for statement in statements:
        match statement:
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                names.add(name)
            case ast.AnnAssign(target=ast.Name(id=name)) | ast.TypeAlias(name=ast.Name(id=name)):
                names.add(name)
            case ast.Assign(targets=targets):
                names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def test_each_code_link_into_the_source_names_what_its_file_defines(
    checkout: frozenset[str],
) -> None:
    """A link to a module of ``src/`` whose text is one code span names what it defines.

    That is a function, a class or a constant defined at its top, or ``Class.name``: a
    method, or a name assigned in the class's body. A link to a folder is not read, nor
    one to a missing file, which the check of links refuses.
    """
    unknown = []
    for page in sorted(path for path in checkout if path.endswith(".md")):
        for link in read(page).links:
            if not (
                link.code
                and link.path in checkout
                and link.path.startswith("src/")
                and link.path.endswith(".py")
            ):
                continue
            module = ast.parse((ROOT / link.path).read_bytes(), link.path).body
            classes = [node for node in module if isinstance(node, ast.ClassDef)]
            names = defined(module) | {
                f"{owner.name}.{name}" for owner in classes for name in defined(owner.body)
            }
            if link.code not in names:
                unknown.append(f"{page}:{link.line}: `{link.code}` is not defined in {link.path}")
    assert unknown == []


@pytest.mark.parametrize("page", PAGES)
def test_each_command_line_of_the_program_parses(page: str) -> None:
    """With continuations joined, the arguments of the program's last name in a line parse.

    The last, as in ``claude mcp add ... atlassian-offline-mcp -- atlassian-offline-mcp``,
    whose server bears the program's name; no arguments mean ``serve``. --help may exit 0.
    """
    text = (ROOT / page).read_text("utf-8")
    lines = [
        END.split(PROGRAM.split(line)[-1])[0]
        for block in BASH.findall(text)
        for line in block.replace("\\\n", " ").splitlines()
        if PROGRAM.search(line)
    ]
    assert lines, page
    refused = []
    for given in lines:
        try:
            parser().parse_args(shlex.split(given) or ["serve"])
        except SystemExit as stopped:
            if stopped.code != 0:
                refused.append(given)
    assert refused == []


def test_the_reference_names_each_tool_and_prompt_served_and_each_of_their_parameters() -> None:
    """Its headings under Tools and Prompts are those served, each parameter in code below.

    The headings come in the server's order, as plan 020's check of every page reads them.
    """
    text = (ROOT / "docs" / "reference" / "mcp-tools.md").read_text("utf-8")
    tools = text.split("\n## Tools\n")[1].split("\n## Prompts\n")[0]
    prompts = text.split("\n## Prompts\n")[1]
    library = Library(ROOT / "index.sqlite", ROOT / "docs")
    sections = {
        name: body
        for part in (tools, prompts)
        for name, body in re.findall(
            r"^### (\S+)\n(.*?)(?=^### |\Z)", part, re.MULTILINE | re.DOTALL
        )
    }
    assert re.findall(r"^### (\S+)$", tools, re.MULTILINE) == list(TOOLS)
    guides = surface(library, TOOLS).guides
    assert re.findall(r"^### (\S+)$", prompts, re.MULTILINE) == [guide.name for guide in guides]
    for tool in TOOLS:
        named = list(inspect.signature(getattr(library, tool)).parameters)
        assert all(f"`{name}`" in sections[tool] for name in named), tool
    for guide in guides:
        assert all(f"`{name}`" in sections[guide.name] for name, _ in guide.arguments), guide.name
