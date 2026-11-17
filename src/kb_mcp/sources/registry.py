"""The registry: every connector, a source of each, and the rules of any registry.

A new connector is its package and one line here; the source that each gives, of its own
name, always exists. Standard library alone: ``--help`` imports it, and imports no table.
"""

from __future__ import annotations

import pkgutil
import re
from typing import TYPE_CHECKING

from kb_mcp.kernel.names import RESERVED, SOURCE_NAME
from kb_mcp.sources.atlassian import declared as atlassian
from kb_mcp.sources.declaration import Source
from kb_mcp.sources.worklog.declared import WORKLOG

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from kb_mcp.sources.declaration import Option

# Every connector, in name order, and its source, of its name.
CONNECTORS = (*atlassian.CONNECTORS, WORKLOG)
SOURCES = tuple(Source(name=each.name, connector=each) for each in CONNECTORS)
# A flag of an option: one dash and a letter, or two and a lower-case word.
FLAG = re.compile(r"-[a-z]|--[a-z][a-z0-9_-]*")


def configured(sources: Sequence[Source], named: Mapping[str, str | None]) -> tuple[Source, ...]:
    """Give the registry's sources, then each other that the settings name, in name order.

    ``named`` gives each source that the settings name, and its connector, None for one
    of its own name. One whose name or connector the registry's rules refuse is left out:
    the settings refuse its table, naming it. A source of the registry keeps its
    connector, which its table's ``connector`` must name.
    """
    connectors = {each.connector.name: each.connector for each in sources}
    known = {each.name for each in sources}
    return (
        *sources,
        *(
            Source(name=name, connector=connectors[connector or name])
            for name, connector in sorted(named.items())
            if name not in known
            and SOURCE_NAME.fullmatch(name)
            and name not in RESERVED
            and (connector or name) in connectors
        ),
    )


def refuse(sources: Iterable[Source]) -> None:
    """Raise ValueError, naming the source, for the first that a registry may not hold.

    A source's name is its table, its folders and the front matter's ``source``, so each
    source is configured once: a name matches ``SOURCE_NAME``, is none of ``RESERVED``,
    and is declared once. A connector names a setting, its first saying whether a source
    is configured, and a fetcher or a preparer, or a run of it would have no unit; its
    location is one of its settings, which a connector that signs in names, as signing in
    reads it. An option is one flag of ``fetch``, which the sources declaring it share:
    each declares it alike, and it matches ``FLAG``, or argparse would read it as a
    positional, and no command would start.
    """
    seen: set[str] = set()
    options: dict[str, tuple[str, Option]] = {}
    for source in sources:
        connector = source.connector
        if not SOURCE_NAME.fullmatch(source.name) or source.name in RESERVED:
            message = (
                f"source {source.name!r}: a source's name matches {SOURCE_NAME.pattern},"
                f" and is none of {', '.join(RESERVED)}"
            )
            raise ValueError(message)
        if source.name in seen:
            message = f"source {source.name!r}: declared twice"
            raise ValueError(message)
        seen.add(source.name)
        if not connector.settings:
            message = f"source {source.name!r}: names no setting"
            raise ValueError(message)
        if connector.fetcher is None and not connector.preparers:
            message = f"source {source.name!r}: names neither fetcher nor preparer"
            raise ValueError(message)
        if connector.location not in (None, *connector.settings) or (
            connector.login is not None and connector.location is None
        ):
            message = f"source {source.name!r}: a location that is none of its settings"
            raise ValueError(message)
        for option in connector.flags.values():
            if not FLAG.fullmatch(option.flag):
                message = (
                    f"source {source.name!r}: option {option.flag!r}: a flag is {FLAG.pattern}"
                )
                raise ValueError(message)
            first, known = options.setdefault(option.flag, (source.name, option))
            if known != option:
                message = (
                    f"source {source.name!r}: option {option.flag} declared otherwise by {first!r}"
                )
                raise ValueError(message)


def tables(sources: Iterable[Source]) -> dict[str, tuple[str, type]]:
    """Load the table of each source by its module path, with its connector's name, by name.

    What the entry composes into the settings' model, as each connector names it. Raises
    ValueError, naming the source, for a table whose settings are not its connector's, by
    name, in their order. A path that does not load raises as it does.
    """
    loaded: dict[str, tuple[str, type]] = {}
    for each in sources:
        path, settings = each.connector.table_path, each.connector.settings
        table = pkgutil.resolve_name(path)
        holds = tuple(getattr(table, "model_fields", ()))
        if holds != settings:
            message = (
                f"source {each.name!r}: {path}: holds {holds}, not the settings named, {settings}"
            )
            raise ValueError(message)
        loaded[each.name] = (each.connector.name, table)
    return loaded
