"""The concepts page holds no more entries than its ceiling, and homes each type held once.

An entry is a level-three heading under *Core concepts* or *Context vocabulary* of
``docs/reference/concepts.md``. ``ENTRIES`` gives the ceiling and the target, the
budget's most; a plan raises the ceiling only by declaring the new concept in its
*Concepts*, approved by the user. Each type of a context converged, or of ``HOMED``, has
one home on the page, as the code's layout says in T8, and *Mechanics* homes at most
``MECHANICS`` types.
"""

from __future__ import annotations

import ast
import itertools
from collections import Counter, defaultdict
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

from tests.test_code_size import CONVERGED, PACKAGE, PARTS, named_types, places, written

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

# The ceiling of the page's entries, then the target.
ENTRIES = (29, 35)
# The contexts whose types the check of homes holds, before they converge.
HOMED = ("kernel", "observability", "config")
# The most types that *Mechanics* may home.
MECHANICS = 20
PAGE = Path(__file__).parents[1] / "docs" / "reference" / "concepts.md"
SRC = PAGE.parents[2] / "src"
# Markdown as GitHub reads it, tables included.
PARSER = MarkdownIt("commonmark").enable("table")
# The sections whose level-three headings are entries.
SECTIONS = frozenset({"Core concepts", "Context vocabulary"})


def entries(text: str) -> int:
    """Count the entries of a concepts page, read as GitHub renders it.

    A level-two heading opens a section, which the next of level one or two ends.
    """
    section, count = None, 0
    # Each inline token, the text of a heading, follows the token that opens it.
    for before, block in itertools.pairwise(MarkdownIt("commonmark").parse(text)):
        if before.type == "heading_open" and before.tag in {"h1", "h2"}:
            section = block.content if before.tag == "h2" else None
        elif before.type == "heading_open" and before.tag == "h3" and section in SECTIONS:
            count += 1
    return count


def homes(text: str) -> dict[str, list[str]]:
    """Give the types that each place of a concepts page homes, by the place's heading.

    A place is an entry, whose paragraph or bullet **Home.** names them, or a table, such
    as *Mechanics*, whose column Home does; each in a code span, a link's being no home.
    """
    found: dict[str, list[str]] = defaultdict(list)
    place, header, column = "", [], 0
    # Each inline token, the text of a block or a cell, follows the token that opens it.
    for before, token in itertools.pairwise(PARSER.parse(text)):
        column = 0 if token.type == "tr_open" else column + (token.type in {"th_open", "td_open"})
        if before.type == "heading_open":
            place, header = token.content, []
        elif before.type == "th_open":
            header.append(token.content)
        # The parser opens a paragraph's children with an empty text.
        children = [
            child for child in token.children or [] if child.content or child.type != "text"
        ]
        opening = [(child.type, child.content) for child in children[:3]]
        if opening == [("strong_open", ""), ("text", "Home."), ("strong_close", "")] or (
            before.type == "td_open" and header[column - 1 : column] == ["Home"]
        ):
            depth = 0
            for child in children:
                depth += {"link_open": 1, "link_close": -1}.get(child.type, 0)
                found[place] += [child.content] if child.type == "code_inline" and not depth else []
    return dict(found)


def unhomed(
    page: str,
    src: Path,
    contexts: Collection[str],
    parts: Mapping[str, Sequence[str]] = MappingProxyType({}),
) -> list[str]:
    """Say where the homes of a concepts page break T8 for the types of ``contexts``.

    A type held, of a context of ``contexts`` or of a part of ``parts`` that it names,
    without a home; a home naming no type of ``src``; a type homed twice; a type held whose
    name ``src`` defines twice. A type that a call makes has no name, and needs no home.
    """
    package = src / PACKAGE
    trees = {path: ast.parse(path.read_bytes(), path) for path in sorted(package.rglob("*.py"))}
    classes = {
        node.name
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    defined: dict[str, list[str]] = defaultdict(list)
    held = set()
    for path, tree in trees.items():
        where = places(path.relative_to(package).with_suffix("").parts, parts)
        for name in named_types(tree, classes):
            defined[name].append(where[0])
            held |= {name} if set(where) & set(contexts) else set()
    homed = homes(page)
    counted = Counter(name for names in homed.values() for name in names)
    found = [
        f"`{name}` ({' and '.join(defined[name])}): no home" for name in sorted(held - set(counted))
    ]
    found += [
        f"`{name}` ({place}): a home naming no type"
        for place, names in homed.items()
        for name in names
        if name not in defined
    ]
    found += [f"`{name}`: homed {count} times" for name, count in counted.items() if count > 1]
    found += [
        f"`{name}`: defined {len(defined[name])} times, in {' and '.join(defined[name])}"
        for name in sorted(held)
        if len(defined[name]) > 1
    ]
    return found


def test_entries_are_counted_under_both_sections() -> None:
    """A level-three heading under either section counts; no other heading, nor code.

    A level-one or level-two heading ends the section.
    """
    page = (
        "# Concepts\n\n### before\n\n## Core concepts\n\n### connector\n\n#### deeper\n\n"
        "```markdown\n### in code\n```\n\n### source\n\n## Context vocabulary\n\n"
        "### account\n\n# Appendix\n\n### after\n\n## Core concepts\n\n### person\n\n"
        "## Elsewhere\n\n### other\n"
    )
    assert entries(page) == len(["connector", "source", "account", "person"])


def test_the_concepts_stay_within_their_ceiling() -> None:
    """The page's entries are at most the ceiling, itself at most the target."""
    ceiling, target = ENTRIES
    assert entries(PAGE.read_text("utf-8")) <= ceiling <= target


# A page that homes each type of ``SOURCE``, in each of T8's forms: a core entry's
# paragraph, a context entry's bullet, and a row of *Mechanics*. Its link is no home.
HOMING = """# Concepts

## Core concepts

### run

**Definition.** What the program does for one command.

**In the code.** [`Linked`](../../src/kb_mcp/ctx/mod.py).

**Home.** `Invocation` and `Running`.

## Context vocabulary

### setting

One named value.

- **In the code.** [`Ignored`](../../src/kb_mcp/ctx/mod.py).
- **Home.** `Ignored`.

## Mechanics

| Role | Home | Why |
|---|---|---|
| utility | `Fields` | the strict reader of JSON |

## Kept apart

- `Invocation` and `Running`: what one start is asked, and its state.
"""
SOURCE = "class Invocation:\n    pass\n\n\nclass Running:\n    pass\n\n\n"
SOURCE += "class Ignored:\n    pass\n\n\nclass Fields:\n    pass\n"


def checked(tmp_path: Path, page: str, files: Mapping[str, str]) -> list[str]:
    """Say where ``page`` and the package of ``files``, beside ``SOURCE``, part, for ``ctx``."""
    src = written(tmp_path, {"kb_mcp/ctx/mod.py": SOURCE, **files})
    return unhomed(page, src, ("ctx",))


def test_each_form_of_a_home_homes_its_types(tmp_path: Path) -> None:
    """A core entry's paragraph, a context entry's bullet and a row of *Mechanics*."""
    assert checked(tmp_path, HOMING, {}) == []
    assert homes(HOMING) == {
        "run": ["Invocation", "Running"],
        "setting": ["Ignored"],
        "Mechanics": ["Fields"],
    }


def test_a_type_without_a_home_is_found(tmp_path: Path) -> None:
    """A type of a context held, homed nowhere; one of a context not held needs none."""
    files = {
        "kb_mcp/ctx/other.py": "class Orphan:\n    pass\n",
        "kb_mcp/free/mod.py": "class Free:\n    pass\n",
    }
    assert checked(tmp_path, HOMING, files) == ["`Orphan` (ctx): no home"]


def test_a_home_naming_no_type_is_found(tmp_path: Path) -> None:
    """A name in a home that no module of ``src/`` defines as a type, misspelt or gone."""
    page = HOMING.replace("`Invocation` and `Running`.", "`Invocation`, `Running` and `Gone`.")
    assert checked(tmp_path, page, {}) == ["`Gone` (run): a home naming no type"]


def test_a_type_homed_twice_is_found(tmp_path: Path) -> None:
    """Two homes name one type: in two places, or twice in one."""
    page = HOMING.replace("| utility | `Fields` |", "| utility | `Fields` and `Running` |")
    assert checked(tmp_path, page, {}) == ["`Running`: homed 2 times"]


def test_a_name_defined_twice_is_found(tmp_path: Path) -> None:
    """A type held whose name another module defines too, of any context: a home is ambiguous."""
    files = {"kb_mcp/free/mod.py": "class Fields:\n    pass\n"}
    assert checked(tmp_path, HOMING, files) == ["`Fields`: defined 2 times, in ctx and free"]


def test_a_link_in_the_code_is_no_home(tmp_path: Path) -> None:
    """A type that the code links, in its **In the code.** or in a **Home.**, is not homed."""
    files = {"kb_mcp/ctx/linked.py": "class Linked:\n    pass\n"}
    assert checked(tmp_path, HOMING, files) == ["`Linked` (ctx): no home"]
    page = HOMING.replace("**Home.** `Invocation`", "**Home.** [`Invocation`](mod.py)")
    assert checked(tmp_path / "linked", page, {}) == ["`Invocation` (ctx): no home"]


def test_a_type_made_by_a_factory_needs_no_home(tmp_path: Path) -> None:
    """A type that a call makes, which the budget counts, has no name to home."""
    made = 'Made = create_model("Made")\nIdentifier = NewType("Identifier", str)\n'
    assert checked(tmp_path, HOMING, {"kb_mcp/ctx/made.py": made}) == []


def test_too_many_mechanics_are_found() -> None:
    """Each type that a row of *Mechanics* homes counts, several in one cell too."""
    rows = "".join(
        f"| utility | `A{row}` and `B{row}` | why |\n" for row in range(MECHANICS // 2 + 1)
    )
    page = HOMING.replace("| utility | `Fields` | the strict reader of JSON |\n", rows)
    assert len(homes(page)["Mechanics"]) > MECHANICS


def test_every_type_of_a_converged_or_homed_context_has_one_home() -> None:
    """T8 on the page: each type of a context or part converged, or homed, has one home.

    Every home names a type of ``src/``, and no name of a type held is defined twice.
    """
    assert unhomed(PAGE.read_text("utf-8"), SRC, (*CONVERGED, *HOMED), PARTS) == []


def test_mechanics_stay_within_their_ceiling() -> None:
    """*Mechanics* homes at most ``MECHANICS`` types."""
    assert len(homes(PAGE.read_text("utf-8")).get("Mechanics", [])) <= MECHANICS
