"""What a source declares: its name, what it reads, its settings' table, account and roles.

Standard library alone, since ``--help`` imports every declaration (contract G), so its
classes are dataclasses, as ``Command`` is. A declaration names its table, and its
account's, by module path, ``module:name``, which the entry loads once the arguments are
parsed; and its roles, each a module that the run using it loads, a ``Fetcher`` or a
``Preparer`` of ``sources.roles``.
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
class Account:
    """What a source's fetcher signs in with: its name, and the Pydantic model of its table.

    ``name`` is its table, ``[accounts.<name>]``, which every source naming it shares.
    ``table`` names the model by module path.
    """

    name: str
    table: str


@dataclass(frozen=True)
class Declared:
    """A source: its name, what it is, the types it reads, its settings, table and roles.

    ``name`` is its table, ``[sources.<name>]``, its folder of the mirror and the front
    matter's ``source``. ``settings`` are its table's settings, by name, in their order:
    the first names what it covers, which makes it configured. ``table`` is the
    Pydantic model of its table, by module path. ``preparers`` name the modules that
    write its documents, in their order, and ``fetcher`` the one that brings its
    system's changes into its store, None for a source read in place. ``account``, if
    any, is what its fetcher signs in with.
    """

    name: str
    summary: str
    types: tuple[ResourceType, ...]
    settings: tuple[str, ...]
    table: str
    preparers: tuple[str, ...]
    fetcher: str | None = None
    account: Account | None = None
