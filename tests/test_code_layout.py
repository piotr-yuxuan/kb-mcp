"""Where the code's imports may go and what stays a dataclass, past Import Linter's reach.

Each contract of ``pyproject.toml`` carries, as its id, the letter that the layout page
gives it; contract I lists the package of each source that the registry declares, and
K every context and source but the Atlassian package.
"""

from __future__ import annotations

import ast
import copy
import importlib
import importlib.util
import pkgutil
import re
import tomllib
from pathlib import Path

import pytest

import kb_mcp
from kb_mcp import sources
from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.record import Record
from kb_mcp.sources.atlassian.fetch.domain.content import Space
from kb_mcp.sources.atlassian.prepare.domain.catalogue import Catalogue
from kb_mcp.sources.registry import SOURCES

PACKAGE = Path(kb_mcp.__file__).parent
ROOT = Path(__file__).parents[1]
LAYOUT = ROOT / "docs" / "explanation" / "code-layout.md"
CONTRACTS = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["tool"]["importlinter"][
    "contracts"
]
# A row of the layout page's table of the classes that stay dataclasses.
KEPT = re.compile(r"^\| `([\w.]+)` \| ", re.MULTILINE)
# A row of the layout page's table of contracts: its letter.
LETTER = re.compile(r"^\| ([A-Z]) \| ", re.MULTILINE)
# What knows no source by name: plan 030's criterion 6.
NAMELESS = ("cli/app", "cli/domain", "config", "mirror")
SOURCE_NAMED = re.compile(r"\b(?:confluence|jira|worklog)\b|sources\.atlassian", re.IGNORECASE)
# The lines of NAMELESS that name one all the same, by file.
NAMING = {
    # A docstring's example of a setting's path.
    "cli/domain/command.py": 1,
    # MOVED: plan 015's message for its moved keys, which name their tables.
    "config/domain/settings.py": 2,
    # A docstring: which step owns which folder.
    "mirror/adapters/mirror_files.py": 2,
    # Docstrings of the front matter's Atlassian-shaped keys, which question 3 keeps.
    "mirror/domain/mirror.py": 3,
}
# OpenTelemetry's SDK, exporters and instrumentation, which plan 016 keeps within
# observability: elsewhere code uses the API alone. Import Linter forbids root packages
# only, and the API and the SDK share theirs, opentelemetry.
SDK = ("opentelemetry.sdk.", "opentelemetry.exporter.", "opentelemetry.instrumentation.")


def test_only_observability_imports_the_opentelemetry_sdk() -> None:
    """No module outside ``observability`` imports the SDK, an exporter or instrumentation.

    Every import counts, within a function or under ``TYPE_CHECKING`` too.
    """
    importers = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_bytes(), path)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                names = []
            if any(f"{name}.".startswith(SDK) for name in names):
                importers.add(path.relative_to(PACKAGE))
    assert {path for path in importers if path.parts[0] != "observability"} == set()


def test_the_dataclasses_are_the_layout_page_s_exceptions() -> None:
    """Every dataclass under ``src/kb_mcp`` is a class of the page's table, and each one is.

    A new value is a record unless the page names it with its reason.
    """
    section = LAYOUT.read_text(encoding="utf-8").partition("\n## Records\n")[2]
    named = set(KEPT.findall(section.partition("\n## ")[0]))
    found = set()
    for path in PACKAGE.rglob("*.py"):
        module = ".".join(path.relative_to(PACKAGE).with_suffix("").parts)
        for node in ast.walk(ast.parse(path.read_bytes(), path)):
            decorators = (
                ast.unparse(each.func if isinstance(each, ast.Call) else each)
                for each in getattr(node, "decorator_list", [])
            )
            if isinstance(node, ast.ClassDef) and "dataclass" in {
                name.removeprefix("dataclasses.") for name in decorators
            }:
                found.add(f"{module}.{node.name}")
    assert found == named


def test_every_record_resolves_its_annotations() -> None:
    """Each record of the package builds its schema from the names its module holds at run time.

    Pydantic resolves a record's annotations at its first construction, which a test may
    never reach: a type imported under ``TYPE_CHECKING`` alone would fail there.
    """
    for module in pkgutil.walk_packages(kb_mcp.__path__, "kb_mcp."):
        if module.name != "kb_mcp.__main__":
            importlib.import_module(module.name)
    records: list[type[Record]] = []
    left = [Record]
    while left:
        subclasses = left.pop().__subclasses__()
        records += subclasses
        left += subclasses
    assert records
    for record in records:
        assert record.model_rebuild(force=True, raise_errors=True), record


def test_a_record_replaced_is_checked_again_and_keeps_its_cached_properties_out() -> None:
    """``copy.replace`` builds the record again from its fields alone, so its checks run.

    A cached property lives in the instance's dictionary, which ``extra="forbid"`` would
    refuse were it passed on as a field.
    """
    space = Space(id="196613", key="MFS", name="Sample")
    catalogue = Catalogue(spaces={space.id: space}, names={}, listed={}, folders={})
    assert catalogue.nodes == {}
    replaced = copy.replace(catalogue, names={"account-1": "A Person"})
    assert (replaced.spaces, replaced.names) == ({space.id: space}, {"account-1": "A Person"})
    with pytest.raises(RefusedError, match=r"^id: does not match"):
        copy.replace(space, id="../up")


def test_each_contract_s_id_is_its_letter_on_the_layout_page_in_its_order() -> None:
    """Plan 030: ``lint-imports`` names a contract as the page does, one row each.

    A contract added, removed or moved without its row, or two ids swapped, fails it.
    """
    section = LAYOUT.read_text(encoding="utf-8").partition("\n## The contracts\n")[2]
    letters = LETTER.findall(section.partition("\n## ")[0])
    assert [contract.get("id") for contract in CONTRACTS] == letters


def test_contract_i_lists_the_package_of_each_registered_source_once() -> None:
    """I's packages are those whose ``declared`` holds a declaration of ``SOURCES``.

    Under ``kb_mcp.sources``, each once and no other: a source registered without its
    place in I fails it. Each declaration of ``SOURCES`` is one of a package's.
    """
    held: dict[str, str] = {}
    for package in pkgutil.iter_modules(sources.__path__, f"{sources.__name__}."):
        declared = f"{package.name}.declared"
        if package.ispkg and importlib.util.find_spec(declared) is not None:
            values = vars(importlib.import_module(declared)).values()
            held |= {each.name: package.name for each in SOURCES if each in values}
    assert set(held) == {each.name for each in SOURCES}
    (independent,) = [contract for contract in CONTRACTS if contract.get("id") == "I"]
    assert sorted(independent["modules"]) == sorted(set(held.values()))


def test_contract_k_names_every_context_and_source_but_the_atlassian_package() -> None:
    """Plan 030: K keeps lxml and Playwright within ``sources.atlassian`` alone.

    A forbidden contract cannot leave one package out of a wildcard, so K names each
    context but ``sources``, and each module and package of ``sources`` but
    ``atlassian``, each once: a new context, or a new source, left out of K fails it. Of
    ``atlassian`` it names the module that every command loads by its path, which no
    import from ``cli`` shows it, the account's and the sources' tables.
    """
    contexts = {
        f"{kb_mcp.__name__}.{each.name}"
        for each in pkgutil.iter_modules(kb_mcp.__path__)
        if each.ispkg and each.name != "sources"
    }
    beside = {
        f"{sources.__name__}.{each.name}"
        for each in pkgutil.iter_modules(sources.__path__)
        if each.name != "atlassian"
    }
    (contract,) = [contract for contract in CONTRACTS if contract.get("id") == "K"]
    every_command_loads = {f"{sources.__name__}.atlassian.settings"}
    assert sorted(contract["source_modules"]) == sorted(contexts | beside | every_command_loads)
    assert sorted(contract["forbidden_modules"]) == ["lxml", "playwright"]


def test_no_context_above_the_sources_names_one_but_the_plan_s_exceptions() -> None:
    """Plan 030's criterion 6 stays true: only the registry brings a source to a run.

    The use cases, ``config`` and ``mirror`` know a source by no name, nor import the
    Atlassian package, which no contract keeps them from. Each file may hold the lines that
    it holds, each for the reason noted.
    """
    found = {
        path.relative_to(PACKAGE).as_posix(): lines
        for root in NAMELESS
        for path in sorted((PACKAGE / root).rglob("*.py"))
        if (lines := sum(map(bool, map(SOURCE_NAMED.search, path.read_text("utf-8").splitlines()))))
    }
    assert found == NAMING
