"""The pages stay true to the checkout and to the code they describe.

Plan 020 walks the checkout for Markdown and reads each page as GitHub renders it: a
relative link reaches a file, or a heading, of the checkout; a link into ``src/`` whose
text is code names what that file defines; the map, ``docs/README.md``, links each page
of the four folders; each command line of the program in a bash block parses, as plans
015 and 017 first checked on their own pages; a page that names Ollama says that any
OpenAI-compatible API works; Docker's command follows each of Podman's; the reference
of the MCP server names, as plan 019 first checked, each tool and prompt that a server
lists over stdio, with their parameters; the tutorial of a first mirror and the guide
to embeddings pull the model that the settings default to; and the how-to for adding a
source gives the code of the memo source that the tests run, under its own names.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import itertools
import json
import posixpath
import re
import shlex
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, override
from urllib.parse import unquote, urlsplit

import pytest
from markdown_it import MarkdownIt
from mcp.client.stdio import StdioServerParameters

from kb_mcp.cli.main import parser
from kb_mcp.config.domain.settings import DEFAULT_MODEL
from kb_mcp.kernel.exit_status import ExitStatus
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
    "docs/how-to/reranking.md",
    "docs/how-to/shell-completions.md",
    "docs/how-to/refresh.md",
    "docs/how-to/sso-machine.md",
    "docs/how-to/work-log.md",
    "docs/tutorials/first-mirror.md",
)
# The how-to for adding a source, whose package is the tests' memo source under another
# name, each of its files by the page's words: what the page gives is then what they run.
ADD_A_SOURCE = ROOT / "docs" / "how-to" / "add-a-source.md"
REGISTRY = ROOT / "src" / "kb_mcp" / "sources" / "registry.py"
NOTES_PACKAGE = "kb_mcp.sources.notes"
MEMO_PACKAGE = ROOT / "tests" / "fixtures" / "memo_source" / "kb_memo"
MEMO_NAMES = {"kb_memo": NOTES_PACKAGE, "memo": "notes", "Memo": "Notes", "MEMO": "NOTES"}
CREATED = re.compile(r"Create\s+`([^`~]+)`[^`:]*:\n\n```python\n(.*?)```", re.DOTALL)
# Folders whose Markdown is seeded into the sandbox site: its content, not pages here.
SEEDED = frozenset({"sandbox/corpus", "sandbox/jira"})
# Markdown as GitHub reads it, tables included, so that code is never read as a link.
PARSER = MarkdownIt("commonmark").enable("table")
# What GitHub drops from a heading's text to make its anchor: all but letters, digits,
# underscores, hyphens and spaces.
UNSLUGGED = re.compile(r"[^\w\- ]")
# A plan named by its number, as history names it: "plan 034", "plans 021 and 024".
PLAN_NUMBER = re.compile(r"\b[Pp]lans?\s+\d{3}\b")
# The pages that name plans, being history told outside the records; none may join them.
TELLING_HISTORY = (
    "docs/README.md",
    "docs/explanation/chunking.md",
    "docs/explanation/code-layout.md",
    "docs/explanation/code-walkthrough.md",
    "docs/explanation/internals.md",
    "docs/explanation/mcp-surface.md",
    "docs/explanation/observability.md",
    "docs/explanation/reranking.md",
    "docs/explanation/search-evaluation.md",
    "docs/explanation/sources.md",
    "docs/explanation/trade-offs.md",
    "docs/how-to/agents.md",
    "docs/how-to/embeddings.md",
    "docs/how-to/evaluate-with-agents.md",
    "docs/how-to/golden-questions.md",
    "docs/how-to/reranking.md",
    "docs/reference/data-layout.md",
    "docs/reference/mcp-tools.md",
    "docs/reference/telemetry/embed.md",
    "docs/reference/telemetry/fetch.md",
    "docs/reference/telemetry/index.md",
    "docs/reference/telemetry/prepare.md",
    "docs/tutorials/first-mirror.md",
    "spikes/README.md",
)
# The four kinds of page, by Diataxis, each a folder of docs/.
KINDS = frozenset({"tutorials", "how-to", "reference", "explanation"})
# A fragment naming lines, as GitHub's view of a file reads it: lines move, names stay.
LINES = re.compile(r"L\d+(-L\d+)?")
# The program's name as a word of its own, not part of a path or of another name.
PROGRAM = re.compile(r"(?<![\w/.~-])kb-mcp(?![\w/.-])")
# A line of a block of shell, with the lines that its continuations join to it.
SHELL_LINE = re.compile(r"^(?:.*\\\n)*.*$", re.MULTILINE)
# A word that sets a variable for the command that follows it.
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
# A word of a line of shell, its quotes and escapes kept, so that a quoted `;`, `>` or
# `#` stays text; or a run of `;`, `|` and `&`, which no space need part from the word
# before. An `&` that touches a `>`, as in `2>&1` and `&>`, is the redirection's; a
# quote left open takes the rest of the line, for shlex to refuse.
SHELL_WORD = re.compile(
    r"""(?: >& | &> | [^\s'"\\;|&] | \\.? | '[^']*' | "(?:[^"\\]|\\.)*" | ['"].* )+
    | [;|&]+""",
    re.VERBOSE,
)
# Words that end one command and begin the next: a pipe or a list.
SEPARATORS = frozenset({"|", "|&", "||", "&", "&&", ";"})
# A redirection, which the shell takes out of a command's words: `<`, or an output
# redirection with its file, such as `2>fetch.log` or `2>&1`, or without it, such as `>`,
# the next word then being its file. A placeholder such as `<missing-file>` stays an
# argument.
REDIRECTION = re.compile(r"[\d&]?>>?&?(?P<file>.*)|<<?")
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


def test_no_page_names_a_plan_but_those_that_still_tell_their_history(
    checkout: frozenset[str],
) -> None:
    """A page says what is true now; a plan's number is history, kept in ``docs/work/``.

    The pages that name plans when this check came are listed, so that the list only
    shrinks; no other page may name one. A link to a record that does not say "plan" is
    not seen.
    """
    pages = sorted(
        path for path in checkout if path.endswith(".md") and not path.startswith("docs/work/")
    )
    naming = [path for path in pages if PLAN_NUMBER.search((ROOT / path).read_text("utf-8"))]
    assert [path for path in naming if path not in TELLING_HISTORY] == []
    assert [path for path in TELLING_HISTORY if path not in naming] == []


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


def shell_commands(line: str) -> list[list[str]]:
    """Split a line into its commands, each the words that a shell gives it.

    A command ends at a pipe or a list; a word that begins with ``#`` begins a comment,
    left out; a redirection is left out with its file, and the words after it stay the
    command's, as the shell passes them on. Then the quotes come off each word, so that
    a quoted ``;``, ``>`` or ``#`` is text. Raises ValueError for a quote left open.
    """
    commands: list[list[str]] = [[]]
    words = iter(SHELL_WORD.findall(line))
    for word in words:
        if word.startswith("#"):
            break
        if word in SEPARATORS:
            commands.append([])
        elif redirection := REDIRECTION.fullmatch(word):
            if not redirection["file"]:
                next(words, None)
        else:
            commands[-1] += shlex.split(word)
    return [command for command in commands if command]


def program_arguments(commands: list[list[str]]) -> list[list[str]]:
    """Give the arguments that each of a line's commands gives the program.

    In a command that names the program, it is the command word after any
    ``NAME=value``, after ``uv run``, inside the quoted command of ``sops exec-env
    <file> '...'`` or of ``eval "$(...)"``, or after the ``--`` of ``claude mcp add``.
    Raises ValueError for a command that names the program in any other form, or whose
    inner command does not name it in one of these.
    """
    given: list[list[str]] = []
    for command in commands:
        if not any(PROGRAM.search(word) for word in command):
            continue
        match list(itertools.dropwhile(ASSIGNMENT.match, command)):
            case ["kb-mcp", *arguments]:
                given.append(arguments)
                continue
            case ["uv", "run", *words]:
                inner = [words]
            case ["sops", "exec-env", *_, quoted]:
                inner = shell_commands(quoted)
            case ["claude", "mcp", "add", *added] if "--" in added:
                inner = [added[added.index("--") + 1 :]]
            case ["eval", text] if text.startswith("$(") and text.endswith(")"):
                inner = shell_commands(text[2:-1])
            case _:
                inner = []
        found = program_arguments(inner)
        if not found:
            message = "names the program in a form that program_arguments does not read"
            raise ValueError(message)
        given += found
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
                commands = program_arguments(shell_commands(given))
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
    """The command's parser takes ``--dry`` for fetch's ``--dry-run``; the check's does not."""
    assert parser().parse_args(["fetch", "--dry"]).dry_run is True
    said = io.StringIO()
    with pytest.raises(SystemExit) as stopped, contextlib.redirect_stderr(said):
        parser(Unabbreviated).parse_args(["fetch", "--dry"])
    assert stopped.value.code == ExitStatus.REFUSED
    assert said.getvalue().endswith("unrecognized arguments: --dry\n")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "kb-mcp check && kb-mcp fetch --simulate",
            [["check"], ["fetch", "--simulate"]],
        ),
        ("cd ~&& kb-mcp fetch --simulate", [["fetch", "--simulate"]]),
        (
            "kb-mcp fetch --since 7d&&kb-mcp fetches",
            [["fetch", "--since", "7d"], ["fetches"]],
        ),
        ("kb-mcp fetch|kb-mcp fetches", [["fetch"], ["fetches"]]),
        (
            "kb-mcp fetch --format json 2>/dev/null | jq .exit_status",
            [["fetch", "--format", "json"]],
        ),
        (
            "kb-mcp fetch 2>&1 | tee x; kb-mcp check &>check.log",
            [["fetch"], ["check"]],
        ),
        ("kb-mcp fetch >&2", [["fetch"]]),
        ("kb-mcp fetch 2>fetch.log --simulate", [["fetch", "--simulate"]]),
        ("kb-mcp fetch &>fetch.log --simulate", [["fetch", "--simulate"]]),
        ("kb-mcp fetch 2>&1 --simulate", [["fetch", "--simulate"]]),
        ("kb-mcp fetch > fetch.log --simulate", [["fetch", "--simulate"]]),
        (
            "kb-mcp fetch --detail detailed#x # look first, it's cheap",
            [["fetch", "--detail", "detailed#x"]],
        ),
        ("# kb-mcp fetch asks before it writes", []),
        (
            "kb-mcp search '>5 minutes' ';' '#x' --simulate",
            [["search", ">5 minutes", ";", "#x", "--simulate"]],
        ),
        (
            "kb-mcp eval --golden <missing-file>",
            [["eval", "--golden", "<missing-file>"]],
        ),
        (
            "sops exec-env ~/a.sops.json 'kb-mcp downlod --yes' 2>download.log",
            [["downlod", "--yes"]],
        ),
        (
            "sops exec-env ~/a.sops.json 'kb-mcp check; kb-mcp fetch'",
            [["check"], ["fetch"]],
        ),
        (
            """sops exec-env ~/a.sops.json 'A="$B" uv run kb-mcp check' | tee x""",
            [["check"]],
        ),
        ('eval "$(kb-mcp completion zsh)"', [["completion", "zsh"]]),
        ("claude mcp add --scope user kb-mcp -- kb-mcp", [[]]),
    ],
)
def test_the_check_of_documented_commands_reads_a_line_as_a_shell_does(
    line: str, expected: list[list[str]]
) -> None:
    """Each command of a line gives the program the words that bash would give it.

    A pipe or a list ends a command, spaced or not; a redirection is not the program's,
    though the words after it are; a comment begins at a word that begins with ``#``; a
    quoted word is text, whatever it holds.
    """
    assert program_arguments(shell_commands(line)) == expected


@pytest.mark.parametrize(
    ("line", "refusal"),
    [
        ("time kb-mcp fetch", "names the program"),
        ("uv run --no-sync kb-mcp fetch", "names the program"),
        ("sops exec-env ~/a.sops.json 'time kb-mcp fetch' >x", "names the program"),
        (
            "claude mcp add kb-mcp -- ~/.local/bin/kb-mcp serve",
            "names the program",
        ),
        ("kb-mcp fetch --since '7d", "No closing quotation"),
    ],
)
def test_the_check_of_documented_commands_refuses_a_line_it_cannot_read(
    line: str, refusal: str
) -> None:
    """A command that names the program in a form the check does not read is refused."""
    with pytest.raises(ValueError, match=refusal):
        program_arguments(shell_commands(line))


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
        command=sys.executable, args=["-m", "kb_mcp"], env={"HOME": str(tmp_path)}
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
    that ``embed`` embeds with. A line that pulls another is cited, and so is
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


def code_of(text: str) -> str:
    """Give a module's syntax tree, its docstrings, worded for their reader, left out."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
            and ast.get_docstring(node) is not None
        ):
            node.body = node.body[1:]
    return ast.dump(tree)


def test_the_how_to_for_a_source_gives_the_code_of_the_memo_that_the_tests_run() -> None:
    """Each of its files, under the page's names, is the memo package's, file for file.

    ``tests/test_memo_source.py`` registers and runs that package, so a change that it
    must follow, such as a key added to the front matter or to a preparer's result, cannot
    leave the page telling a contributor to write what fails. A file created, or one that
    it lacks, is named.
    """
    folder = f"src/{NOTES_PACKAGE.replace('.', '/')}/"
    created = {
        path.removeprefix(folder): body
        for path, body in CREATED.findall(ADD_A_SOURCE.read_text("utf-8"))
        if path.startswith(folder)
    }
    memo = {
        path.relative_to(MEMO_PACKAGE).as_posix(): re.sub(
            "|".join(MEMO_NAMES),
            lambda found: MEMO_NAMES[found[0]],
            path.read_text("utf-8"),
        )
        for path in MEMO_PACKAGE.rglob("*.py")
    }
    assert sorted(created) == sorted(memo)
    assert [path for path, body in memo.items() if code_of(created[path]) != code_of(body)] == []


def test_the_how_to_for_a_source_gives_the_checkout_s_registry_and_contracts_and_its_own() -> None:
    """Its lines of steps 6 and 7 are those of the checkout, with the new connector among them.

    Each in the order that the registry's rule and the contract's list keep; so a connector
    added, or a contract's list changed, is said on the page too. The page's own source
    aside on both sides, as a reader who follows it registers that source.
    """
    page = ADD_A_SOURCE.read_text("utf-8")
    line = re.search(r"^CONNECTORS = \((.*)\)$", page, re.MULTILINE)
    registry = re.search(r"^CONNECTORS = \((.*)\)$", REGISTRY.read_text("utf-8"), re.MULTILINE)
    assert line is not None
    assert registry is not None
    names = line[1].lower().split(", ")
    assert names == sorted(names)
    assert [name for name in names if name != "notes"] == registry[1].lower().split(", ")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    contracts = {each.get("id"): each for each in pyproject["tool"]["importlinter"]["contracts"]}
    listed = re.search(r"^modules = (\[.*\])$", page, re.MULTILINE)
    assert listed is not None
    modules = json.loads(listed[1])
    assert NOTES_PACKAGE in modules
    assert [each for each in modules if each != NOTES_PACKAGE] == [
        each for each in contracts["I"]["modules"] if each != NOTES_PACKAGE
    ]
    assert f'"{NOTES_PACKAGE}",' in page.splitlines()
    assert "kb_mcp.sources.worklog" in contracts["K"]["source_modules"]
