"""What a connector declares, and a source: one configured instance of one connector.

Standard library alone, since ``--help`` imports every declaration (contract G), so its
classes are dataclasses, as ``Command`` is. A connector names its table by module path,
``module:name``, which the entry loads once the arguments are parsed; its fetcher and
preparers, each a module that the run using it loads, a ``Fetcher`` or a ``Preparer`` of
``sources.stages``; and its sign-in's run and checks alike. Its light checks, which
``fetch`` asks before anything is asked of the user, are functions that it holds.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import re

# How a fetch enumerates the documents of a scope: listed whole, searched by update time,
# or read whole, in place.
type Enumeration = Literal["listed", "searched", "in place"]
# A connector's light checks, each a pure function of the source that it is asked of, of
# its options' values, by flag, None when not given, and of every setting's value, by its
# path joined by dots: why the source's run cannot go on, or None when it can;
type Refused = Callable[[Source, Mapping[str, object], Mapping[str, object]], str | None]
# what its run does not apply of the settings given, by setting, and why;
type Unapplied = Callable[[Source, Mapping[str, object], Mapping[str, object]], Mapping[str, str]]
# and the lines that a run's echo says of it.
type Described = Callable[[Source, Mapping[str, object], Mapping[str, object]], tuple[str, ...]]


def key_of(name: str, rule: re.Pattern[str]) -> Callable[[str], str]:
    """Return an argparse type that takes a scope's key by its rule, naming its scope type."""

    def check(text: str) -> str:
        if not rule.fullmatch(text):
            message = f"not a {name} key: {text!r}"
            raise argparse.ArgumentTypeError(message)
        return text

    return check


@dataclass(frozen=True)
class Option:
    """An option of a fetch: its flag, help and value's type, and any setting it replaces.

    ``parse`` reads the value as typed, as argparse's ``type`` does. ``setting``, the name
    of a list of its source's table that the flag replaces for one run, makes it repeat;
    without one, no setting holds the option.
    """

    flag: str
    help: str
    parse: Callable[[str], object] = str
    setting: str | None = None


@dataclass(frozen=True)
class DocumentType:
    """A type of document that one connector declares: its name, and its name in the plural.

    ``name`` is the front matter's ``type``; ``plural`` names its folder of a copy store.
    """

    name: str
    plural: str


@dataclass(frozen=True)
class ScopeType:
    """A type of scope: its name, its key's rule, how its documents are enumerated, its option.

    A scope of it is known by its source, this type and a key that matches ``key``, and
    holds documents of ``document_types``. ``option``, if any, replaces for one run the
    list of keys that a source's table holds, which its ``setting`` names. A scope type
    without a key's rule has one scope, the whole source, as a read in place has, keyed
    by the source's name.
    """

    name: str
    key: re.Pattern[str] | None
    enumeration: Enumeration
    document_types: tuple[DocumentType, ...]
    option: Option | None = None


@dataclass(frozen=True)
class Connector:
    """The code that reads one kind of origin: its scope types, its source's settings, its stages.

    ``help`` opens the group of each of its sources in the help of ``fetch`` and
    ``prepare``. ``scope_types`` are all that it reads, whole. ``options`` are its fetch's
    beside those of its scope types. ``settings`` are a source's table's settings, by
    name, in their order: the first names what the source covers, which makes it
    configured. ``table_path`` is the Pydantic model of that table, by module path.
    ``preparers`` name the modules that write a source's documents, in their order, and
    ``fetcher`` the one that brings its origin's changes into its store, None for a
    connector read in place. ``location``, if any, is the setting that says where a
    source of it is, such as a site's address, without which it is not signed in to,
    nor its documents given an address.

    A connector whose origin asks to sign in names, by module path as ``table_path``
    does, the run of ``kb-mcp login`` (``login``): a function of the settings, the
    sources to sign in, the browser's path and, by name, ``extensions`` and ``named``,
    whether the user named the one source, which gives a record of each place it signed
    in to, with its ``site``, and whether every sign-in completed, having said why not;
    and ``doctor``'s
    checks (``checks``): a function of the settings and of the sources configured, which
    gives its checks, each a ``Check``. A path that does not load raises as it does, as a
    table's: a programmer's error, as no setting can cause it. ``refused``,
    ``unapplied`` and ``described``, if any, are its light checks.
    """

    name: str
    help: str
    scope_types: tuple[ScopeType, ...]
    settings: tuple[str, ...]
    table_path: str
    preparers: tuple[str, ...]
    fetcher: str | None = None
    location: str | None = None
    login: str | None = None
    checks: str | None = None
    options: tuple[Option, ...] = ()
    refused: Refused | None = None
    unapplied: Unapplied | None = None
    described: Described | None = None

    @property
    def document_types(self) -> tuple[DocumentType, ...]:
        """Give the document types of its scope types, in their order."""
        return tuple(each for scope_type in self.scope_types for each in scope_type.document_types)

    @property
    def flags(self) -> dict[str, Option]:
        """Give its options by flag, each once: its scope types', then its own."""
        options = (each.option for each in self.scope_types if each.option is not None)
        return {option.flag: option for option in (*options, *self.options)}


@dataclass(frozen=True)
class Source:
    """One configured instance of one connector: its name and its connector.

    ``name`` is its table, ``[sources.<name>]``, its folders, and the front matter's
    ``source``.
    """

    name: str
    connector: Connector

    def path(self, setting: str) -> str:
        """Give one of its settings by its path, joined by dots: ``sources.<name>.<setting>``."""
        return f"sources.{self.name}.{setting}"

    @property
    def paths(self) -> tuple[str, ...]:
        """Give its connector's settings by their paths, in their order.

        Its table's ``connector`` aside, which every command reads, as the entry composes
        the settings' model by it.
        """
        return tuple(map(self.path, self.connector.settings))

    def prepared_by_default(self, settings: Mapping[str, object]) -> bool:
        """Say whether it holds documents to prepare: it keeps a store, or is configured.

        ``settings`` holds every setting's value by its path; configured is its first set.
        """
        return self.connector.fetcher is not None or bool(settings[self.paths[0]])
