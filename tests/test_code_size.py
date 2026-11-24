"""The source's size, measured per context, and held to its ceilings and to the budget.

``measure`` counts each context's lines of code, files, types, largest module and comment
lines; ``breaches`` says where the measures break their ceilings, the ceilings their
bounds, or a converged context or part its targets; ``overspent`` where the targets pass
the budget. ``src/`` is held to the tables below, plain literals that a plan edits: the
trade-offs' "A budget of twelve thousand lines" says why.
"""

from __future__ import annotations

import ast
import io
import math
import re
import tokenize
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

type Measure = tuple[int, int, int, int, int]  # lines, files, types, largest, comments
type Target = tuple[int, int, int, int]  # lines, files, types, largest

# Each context's ceilings: no measure may pass its own, nor a ceiling stand above its
# bound, so that they fall as the context shrinks; a plan raises one on the user's word.
CEILINGS = {
    "sources/atlassian": (5_150, 35, 81, 1_050, 190),
    "search": (4_500, 20, 78, 1_250, 220),
    "cli": (4_450, 56, 33, 300, 80),
    "sources/worklog": (2_150, 23, 23, 750, 90),
    "evaluation": (1_750, 13, 38, 600, 60),
    "mcp": (1_450, 6, 11, 950, 50),
    "config": (850, 5, 18, 750, 40),
    "observability": (800, 6, 16, 450, 50),
    "mirror": (850, 12, 12, 300, 60),
    "kernel": (450, 5, 20, 200, 60),
    "sources": (400, 5, 19, 250, 30),
    "(root)": (100, 3, 2, 100, 10),
}
# Each context's targets, and each converging part's, which hold once it converges; the
# contexts' leave the rest of the budget in reserve.
TARGETS = {
    "sources/atlassian": (2_600, 10, 36, 700),
    "search": (2_200, 8, 30, 700),
    "cli": (2_000, 10, 16, 700),
    "sources/worklog": (900, 6, 8, 700),
    "evaluation": (1_000, 5, 16, 700),
    "mcp": (800, 4, 6, 700),
    "config": (550, 3, 10, 700),
    "observability": (400, 3, 6, 700),
    "mirror": (300, 4, 6, 700),
    "kernel": (200, 3, 8, 700),
    "sources": (150, 4, 8, 700),
    "(root)": (10, 2, 0, 700),
}
BUDGET = (12_000, 70, 160, 700)
# Each part of a context that a plan converges apart, as "<context>:<part>", by the paths
# of its modules under the package, each a module or a package, without ".py".
PARTS = {}
# The contexts and parts that plans have converged, which their targets hold.
CONVERGED = ()

ROOT = Path(__file__).parents[1]
PACKAGE = "kb_mcp"
# What each place of a measure counts; a target's are the first four.
MEASURES = ("lines", "files", "types", "largest", "comments")
# The tokens that hold no code: a comment, and those that mark where a line, a block or
# the file starts and ends.
NO_CODE = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)
# What a call makes a type by, wherever it is called; and type(name, bases, namespace).
MAKERS = frozenset(
    {
        "NewType",
        "TypeVar",
        "ParamSpec",
        "TypeVarTuple",
        "TypeAliasType",
        "TypedDict",
        "NamedTuple",
        "namedtuple",
        "create_model",
        "make_dataclass",
        "Enum",
        "IntEnum",
        "StrEnum",
        "Flag",
        "IntFlag",
    }
)
TYPE_ARGUMENTS = 3
# The typing and collection forms whose subscript, assigned to a capitalised name at the
# top of a module, is a type.
FORMS = frozenset(
    {
        "Literal",
        "Annotated",
        "Callable",
        "Union",
        "Optional",
        "ClassVar",
        "Final",
        "Type",
        "tuple",
        "list",
        "dict",
        "set",
        "frozenset",
        "type",
        "Mapping",
        "MutableMapping",
        "Sequence",
        "Iterable",
        "Iterator",
        "Collection",
        "Generator",
        "Awaitable",
        "Coroutine",
        "AsyncIterator",
        "AsyncIterable",
        "Counter",
        "defaultdict",
        "deque",
    }
)
# What a side of such a union may be besides a form, a class of src/ and None.
PLAIN = frozenset({"int", "str", "float", "bool", "bytes", "object"})


def name_of(node: ast.AST) -> str | None:
    """Give the name that an expression is, or ends with, as ``Literal`` of ``typing.Literal``."""
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
    return None


def made(node: ast.AST | None) -> bool:
    """Say whether a node is a call that makes a type."""
    match node:
        case ast.Call(func=called, args=arguments):
            name = name_of(called)
            return name in MAKERS or (name == "type" and len(arguments) == TYPE_ARGUMENTS)
    return False


def formed(value: ast.expr, classes: Collection[str]) -> bool:
    """Say whether a value assigned is a type: a form, or a class of ``classes``, subscripted.

    Or a union whose every side is one, or such a union, a class, a plain type or None.
    """
    match value:
        case ast.Subscript(value=subscripted):
            return name_of(subscripted) in FORMS or name_of(subscripted) in classes
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return all(
                formed(side, classes)
                or name_of(side) in PLAIN
                or name_of(side) in classes
                or (isinstance(side, ast.Constant) and side.value is None)
                for side in (left, right)
            )
    return False


def named_types(tree: ast.Module, classes: Collection[str]) -> list[str]:
    """Name the types that a module defines, but those that a call makes, which have no name.

    ``classes`` is every class of ``src/``. Anywhere: a class, a ``type`` statement. At its
    top, or under an ``if`` there: a name annotated ``TypeAlias``, unless a call makes it,
    and a capitalised name assigned a type.
    """
    names = [
        node.name if isinstance(node, ast.ClassDef) else ast.unparse(node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.TypeAlias))
    ]
    top = list(tree.body)
    while top:
        match top.pop():
            case ast.If(body=body, orelse=orelse):
                top += [*body, *orelse]
            case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation, value=value) if (
                name_of(annotation) == "TypeAlias" and not made(value)
            ):
                names.append(name)
            case ast.Assign(targets=[ast.Name(id=name)], value=value) if name[0].isupper():
                names += [name] if formed(value, classes) else []
    return names


def typed(tree: ast.Module, classes: Collection[str]) -> int:
    """Count the types that a module defines, ``classes`` being every class of ``src/``.

    Those that ``named_types`` names, and each call anywhere that makes one.
    """
    return len(named_types(tree, classes)) + sum(made(node) for node in ast.walk(tree))


def places(module: Sequence[str], parts: Mapping[str, Sequence[str]]) -> list[str]:
    """Name what a module is measured in: its context, then each part of ``parts`` holding it.

    ``module`` is its path under the package, by its names, without ``.py``.
    """
    match module:
        case ("__init__",) | ("__main__",):
            context = "(root)"
        case ("sources", source, _, *_):
            context = f"sources/{source}"
        case (first, *_):
            context = first
    named = "/".join(module)
    return [
        context,
        *(
            part
            for part, paths in parts.items()
            if any(named == each or named.startswith(f"{each}/") for each in paths)
        ),
    ]


def measure(
    src: Path, parts: Mapping[str, Sequence[str]] = MappingProxyType({})
) -> dict[str, Measure]:
    """Measure each context of the package under ``src``, then each part of ``parts``.

    A part is named by the paths of its modules under the package, each a module or a
    package, without ``.py``. Raises ValueError naming each file under ``src`` that is
    neither a module of the package nor ignored: a cache's, a hidden file, a backup.
    """
    package = src / PACKAGE
    files = [
        path
        for path in sorted(src.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.relative_to(src).parts
        and not path.name.startswith(".")
        and not path.name.endswith("~")
    ]
    stray = [
        path.relative_to(src).as_posix()
        for path in files
        if path.suffix != ".py" or package not in path.parents
    ]
    if stray:
        message = f"neither a module of {PACKAGE} nor ignored: {', '.join(stray)}"
        raise ValueError(message)
    texts = {path: path.read_text("utf-8") for path in files}
    trees = {path: ast.parse(text, path) for path, text in texts.items()}
    classes = {
        node.name
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    measured: dict[str, Measure] = {}
    for path, text in texts.items():
        code, comments = set(), set()
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comments.add(token.start[0])
            elif token.type not in NO_CODE:
                code.update(range(token.start[0], token.end[0] + 1))
        rows = text.split("\n")
        lines = len([row for row in code if rows[row - 1].strip()])
        types = typed(trees[path], classes)
        for name in places(path.relative_to(package).with_suffix("").parts, parts):
            was = measured.get(name, (0, 0, 0, 0, 0))
            measured[name] = (
                was[0] + lines,
                was[1] + 1,
                was[2] + types,
                max(was[3], lines),
                was[4] + len(comments - code),
            )
    return measured


def breaches(
    measured: Mapping[str, Measure],
    ceilings: Mapping[str, Measure],
    targets: Mapping[str, Target],
    converged: Collection[str],
    parts: Collection[str],
) -> list[str]:
    """Say where the measures break the tables, each breach after its context's or part's name.

    A measure past its ceiling; a ceiling above its bound: lines and the largest module
    rounded up to 50, then 50 more, files one more, types two, comment lines rounded up to
    10, then 10 more; a converged context or part past its targets; a context without a
    ceiling or a target, a part without a target, a ceiling without its context, a
    converged name that names nothing measured.
    """
    contexts = [name for name in measured if name not in parts]
    found = [f"{name}: no ceiling" for name in contexts if name not in ceilings]
    found += [f"{name}: no target" for name in [*contexts, *parts] if name not in targets]
    found += [
        f"{name}: a ceiling, and no such context" for name in ceilings if name not in contexts
    ]
    found += [
        f"{name}: converged, and no context or part of that name measured"
        for name in converged
        if name not in measured
    ]
    for name in (name for name in contexts if name in ceilings):
        lines, files, types, largest, comments = measured[name]
        bound = (
            math.ceil(lines / 50) * 50 + 50,
            files + 1,
            types + 2,
            math.ceil(largest / 50) * 50 + 50,
            math.ceil(comments / 10) * 10 + 10,
        )
        for what, value, ceiling, most in zip(
            MEASURES, measured[name], ceilings[name], bound, strict=True
        ):
            if value > ceiling:
                found.append(f"{name}: {what} {value}, past its ceiling {ceiling}")
            if ceiling > most:
                found.append(f"{name}: a ceiling of {ceiling} {what}, above its bound {most}")
    found += [
        f"{name}: {what} {value}, past its target {target}"
        for name in converged
        if name in measured and name in targets
        for what, value, target in zip(MEASURES[:4], measured[name][:4], targets[name], strict=True)
        if value > target
    ]
    return found


def overspent(targets: Mapping[str, Target], budget: Target, parts: Collection[str]) -> list[str]:
    """Say where the contexts' targets, the parts' aside, pass the budget.

    Their sums of lines, files and types may reach the budget's, what they leave being the
    reserve; no target's largest module, a part's included, may pass the budget's.
    """
    sums = [
        sum(target[place] for name, target in targets.items() if name not in parts)
        for place in range(3)
    ]
    found = [
        f"the contexts' targets: {what} {spent}, past the budget {most}"
        for what, spent, most in zip(MEASURES[:3], sums, budget[:3], strict=True)
        if spent > most
    ]
    found += [
        f"{name}: a target of {target[3]} largest, past the budget {budget[3]}"
        for name, target in targets.items()
        if target[3] > budget[3]
    ]
    return found


def written(root: Path, files: Mapping[str, str]) -> Path:
    """Write each file, by its path under a folder ``src``, in ``root``; give that folder."""
    src = root / "src"
    for name, text in files.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(text, encoding="utf-8")
    return src


def test_a_comment_or_blank_line_is_no_line_of_code(tmp_path: Path) -> None:
    """A line holding a comment alone is a comment line; a blank one is neither."""
    module = "import os\n\n# a comment\n   \ndef f() -> None:\n    # indented\n    return  # end\n"
    assert measure(written(tmp_path, {"kb_mcp/mod.py": module})) == {"mod": (3, 1, 0, 3, 2)}


def test_a_line_in_a_string_is_a_line_of_code(tmp_path: Path) -> None:
    """Each non-blank line of a docstring or another string counts, a comment's look aside."""
    module = (
        '"""A docstring\n\nof three lines, one blank.\n"""\n\n'
        'TEXT = """\n# not a comment\n\nend\n"""\n'
        'NAMED = f"""\n{TEXT}\n"""\n'
    )
    assert measure(written(tmp_path, {"kb_mcp/mod.py": module})) == {"mod": (10, 1, 0, 10, 0)}


MADE_IN_A_FUNCTION = "def make() -> None:\n" + "".join(
    f"    {maker}('X')\n"
    for maker in (
        "typing.NewType",
        "TypeVar",
        "ParamSpec",
        "TypeVarTuple",
        "TypeAliasType",
        "TypedDict",
        "NamedTuple",
        "collections.namedtuple",
        "pydantic.create_model",
        "make_dataclass",
        "enum.Enum",
        "IntEnum",
        "StrEnum",
        "Flag",
        "IntFlag",
    )
)
EVERY_FORM = "".join(
    f"A{index} = {form}[int]\n"
    for index, form in enumerate(
        (
            "Literal",
            "typing.Annotated",
            "Callable",
            "Union",
            "Optional",
            "ClassVar",
            "Final",
            "Type",
            "tuple",
            "list",
            "dict",
            "set",
            "frozenset",
            "type",
            "Mapping",
            "MutableMapping",
            "Sequence",
            "Iterable",
            "Iterator",
            "Collection",
            "Generator",
            "Awaitable",
            "Coroutine",
            "AsyncIterator",
            "AsyncIterable",
            "Counter",
            "defaultdict",
            "deque",
        )
    )
)


@pytest.mark.parametrize(
    ("source", "types"),
    [
        ("class Outer:\n    class Inner:\n        pass\n", 2),
        ("type Pair = tuple[int, int]\n", 1),
        (MADE_IN_A_FUNCTION, 15),
        ("plain = type(1)\nMADE = type('Made', (), {})\n", 1),
        (
            (
                "Alias: TypeAlias = int\nOther: typing.TypeAlias = 'int | None'\n"
                "Identifier: TypeAlias = NewType('Identifier', str)\n"
            ),
            3,
        ),
        (EVERY_FORM, 28),
        ("Boxes = Known[int]\n", 1),
        (
            (
                "Either = Known | int | str | float | bool | bytes | object | None\n"
                "Pair = list[int] | dict[str, int]\nDotted = typing.Optional[int] | None\n"
            ),
            3,
        ),
        (
            (
                "if TYPE_CHECKING:\n    Hint = list[int]\nelif SOMETHING:\n    Other = int | None\n"
                "else:\n    if True:\n        Deep = Known | None\n"
            ),
            3,
        ),
        (
            (
                "def f() -> None:\n    Local = list[int]\n\nlower = list[int]\nMIXED = Known | 3\n"
                "NAMES = OTHER | MORE\nKEY = MAPPING['key']\ntry:\n    Tried = list[int]\n"
                "except ImportError:\n    pass\n"
            ),
            0,
        ),
    ],
)
def test_every_kind_of_type_is_counted(tmp_path: Path, source: str, types: int) -> None:
    """Classes, ``type`` statements and calls anywhere; aliases at the top or under an ``if``.

    ``Known`` is a class of another module of the package, so of ``src/``.
    """
    files = {"kb_mcp/mod.py": source, "kb_mcp/other.py": "class Known:\n    pass\n"}
    assert measure(written(tmp_path, files))["mod"][2] == types


def test_a_context_is_found_for_every_file(tmp_path: Path) -> None:
    """The first package or module under the package; a source's package; and parts."""
    one, three = "X = 1\n", "X = 1\nY = 2\nZ = 3\n"
    files = {
        "kb_mcp/__init__.py": one,
        "kb_mcp/__main__.py": "X = 1\nY = 2\n",
        "kb_mcp/single.py": one,
        "kb_mcp/cli/__init__.py": one,
        "kb_mcp/cli/runs/__init__.py": one,
        "kb_mcp/cli/runs/unit.py": three,
        "kb_mcp/cli/run.py": one,
        "kb_mcp/cli/other.py": one,
        "kb_mcp/sources/__init__.py": one,
        "kb_mcp/sources/registry.py": one,
        "kb_mcp/sources/atlassian/__init__.py": one,
        "kb_mcp/sources/atlassian/fetch/deep.py": one,
    }
    parts = {"cli:runs": ("cli/runs", "cli/run")}
    assert measure(written(tmp_path, files), parts) == {
        "(root)": (3, 2, 0, 2, 0),
        "single": (1, 1, 0, 1, 0),
        "cli": (7, 5, 0, 3, 0),
        "cli:runs": (5, 3, 0, 3, 0),
        "sources": (2, 2, 0, 1, 0),
        "sources/atlassian": (2, 2, 0, 1, 0),
    }


@pytest.mark.parametrize("stray", ["kb_mcp/data.json", "tools/script.py", "setup.py"])
def test_a_stray_file_fails_and_a_cache_does_not(tmp_path: Path, stray: str) -> None:
    """A cache's file, a hidden one and a backup are ignored; any other file fails."""
    files = {
        "kb_mcp/__init__.py": "X = 1\n",
        "kb_mcp/__pycache__/__init__.cpython-314.pyc": "",
        "kb_mcp/__pycache__/stale.py": "X = 1\n",
        "kb_mcp/.DS_Store": "",
        "kb_mcp/.scratch.py": "X = 1\n",
        "kb_mcp/mod.py~": "X = 1\n",
    }
    src = written(tmp_path, files)
    assert measure(src) == {"(root)": (1, 1, 0, 1, 0)}
    written(tmp_path, {stray: "X = 1\n"})
    with pytest.raises(ValueError, match=re.escape(stray)):
        measure(src)


MEASURES_NAMED = ["lines", "files", "types", "largest", "comments"]
# A context's ceilings at the bound of (100, 5, 10, 60, 20), and targets far above.
CEILING = (150, 6, 12, 100, 30)
FAR = (10_000, 100, 100, 10_000)


@pytest.mark.parametrize(("index", "what"), list(enumerate(MEASURES_NAMED)))
def test_each_measure_past_its_ceiling_is_a_breach(index: int, what: str) -> None:
    """At its ceiling, a measure is no breach; one more, it is one, naming it."""
    past = tuple(value + (place == index) for place, value in enumerate(CEILING))
    assert breaches({"ctx": CEILING}, {"ctx": CEILING}, {"ctx": FAR}, (), ()) == []
    found = breaches({"ctx": past}, {"ctx": CEILING}, {"ctx": FAR}, (), ())
    assert [each.startswith("ctx: ") and what in each for each in found] == [True]


@pytest.mark.parametrize(
    ("measured", "bound"),
    [
        ((1387, 5, 9, 896, 31), (1450, 6, 11, 950, 50)),
        ((1400, 0, 0, 50, 30), (1450, 1, 2, 100, 40)),
    ],
)
@pytest.mark.parametrize(("index", "what"), list(enumerate(MEASURES_NAMED)))
def test_a_ceiling_above_its_bound_is_a_breach(
    measured: Measure, bound: Measure, index: int, what: str
) -> None:
    """Lines and the largest module up to the next 50, then 50; files 1; types 2; comments 10.

    A ceiling at its bound is no breach; one more, it is one, naming its measure.
    """
    above = tuple(value + (place == index) for place, value in enumerate(bound))
    assert breaches({"ctx": measured}, {"ctx": bound}, {"ctx": FAR}, (), ()) == []
    found = breaches({"ctx": measured}, {"ctx": above}, {"ctx": FAR}, (), ())
    assert [each.startswith("ctx: ") and what in each for each in found] == [True]


@pytest.mark.parametrize("name", ["ctx", "ctx:part"])
@pytest.mark.parametrize(("index", "what"), list(enumerate(MEASURES_NAMED[:4])))
def test_a_converged_context_or_part_past_its_target_is_a_breach(
    name: str, index: int, what: str
) -> None:
    """Past one of its targets, a context or a part breaks it once converged, not before."""
    target = (100, 4, 6, 200)
    within = (*target, 0)
    measured = {"ctx": within, "ctx:part": within}
    measured[name] = tuple(value + (place == index) for place, value in enumerate(within))
    ceilings = {"ctx": (150, 5, 8, 250, 10)}  # at the bound of within
    targets = {"ctx": target, "ctx:part": target}
    assert breaches(measured, ceilings, targets, (), ("ctx:part",)) == []
    found = breaches(measured, ceilings, targets, (name,), ("ctx:part",))
    assert [each.startswith(f"{name}: ") and what in each for each in found] == [True]


def test_a_context_or_part_without_its_tables_is_a_breach() -> None:
    """A context needs a ceiling and a target, a part a target; a ceiling needs its context."""
    found = breaches(
        {"ctx": CEILING, "new": CEILING, "ctx:part": CEILING},
        {"ctx": CEILING, "gone": CEILING},
        {"ctx": FAR},
        (),
        ("ctx:part", "ctx:empty"),
    )
    named = sorted(each.partition(": ")[0] for each in found)
    assert named == ["ctx:empty", "ctx:part", "gone", "new", "new"]


def test_a_converged_name_that_measures_nothing_is_a_breach(tmp_path: Path) -> None:
    """A name misspelt, or a part whose paths reach no module, converges nothing.

    Each is named, though its target is there.
    """
    files = {"kb_mcp/kernel/__init__.py": "X = 1\n", "kb_mcp/kernel/names.py": "X = 1\n"}
    parts = {"kernel:gone": ("kernel/gone",)}
    measured = measure(written(tmp_path, files), parts)
    found = breaches(
        measured,
        {"kernel": (100, 3, 2, 100, 10)},  # at the bound of its measure
        {"kernel": FAR, "kernel:gone": FAR, "kernal": FAR},
        ("kernal", "kernel:gone"),
        parts,
    )
    assert sorted(each.partition(": ")[0] for each in found) == ["kernal", "kernel:gone"]


# Targets that sum to a budget, the part's aside, which would pass it.
SMALL_BUDGET = (100, 10, 20, 50)
AT_BUDGET = {"a": (60, 6, 12, 50), "b": (40, 4, 8, 30), "a:part": (90, 9, 19, 40)}


@pytest.mark.parametrize(
    ("name", "target", "what"),
    [
        ("b", (41, 4, 8, 30), "lines"),
        ("b", (40, 5, 8, 30), "files"),
        ("b", (40, 4, 9, 30), "types"),
        ("b", (40, 4, 8, 51), "largest"),
        ("a:part", (90, 9, 19, 51), "largest"),
    ],
)
def test_targets_past_the_budget_are_a_breach(name: str, target: Target, what: str) -> None:
    """The contexts' targets may sum to the budget, the parts' aside; one more is a breach.

    No target's largest module, a part's included, may pass the budget's.
    """
    assert overspent(AT_BUDGET, SMALL_BUDGET, ("a:part",)) == []
    found = overspent({**AT_BUDGET, name: target}, SMALL_BUDGET, ("a:part",))
    assert [what in each for each in found] == [True]


def test_src_is_within_its_ceilings() -> None:
    """Each context of ``src/`` is within its ceilings, each at most its bound.

    Each converged context and part is within its targets too.
    """
    measured = measure(ROOT / "src", PARTS)
    assert breaches(measured, CEILINGS, TARGETS, CONVERGED, PARTS) == []


def test_the_targets_fit_the_budget() -> None:
    """The contexts' targets leave the budget a reserve, and no target passes its largest."""
    assert overspent(TARGETS, BUDGET, PARTS) == []
