"""The settings' model of a registry, composed as the entry composes it, for the tests.

``MODEL`` is the program's, of ``SOURCES``: each declaration's table loaded by its module
path, composed by ``settings_model``.
"""

from __future__ import annotations

import pkgutil
from typing import TYPE_CHECKING

from kb_mcp.config.domain.settings import settings_model
from kb_mcp.sources.registry import SOURCES

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.declaration import Declared


def model_of(sources: Iterable[Declared]) -> type[Settings]:
    """Compose the settings' model of a registry, each table loaded by its module path."""
    return settings_model({each.name: pkgutil.resolve_name(each.table) for each in sources})


MODEL = model_of(SOURCES)
