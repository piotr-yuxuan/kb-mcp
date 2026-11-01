"""What a source declares: its name, what it reads, its settings' table, account and roles.

Standard library alone, since ``--help`` imports every declaration (contract G), so its
classes are dataclasses, as ``Command`` is. A declaration names its table, and its
account's, by module path, ``module:name``, which the entry loads once the arguments are
parsed; and its roles, each a module that the run using it loads, a ``Fetcher`` or a
``Preparer`` of ``sources.roles``. Its light checks, which ``fetch`` asks before anything
is asked of the user, are functions that it holds.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

# How a source reads a resource type: listed whole, per target; searched by update time,
# per target, which alone gives a window an exact end; or read whole, in place.
type Reading = Literal["listed", "searched", "in place"]
# A source's light checks, each a pure function of its options' values, by flag, None
# when not given, and of every setting's value, by its path joined by dots: why its run
# cannot go on, or None when it can;
type Refused = Callable[[Mapping[str, object], Mapping[str, object]], str | None]
# what its run does not apply of the settings given, by setting, and why;
type Unapplied = Callable[[Mapping[str, object], Mapping[str, object]], Mapping[str, str]]
# and the lines that a run's summary says of it.
type Described = Callable[[Mapping[str, object], Mapping[str, object]], tuple[str, ...]]


@dataclass(frozen=True)
class Option:
    """An option of a resource type: its flag, help and value's type, and any setting it replaces.

    ``type`` reads the value as typed, as argparse's ``type`` does. ``setting``, the path
    of a list that the flag replaces for one run, makes it repeat; without one, no setting
    holds the option.
    """

    flag: str
    help: str
    type: Callable[[str], object] = str
    setting: str | None = None


@dataclass(frozen=True)
class ResourceType:
    """A kind of thing that a source reads: its name, what it is, how it is read, its options.

    A source's types are read whole: no role reads some of them until a plan chooses among
    them, and a role whose removals cover them all may refuse some, as Atlassian's preparer
    does. Only the name and the options are read so far: plan 033 reads ``summary``, for
    help, and plan 034 ``read``, for its coverage.
    """

    name: str
    summary: str
    read: Reading
    options: tuple[Option, ...] = ()


@dataclass(frozen=True)
class Account:
    """What a source's fetcher signs in with: its name, its table's model and settings.

    ``name`` is its table, ``[accounts.<name>]``, which every source naming it shares.
    ``table`` names the model by module path; ``settings`` are its settings, by name, in
    their order.
    """

    name: str
    table: str
    settings: tuple[str, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        """Give its settings by their paths, joined by dots: ``accounts.<name>.<setting>``."""
        return tuple(f"accounts.{self.name}.{setting}" for setting in self.settings)


@dataclass(frozen=True)
class Declared:
    """A source: its name, what it is, the types it reads, its settings, table and roles.

    ``name`` is its table, ``[sources.<name>]``, its folder of the mirror and the front
    matter's ``source``. ``summary`` waits for plan 033's help, which reads it. ``types``
    are all that it reads, whole. ``settings`` are its table's settings, by name, in their
    order: the first names what it covers, which makes it configured. ``table`` is the
    Pydantic model of its table, by module path. ``preparers`` name the modules that
    write its documents, in their order, and ``fetcher`` the one that brings its
    system's changes into its store, None for a source read in place. ``account``, if
    any, is what its fetcher signs in with. ``refused``, ``unapplied`` and
    ``described``, if any, are its light checks.
    """

    name: str
    summary: str
    types: tuple[ResourceType, ...]
    settings: tuple[str, ...]
    table: str
    preparers: tuple[str, ...]
    fetcher: str | None = None
    account: Account | None = None
    refused: Refused | None = None
    unapplied: Unapplied | None = None
    described: Described | None = None

    @property
    def paths(self) -> tuple[str, ...]:
        """Give its settings by their paths, joined by dots: ``sources.<name>.<setting>``."""
        return tuple(f"sources.{self.name}.{setting}" for setting in self.settings)

    @property
    def options(self) -> dict[str, Option]:
        """Give the options of its types by flag, each once, in their order."""
        return {option.flag: option for each in self.types for option in each.options}
