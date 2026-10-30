"""What a source declares: its name, what it reads, and its settings' table.

Standard library alone, since ``--help`` imports every declaration (contract G), so its
classes are dataclasses, as ``Command`` is. A declaration names its table by module
path, ``module:name``, which the entry loads once the arguments are parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# How a source reads a resource type: listed whole, per target; searched by update time,
# per target, which alone gives a window an exact end; or read whole, in place.
type Reading = Literal["listed", "searched", "in place"]


@dataclass(frozen=True)
class ResourceType:
    """A kind of thing that a source reads: its name, what it is, and how it is read."""

    name: str
    summary: str
    read: Reading


@dataclass(frozen=True)
class Declared:
    """A source: its name, what it is, the types it reads, its settings and their table.

    ``name`` is its table, ``[sources.<name>]``, its folder of the mirror and the front
    matter's ``source``. ``settings`` are its table's settings, by name, in their order:
    the first names what it covers, which makes it configured. ``table`` is the
    Pydantic model of its table, by module path.
    """

    name: str
    summary: str
    types: tuple[ResourceType, ...]
    settings: tuple[str, ...]
    table: str
