"""The glossary stays the one owner of the program's words, true to the code: plan 052.

Each term of ``docs/reference/glossary.md`` says where it lives in the code, what a user
meets of it, or that it is a word of the docs alone, and each name that a user meets is
one of the reference pages'. No two classes or ``type`` aliases at the top of the
package's modules share a name. Each name that a term retires is gone from the code and
from the pages, but where its line keeps it.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest
from markdown_it import MarkdownIt

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "kb_mcp"
GLOSSARY = "docs/reference/glossary.md"
# The pages that give each name a user meets, and its meaning.
REFERENCE = (
    "docs/reference/commands.md",
    "docs/reference/settings.md",
    "docs/reference/mcp-tools.md",
    "docs/reference/data-layout.md",
    *sorted(
        path.relative_to(ROOT).as_posix() for path in ROOT.glob("docs/reference/telemetry/*.md")
    ),
)
HEADING = re.compile(r"^(#{2,3}) (.+)$", re.MULTILINE)
# A line under a term, with the lines that continue it, each indented by two spaces.
LINE = re.compile(r"^- (In the code|User-facing|Retires):(.*(?:\n  .*)*)", re.MULTILINE)
SPAN = re.compile(r"`([^`]+)`")
# A name, not inside a longer name, dotted or hyphenated, at an end of it that is a word
# character.
WHOLE = r"(?:(?<=[^\w.-])|^|(?=[^\w.-])){}(?:(?=[^\w.-])|$|(?<=[^\w.-]))"
DOCS_ALONE = "A word of the docs alone"
# An item of a "Retires:" line: a name in code or a phrase in quotes, then the files that
# keep it, if any.
ITEM = re.compile(r'(?:`(?P<name>[^`]+)`|"(?P<phrase>[^"]+)")(?: \(kept in (?P<kept>[^)]+)\))?')


class Retired(NamedTuple):
    """A name or phrase that a term retires, and the files that keep it, from the root."""

    term: str
    name: str | None
    phrase: str | None
    kept: tuple[str, ...]

    def kept_in(self, path: str) -> bool:
        """Say whether its line keeps it in this file, or in a folder that holds it."""
        return any(path == each or path.startswith(f"{each.rstrip('/')}/") for each in self.kept)


@pytest.fixture(scope="module")
def terms() -> list[tuple[str, str]]:
    """Read the glossary's terms, each by its name, with its text up to the next heading."""
    text = (ROOT / GLOSSARY).read_text("utf-8")
    found = list(HEADING.finditer(text))
    return [
        (heading[2], text[heading.end() : after.start() if after else len(text)])
        for heading, after in zip(found, [*found[1:], None], strict=True)
        if heading[1] == "###"
    ]


@pytest.fixture(scope="module")
def retired(terms: list[tuple[str, str]]) -> list[Retired]:
    """Read each item of each term's "Retires:" line."""
    return [
        Retired(term, item["name"], item["phrase"], tuple(SPAN.findall(item["kept"] or "")))
        for term, body in terms
        for kind, line in LINE.findall(body)
        if kind == "Retires"
        for item in ITEM.finditer(line)
    ]


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    """Read each page of ``docs/`` but the plans' records and the glossary, by its path."""
    return {
        path.relative_to(ROOT).as_posix(): path.read_text("utf-8")
        for path in sorted(ROOT.glob("docs/**/*.md"))
        if not path.relative_to(ROOT).as_posix().startswith(("docs/work/", GLOSSARY))
    }


def test_each_term_says_where_it_lives_or_what_a_user_meets_of_it_once(
    terms: list[tuple[str, str]],
) -> None:
    """A term has its code, its user-facing names or the docs alone; each name is referenced.

    A user-facing name is a code span of the line, which a code span or a block of code of
    a reference page holds, not inside a longer name. No two terms share a name.
    """
    code = [
        token.content
        for page in REFERENCE
        for block in MarkdownIt("commonmark")
        .enable("table")
        .parse((ROOT / page).read_text("utf-8"))
        for token in [block, *(block.children or [])]
        if token.type in {"code_inline", "fence"}
    ]
    problems = [
        f"{name}: {count} terms"
        for name, count in Counter(n for n, _ in terms).items()
        if count > 1
    ]
    for name, body in terms:
        lines = dict(LINE.findall(body))
        if not (
            {"In the code", "User-facing"} & lines.keys() or DOCS_ALONE in " ".join(body.split())
        ):
            problems.append(f"{name}: no line In the code: nor User-facing:, nor {DOCS_ALONE}")
        problems.extend(
            f"{name}: `{each}` is in no reference page"
            for each in SPAN.findall(lines.get("User-facing", ""))
            if not any(re.search(WHOLE.format(re.escape(each)), held) for held in code)
        )
    assert problems == []


def test_no_two_classes_or_type_aliases_of_the_package_share_a_name() -> None:
    """At the top of the package's modules, each class and ``type`` alias has its own name."""
    defined: Counter[str] = Counter()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.parse(path.read_bytes(), path).body:
            match node:
                case ast.ClassDef(name=name) | ast.TypeAlias(name=ast.Name(id=name)):
                    defined[name] += 1
    shared = {name for name, count in defined.items() if count > 1}
    assert [f"{name}: shared by two modules or more" for name in sorted(shared)] == []


def test_each_retired_name_is_gone_from_the_code_and_the_pages_but_where_kept(
    retired: list[Retired], pages: dict[str, str]
) -> None:
    """A retired name is no name of the syntax of ``src/`` and ``tests/``, nor a word of a page.

    In the syntax: a definition, a variable, an attribute, an argument, a keyword or an
    import, each part of a dotted one. In a page, as a whole word with its case. A retired
    module, ``name.py``, is also no file of ``src/``.
    """
    held = {
        path.relative_to(ROOT).as_posix(): {
            part
            for node in ast.walk(ast.parse(path.read_bytes(), path))
            for field in ("id", "attr", "arg", "name", "asname", "module")
            if isinstance(value := getattr(node, field, None), str)
            for part in value.split(".")
        }
        for path in sorted([*ROOT.glob("src/**/*.py"), *ROOT.glob("tests/**/*.py")])
    }
    modules = {path.name: path.relative_to(ROOT).as_posix() for path in ROOT.glob("src/**/*.py")}
    found = []
    for each in (item for item in retired if item.name):
        word = re.compile(rf"(?<!\w){re.escape(each.name)}(?!\w)")
        where = [path for path, names in held.items() if each.name in names]
        where += [path for path, text in pages.items() if word.search(text)]
        where += [modules[each.name]] if each.name in modules else []
        found += [
            f"{each.term}: `{each.name}` in {path}" for path in where if not each.kept_in(path)
        ]
    assert found == []


def test_each_retired_phrase_is_gone_from_the_code_and_the_pages_but_where_kept(
    retired: list[Retired], pages: dict[str, str]
) -> None:
    """A retired phrase is in no page, nor in the text of ``src/`` and ``tests/``.

    In any case, as whole words, plural or not, across a line's end or a comment's mark.
    """
    texts = pages | {
        path.relative_to(ROOT).as_posix(): path.read_text("utf-8")
        for path in sorted([*ROOT.glob("src/**/*.py"), *ROOT.glob("tests/**/*.py")])
    }
    found = []
    for each in (item for item in retired if item.phrase):
        words = r"[\s#]+".join(map(re.escape, each.phrase.split()))
        phrase = re.compile(rf"(?<!\w){words}s?(?!\w)", re.IGNORECASE)
        found += [
            f'{each.term}: "{each.phrase}" in {path}'
            for path, text in texts.items()
            if phrase.search(text) and not each.kept_in(path)
        ]
    assert found == []
