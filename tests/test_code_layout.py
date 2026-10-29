"""Where the code's imports may go, for what Import Linter cannot check."""

from __future__ import annotations

import ast
from pathlib import Path

import kb_mcp

PACKAGE = Path(kb_mcp.__file__).parent
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
