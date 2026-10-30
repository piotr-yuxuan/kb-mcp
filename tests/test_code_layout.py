"""Where the code's imports may go and what stays a dataclass, past Import Linter's reach."""

from __future__ import annotations

import ast
import copy
import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import kb_mcp
from kb_mcp.kernel.names import RefusedError
from kb_mcp.kernel.record import Record
from kb_mcp.sources.atlassian.fetch.domain.content import Space
from kb_mcp.sources.atlassian.prepare.domain.catalogue import Catalogue

PACKAGE = Path(kb_mcp.__file__).parent
LAYOUT = Path(__file__).parents[1] / "docs" / "explanation" / "code-layout.md"
# A row of the layout page's table of the classes that stay dataclasses.
KEPT = re.compile(r"^\| `([\w.]+)` \| ", re.MULTILINE)
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
