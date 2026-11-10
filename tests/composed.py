"""The settings' model of a registry, composed as the entry composes it, for the tests.

``MODEL`` is the program's, of ``SOURCES``: each connector's table, and its account's,
loaded by its module path, composed by ``settings_model``. ``sourced`` makes a registry of
connectors, as ``SOURCES`` is made.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.config.domain.settings import settings_model
from kb_mcp.sources.declaration import Source
from kb_mcp.sources.registry import SOURCES, tables

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Connector


def sourced(*connectors: Connector) -> tuple[Source, ...]:
    """Give each connector one source, of its own name, in their order, as the registry does."""
    return tuple(Source(name=each.name, connector=each) for each in connectors)


def model_of(sources: Iterable[Source]) -> type[Settings]:
    """Compose the settings' model of a registry, each table loaded by its module path."""
    return settings_model(*tables(sources))


MODEL = model_of(SOURCES)
