"""The registry: every source that the program knows, and the rules of any registry.

A new source is its package and one line here. The entry, ``kb_mcp.cli.main.main``,
takes ``SOURCES`` unless a test gives it a registry of its own, and ``refuse`` judges
either. Standard library alone, as the declarations are: ``--help`` imports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.names import SOURCE_NAME
from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
from kb_mcp.sources.worklog.declared import WORKLOG

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kb_mcp.sources.declaration import Declared

# Every source, in name order.
SOURCES = (CONFLUENCE, JIRA, WORKLOG)
# The mirror's folder of the files that Confluence's and Jira's documents attach,
# docs/assets/, which no source's folder may be.
ASSETS = "assets"


def refuse(sources: Iterable[Declared]) -> None:
    """Raise ValueError, naming the declaration, for the first that a registry may not hold.

    A source's name is its table, its folder of the mirror and the front matter's
    ``source``, so one source type has one instance: a name matches ``SOURCE_NAME``, is
    not ``assets``, and is declared once.
    """
    seen: set[str] = set()
    for declared in sources:
        if not SOURCE_NAME.fullmatch(declared.name) or declared.name == ASSETS:
            message = (
                f"source {declared.name!r}: a source's name matches {SOURCE_NAME.pattern},"
                f" and is not {ASSETS}"
            )
            raise ValueError(message)
        if declared.name in seen:
            message = f"source {declared.name!r}: declared twice"
            raise ValueError(message)
        seen.add(declared.name)
