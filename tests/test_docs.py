"""The pages stay true to the checkout and to the code they describe.

Plan 020 walks the checkout for Markdown and reads each page as GitHub renders it: a
relative link reaches a file, or a heading, of the checkout; a link into ``src/`` whose
text is code names what that file defines; the map, ``docs/README.md``, links each page
of the four folders; each command line of the program in a bash block parses, as plans
015 and 017 first checked on their own pages; a page that names Ollama says that any
OpenAI-compatible API works; Docker's command follows each of Podman's; the reference
of the MCP server names, as plan 019 first checked, each tool and prompt that a server
lists over stdio, with their parameters; and the tutorial of a first mirror and the
guide to embeddings pull the model that the settings default to.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import itertools
import posixpath
import re
import shlex
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, override
from urllib.parse import unquote, urlsplit

import pytest
from markdown_it import MarkdownIt
from mcp.client.stdio import StdioServerParameters

from atlassian_offline_mcp.cli.main import parser
from atlassian_offline_mcp.config.domain.settings import DEFAULT_MODEL
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from tests.test_serve import talk

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).parents[1]
# The pages whose command lines plans 015 and 017 checked, and the tutorial of a first
# mirror: each still holds one checked.
PAGES = (
    "AGENTS.md",
    "docs/how-to/agents.md",
    "docs/how-to/api-token-with-sops.md",
    "docs/how-to/evaluate-with-agents.md",
    "docs/how-to/golden-questions.md",
    "docs/how-to/shell-completions.md",
    "docs/how-to/sync.md",
    "docs/how-to/sso-machine.md",
    "docs/how-to/work-log.md",
    "docs/tutorials/first-mirror.md",
)
# Folders whose Markdown is seeded into the sandbox site: its content, not pages here.
SEEDED = frozenset({"sandbox/corpus", "sandbox/jira"})
# Markdown as GitHub reads it, tables included, so that code is never read as a link.
PARSER = MarkdownIt("commonmark").enable("table")
# What GitHub drops from a heading's text to make its anchor: all but letters, digits,
# underscores, hyphens and spaces.
UNSLUGGED = re.compile(r"[^\w\- ]")
# The four kinds of page, by Diataxis, each a folder of docs/.
KINDS = frozenset({"tutorials", "how-to", "reference", "explanation"})
# A fragment naming lines, as GitHub's view of a file reads it: lines move, names stay.
LINES = re.compile(r"L\d+(-L\d+)?")
# The program's name as a word of its own, not part of a path or of another name.
PROGRAM = re.compile(r"(?<![\w/.~-])atlassian-offline-mcp(?![\w/.-])")
# A line of a block of shell, with the lines that its continuations join to it.
SHELL_LINE = re.compile(r"^(?:.*\\\n)*.*$", re.MULTILINE)
# A word that sets a variable for the command that follows it.
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
# Words that end one command and begin the next: a pipe or a list.
SEPARATORS = frozenset({"|", "|&", "||", "&", "&&", ";"})
# A word from which on a command's words are the shell's: `<`, or an output redirection
# with or without its file, such as `>`, `2>sync.log` or the `2>` of `2>&1`. A
# placeholder such as `<missing-file>` stays an argument.
REDIRECTION = re.compile(r"<<?|\d*>.*")
# The reference of the MCP server's tools and prompts, and its headings: a part, then
# a tool or a prompt of that part.
MCP_TOOLS = "docs/reference/mcp-tools.md"
HEADING = re.compile(r"^(#{2,3}) (.+)$", re.MULTILINE)
# The one page whose console blocks may run the program: the lesson's own subcommand,
# which no commit declares.
FIRST_CHANGE = "docs/tutorials/first-change.md"
# Ollama, named in any case, and what a page that names it says too: it is the example
# of the embedding APIs that work, never the only one.
OLLAMA = re.compile(r"ollama", re.IGNORECASE)
COMPATIBLE = "OpenAI-compatible"
# A container engine's command, in code: the engine, then its verb.
CONTAINER = re.compile(r"(?<![\w-])(podman|docker) ([a-z][\w-]*)")
# Podman's virtual machine on macOS, which Docker Desktop starts by itself.
PODMAN_ONLY = frozenset({"machine"})
# The pages that pull the default model, and the model that a line of their shell
# pulls. The evaluation of search pulls the model it measured, whatever the default.
DEFAULT_PULLS = ("docs/how-to/embeddings.md", "docs/tutorials/first-mirror.md")
PULL = re.compile(r"^ollama pull (\S+)$", re.MULTILINE)


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


class Unabbreviated(argparse.ArgumentParser):
    """A parser that takes an option by its whole name alone, never by a prefix of it.

    argparse gives each subcommand's parser the class of its parent, so that no level of
    the command takes a prefix: a flag renamed by extension, as ``--since`` would be to
    ``--since-date``, fails each page that still writes the old name.
    """

    @override
    def __init__(self, *arguments: Any, **keywords: Any) -> None:
        """Build the parser as argparse does, with abbreviations refused."""
        super().__init__(*arguments, **{**keywords, "allow_abbrev": False})


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


def test_the_map_links_each_page_of_the_four_kinds_and_docs_holds_no_other(
    checkout: frozenset[str],
) -> None:
    """``docs/README.md`` links each page under the four folders, at any depth.

    Any other page under ``docs/`` is the map itself or a plan's record in ``docs/work/``.
    """
    mapped = {link.path for link in read("docs/README.md").links}
    pages = {path for path in checkout if path.startswith("docs/") and path.endswith(".md")}
    kinds = {page for page in pages if page.split("/")[1] in KINDS}
    assert [f"docs/README.md does not link {page}" for page in sorted(kinds - mapped)] == []
    others = sorted(page for page in pages - kinds if not page.startswith("docs/work/"))
    assert others == ["docs/README.md"]


def shell_words(line: str) -> list[str]:
    """Split a line into words as a shell does, leaving a comment out.

    A run of ``;``, ``|`` and ``&``, such as ``&&``, is a word of its own even where no
    space parts it from the word before, as in ``check; sync``; so ``2>&1`` is three
    words, of which the first ends the arguments.
    """
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";|&")
    lexer.whitespace_split = True
    return list(lexer)


def program_arguments(words: list[str]) -> list[list[str]]:
    """Give the arguments that each command of a line's words gives the program.

    The words split into commands at a pipe or a list. In a command that names the
    program, it is the command word after any ``NAME=value``, after ``uv run``, inside
    the quoted command of ``sops exec-env <file> '...'`` or of ``eval "$(...)"``, or
    after the ``--`` of ``claude mcp add``; its arguments end at a redirection. Raises
    ValueError for a command that names the program in any other form.
    """
    given: list[list[str]] = []
    for between, grouped in itertools.groupby(words, lambda word: word in SEPARATORS):
        command = list(grouped)
        if between or not any(PROGRAM.search(word) for word in command):
            continue
        match list(itertools.dropwhile(ASSIGNMENT.match, command)):
            case ["atlassian-offline-mcp", *arguments]:
                kept = itertools.takewhile(lambda word: not REDIRECTION.fullmatch(word), arguments)
                given.append(list(kept))
            case ["uv", "run", *inner]:
                given += program_arguments(inner)
            case ["sops", "exec-env", *_, inner]:
                given += program_arguments(shell_words(inner))
            case ["claude", "mcp", "add", *added] if "--" in added:
                given += program_arguments(added[added.index("--") + 1 :])
            case ["eval", inner] if inner.startswith("$(") and inner.endswith(")"):
                given += program_arguments(shell_words(inner[2:-1]))
            case _:
                message = "names the program in a form that program_arguments does not read"
                raise ValueError(message)
    return given


def test_each_documented_command_line_of_the_program_parses(checkout: frozenset[str]) -> None:
    """In a bash block of any page but the plans', the program's arguments parse.

    Continuations joined, words split as a shell does, a comment left out, the arguments
    that ``program_arguments`` finds in each command of a line parse with the command's
    own parser, no prefix taken for an option, no arguments meaning ``serve``; --help
    and --version exit 0, which passes. A line is refused when the shell could not split
    it, or when a command of it names the program in a form that ``program_arguments``
    does not read, so that no such form is passed unread. A console block that names the
    program is refused outside the tutorial of a first change, whose subcommand no commit
    declares.
    """
    refused = []
    checked: Counter[str] = Counter()
    blocks = [
        (page, block)
        for page in sorted(path for path in checkout if path.endswith(".md"))
        if not page.startswith("docs/work/")
        for block in PARSER.parse((ROOT / page).read_text("utf-8"))
        if block.type == "fence" and block.info in {"bash", "console"}
    ]
    for page, block in blocks:
        for found in SHELL_LINE.finditer(block.content):
            given = found[0].replace("\\\n", " ")
            if not PROGRAM.search(given):
                continue
            line = block.map[0] + 2 + block.content.count("\n", 0, found.start())
            if block.info == "console":
                if page != FIRST_CHANGE:
                    refused.append(f"{page}:{line}: the program in a console block")
                continue
            try:
                commands = program_arguments(shell_words(given))
            except ValueError as error:
                refused.append(f"{page}:{line}: {error}")
                continue
            checked[page] += len(commands)
            for arguments in commands:
                said = io.StringIO()
                try:
                    with (
                        contextlib.redirect_stdout(io.StringIO()),
                        contextlib.redirect_stderr(said),
                    ):
                        parser(Unabbreviated).parse_args(arguments or ["serve"])
                except SystemExit as stopped:
                    if stopped.code != 0:
                        refused.append(f"{page}:{line}: {said.getvalue().splitlines()[-1]}")
    assert refused == []
    assert [page for page in PAGES if not checked[page]] == []


def test_the_check_of_documented_commands_refuses_a_prefix_of_an_option() -> None:
    """The command's parser takes ``--dry`` for sync's ``--dry-run``; the check's does not."""
    with pytest.raises(SystemExit) as stopped, contextlib.redirect_stderr(io.StringIO()):
        parser(Unabbreviated).parse_args(["sync", "--dry"])
    assert stopped.value.code == ExitStatus.REFUSED


def test_each_page_that_names_ollama_says_that_any_openai_compatible_api_works(
    checkout: frozenset[str],
) -> None:
    """Outside the plans' records, a page that names Ollama says "OpenAI-compatible" too.

    The user asked the docs to take Ollama as the example, not as the requirement. A page
    that fails is cited at its first mention of Ollama, in any case, code included.
    """
    unsaid = []
    for page in sorted(path for path in checkout if path.endswith(".md")):
        text = (ROOT / page).read_text("utf-8")
        named = OLLAMA.search(text)
        if named and COMPATIBLE not in text and not page.startswith("docs/work/"):
            line = text.count("\n", 0, named.start()) + 1
            unsaid.append(f"{page}:{line}: names Ollama, and nowhere {COMPATIBLE}")
    assert unsaid == []


def test_each_podman_command_has_docker_s_below_it_in_its_section(
    checkout: frozenset[str],
) -> None:
    """Outside the plans' records, Podman comes first and Docker too, as the user chose.

    In code, in a fenced block or a span, each ``podman <verb>`` but ``podman machine``
    has a ``docker <verb>`` below it before the next heading, one Docker line serving
    every Podman line above it. A line of a block is cited exactly, a span by the first
    line of its paragraph.
    """
    alone = []
    for page in sorted(path for path in checkout if path.endswith(".md")):
        if page.startswith("docs/work/"):
            continue
        commands = []  # each command's section, line, engine and verb, in the page's order
        section = 0
        for block in PARSER.parse((ROOT / page).read_text("utf-8")):
            section += block.type == "heading_open"
            # A fence's code starts on the line after it; a span is cited by its paragraph.
            codes = (
                [(block.content, block.map[0] + 2)]
                if block.type == "fence"
                else [
                    (child.content, block.map[0] + 1)
                    for child in block.children or []
                    if child.type == "code_inline"
                ]
            )
            commands += [
                (section, first + code.count("\n", 0, at.start()), *at.groups())
                for code, first in codes
                for at in CONTAINER.finditer(code)
            ]
        later = set()  # the Docker verbs below, by section
        for section, line, engine, verb in reversed(commands):
            if engine == "docker":
                later.add((section, verb))
            elif verb not in PODMAN_ONLY and (section, verb) not in later:
                alone.append(f"{page}:{line}: podman {verb}, no docker {verb} below in its section")
    assert alone == []


def test_the_reference_names_each_tool_and_prompt_served_and_each_of_their_parameters(
    tmp_path: Path,
) -> None:
    """Its headings under Tools and Prompts are what a server lists over stdio, in order.

    The server starts as agents start it, in a scratch home, and is listed through
    ``tests/test_serve.py``'s ``talk``; each parameter of a tool's schema and each
    argument of a prompt leads a bullet of its section, in code (``- `name`:``), so that
    another line's mention does not stand for its own.
    """
    command = StdioServerParameters(
        command=sys.executable, args=["-m", "atlassian_offline_mcp"], env={"HOME": str(tmp_path)}
    )
    _, listed, _ = talk(command, [])
    served = {
        "Tools": {
            tool["name"]: list(tool["inputSchema"].get("properties", {}))
            for tool in listed["tools"]
        },
        "Prompts": {
            prompt["name"]: [argument["name"] for argument in prompt.get("arguments", [])]
            for prompt in listed["prompts"]
        },
    }
    text = (ROOT / MCP_TOOLS).read_text("utf-8")
    found = list(HEADING.finditer(text))
    headings: dict[str, list[str]] = {}
    lines: dict[tuple[str, str], int] = {}
    bodies: dict[tuple[str, str], str] = {}
    part = ""
    for heading, after in zip(found, [*found[1:], None], strict=True):
        line = text.count("\n", 0, heading.start()) + 1
        if heading[1] == "##":
            part = heading[2]
            lines[part, ""] = line
            continue
        headings.setdefault(part, []).append(heading[2])
        lines[part, heading[2]] = line
        bodies[part, heading[2]] = text[heading.end() : after.start() if after else len(text)]
    problems = []
    for part, offered in served.items():
        at = lines.get((part, ""), 1)
        if headings.get(part, []) != list(offered):
            problems.append(
                f"{MCP_TOOLS}:{at}: {part} are {headings.get(part, [])}, served {list(offered)}"
            )
        problems.extend(
            f"{MCP_TOOLS}:{lines.get((part, name), at)}: {name} has no bullet `{parameter}`"
            for name, parameters in offered.items()
            for parameter in parameters
            if not re.search(
                rf"^- `{re.escape(parameter)}`:", bodies.get((part, name), ""), re.MULTILINE
            )
        )
    assert problems == []


def test_each_page_that_pulls_the_default_model_pulls_the_one_the_settings_name() -> None:
    """Each ``ollama pull`` in a bash block of those pages names the default model.

    So the learner who follows the tutorial, or the guide, word for word has the model
    that ``sync`` and ``index`` embed with. A line that pulls another is cited, and so is
    a page that pulls none.
    """
    pulled = {
        page: [
            (block.map[0] + 2 + block.content.count("\n", 0, found.start()), found[1])
            for block in PARSER.parse((ROOT / page).read_text("utf-8"))
            if block.type == "fence" and block.info == "bash"
            for found in PULL.finditer(block.content)
        ]
        for page in DEFAULT_PULLS
    }
    assert [f"{page}: no ollama pull in a bash block" for page in pulled if not pulled[page]] == []
    assert [
        f"{page}:{line}: pulls {model}, not {DEFAULT_MODEL}"
        for page, lines in pulled.items()
        for line, model in lines
        if model != DEFAULT_MODEL
    ] == []
