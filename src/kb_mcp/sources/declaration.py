"""What a source declares: its name, what it reads, its settings' table, account, stages.

Standard library alone, since ``--help`` imports every declaration (contract G), so its
classes are dataclasses, as ``Command`` is. A declaration names its table, and its
account's, by module path, ``module:name``, which the entry loads once the arguments are
parsed; and its fetcher and preparers, each a module that the run using it loads, a
``Fetcher`` or a ``Preparer`` of ``sources.stages``. Its light checks, which ``fetch`` asks
before anything is asked of the user, are functions that it holds.
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
# and the lines that a run's preview says of it.
type Described = Callable[[Mapping[str, object], Mapping[str, object]], tuple[str, ...]]


@dataclass(frozen=True)
class Option:
    """An option of a resource type: its flag, help and value's type, and any setting it replaces.

    ``parse`` reads the value as typed, as argparse's ``type`` does. ``setting``, the path
    of a list that the flag replaces for one run, makes it repeat; without one, no setting
    holds the option.
    """

    flag: str
    help: str
    parse: Callable[[str], object] = str
    setting: str | None = None


@dataclass(frozen=True)
class ResourceType:
    """A type of thing that a source reads: its name, what it is, how it is read, its options.

    A source's types are read whole: no fetcher or preparer reads some of them until a plan
    chooses among them, and one whose removals cover them all may refuse some, as
    Atlassian's preparer does. The name, the options and ``read`` are read so far, the last
    in the help of ``fetch`` and ``prepare``, each source's group, where ``help`` is not
    read yet.
    """

    name: str
    help: str
    read: Reading
    options: tuple[Option, ...] = ()


@dataclass(frozen=True)
class Account:
    """What a source's fetcher signs in with: its name, its table, its login and its checks.

    ``name`` is its table, ``[accounts.<name>]``, which every source naming it shares.
    ``table_path`` names the model by module path; ``settings`` are its settings, by name, in
    their order, the first where it signs in. ``login`` names by module path, as ``table_path``
    does, the run of ``kb-mcp login <name>``: a function of the settings, the browser's
    path and, by name, ``extensions``, which gives a ``SignedIn`` of ``sources.stages``, or
    None when no sign-in completed, having said so. ``checks`` names alike ``doctor``'s of
    it: a function of the settings, which gives a ``Verdict`` each. ``refused`` and
    ``unapplied``, if any, are its light checks, which ``doctor`` asks with no options:
    what cannot be signed in with, and what the sign-in does not apply. A path that does not
    load raises as it does, as a table's: a programmer's error, as no setting can cause it.
    """

    name: str
    table_path: str
    settings: tuple[str, ...]
    login: str
    checks: str
    refused: Refused | None = None
    unapplied: Unapplied | None = None

    @property
    def paths(self) -> tuple[str, ...]:
        """Give its settings by their paths, joined by dots: ``accounts.<name>.<setting>``."""
        return tuple(f"accounts.{self.name}.{setting}" for setting in self.settings)


@dataclass(frozen=True)
class Source:
    """A source: its name, what it is, the types it reads, its settings, table and stages.

    ``name`` is its table, ``[sources.<name>]``, its folder of the mirror and the front
    matter's ``source``. ``help`` opens its group in the help of ``fetch`` and
    ``prepare``. ``resource_types`` are all that it reads, whole. ``settings`` are its table's
    settings, by name, in their order: the first names what it covers, which makes it
    configured. ``table_path`` is the Pydantic model of its table, by module path.
    ``preparers`` name the modules that write its documents, in their order, and
    ``fetcher`` the one that brings its system's changes into its store, None for a
    source read in place. ``account``, if any, is what its fetcher signs in with.
    ``refused``, ``unapplied`` and ``described``, if any, are its light checks.
    """

    name: str
    help: str
    resource_types: tuple[ResourceType, ...]
    settings: tuple[str, ...]
    table_path: str
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
        return {option.flag: option for each in self.resource_types for option in each.options}
