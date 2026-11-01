"""The registry: every source that the program knows, and the rules of any registry.

A new source is its package and one line here. The entry, ``kb_mcp.cli.main.main``,
takes ``SOURCES`` unless a test gives it a registry of its own, and ``refuse`` judges
either; ``tables`` loads the tables that its declarations name, once the arguments are
parsed. Standard library alone, as the declarations are: ``--help`` imports it, and
imports no table.
"""

from __future__ import annotations

import pkgutil
from typing import TYPE_CHECKING

from kb_mcp.kernel.names import SOURCE_NAME
from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
from kb_mcp.sources.worklog.declared import WORKLOG

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kb_mcp.sources.declaration import Account, Declared, Option

# Every source, in name order.
SOURCES = (CONFLUENCE, JIRA, WORKLOG)
# The mirror's folder of the files that Confluence's and Jira's documents attach,
# docs/assets/, which no source's folder may be.
ASSETS = "assets"


def refuse(sources: Iterable[Declared]) -> None:
    """Raise ValueError, naming the declaration, for the first that a registry may not hold.

    A source's name is its table, its folder of the mirror and the front matter's
    ``source``, so one source type has one instance: a name matches ``SOURCE_NAME``, is
    not ``assets``, and is declared once. An account's name is its table, which the
    sources naming it share: each names it alike. A source names a setting, its first
    saying whether it is configured. An option is one flag of ``sync``, which the sources
    declaring it share: each declares it alike.
    """
    seen: set[str] = set()
    accounts: dict[str, Account] = {}
    options: dict[str, tuple[str, Option]] = {}
    for declared in sources:
        account = declared.account
        if account is not None and accounts.setdefault(account.name, account) != account:
            message = f"source {declared.name!r}: account {account.name!r} declared otherwise"
            raise ValueError(message)
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
        if not declared.settings:
            message = f"source {declared.name!r}: names no setting"
            raise ValueError(message)
        for option in (option for kind in declared.types for option in kind.options):
            first, known = options.setdefault(option.flag, (declared.name, option))
            if known != option:
                message = (
                    f"source {declared.name!r}: option {option.flag} declared otherwise"
                    f" by {first!r}"
                )
                raise ValueError(message)


def accounts_of(sources: Iterable[Declared]) -> dict[str, Account]:
    """Give each account that these sources name, by its name, once, in their order."""
    return {
        declared.account.name: declared.account
        for declared in sources
        if declared.account is not None
    }


def table_of(owner: str, path: str, settings: tuple[str, ...]) -> type:
    """Load a table by its module path; raise ValueError for settings other than those named.

    ``owner`` names the declaration: its settings are the table's, by name, in their
    order. A path that does not load raises as it does.
    """
    table = pkgutil.resolve_name(path)
    holds = tuple(getattr(table, "model_fields", ()))
    if holds != settings:
        message = f"{owner}: {path}: holds {holds}, not the settings named, {settings}"
        raise ValueError(message)
    return table


def tables(sources: Iterable[Declared]) -> tuple[dict[str, type], dict[str, type]]:
    """Load the table of each source, then of each account that they name, each by its name.

    What the entry composes into the settings' model, as each declaration names it.
    """
    declared = tuple(sources)
    return (
        {
            each.name: table_of(f"source {each.name!r}", each.table, each.settings)
            for each in declared
        },
        {
            name: table_of(f"account {name!r}", each.table, each.settings)
            for name, each in accounts_of(declared).items()
        },
    )
