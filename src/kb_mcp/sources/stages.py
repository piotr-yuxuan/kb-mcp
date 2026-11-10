"""A source's part in the stages: its fetcher, if any, and its preparers, one interface each.

A ``Fetcher`` brings a system's changes into the store that it owns, raw first; a
``Preparer`` writes documents through the mirror, from that store or from a folder read
in place. Each takes a ``SourceRun``, the source it is run for and what it reads, and
gives an ``Outcome``: how it ended, its problems and warnings, and its counts, a record
whose ``text`` writes them as its command does. A declaration names its
fetcher and preparers by module path, which a run loads, never ``--help``; any object
with an interface's methods is one, and each source's is a module, its functions the
methods, which take the run by position.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, InstanceOf

from kb_mcp.config.domain.settings import Settings
from kb_mcp.kernel.record import Record
from kb_mcp.sources.declaration import Source

if TYPE_CHECKING:
    from kb_mcp.kernel.outcome import Outcome

# What a check concludes: all is well, the user must sign in again, or something fails.
type CheckState = Literal["well", "sign in again", "failed"]


class Check(Record):
    """One check: what it looked at, what it found, and what that means."""

    name: str
    found: str
    state: CheckState = "well"


class SourceRun(Record):
    """What a fetcher or a preparer runs with: its source, the settings, tables, options, a dry run.

    ``source`` is the source that it is run for, its name and connector, which a fetcher
    or preparer serving several connectors reads; ``sources`` every source of the
    registry, which a preparer that places documents across sources reads;
    ``source_table`` is that source's
    ``[sources.<name>]``, ``account_table`` its account's table, None for a source that
    signs in with none. ``options`` holds its options' values by flag, None when not given,
    and nothing for a preparer, a source's options being its fetch's; ``now`` and ``sleep``
    are the clock and the pause between requests.
    """

    source: InstanceOf[Source]
    sources: tuple[InstanceOf[Source], ...]
    settings: Settings
    source_table: BaseModel
    account_table: BaseModel | None
    options: Mapping[str, object]
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    dry_run: bool


@runtime_checkable
class Fetcher(Protocol):
    """A source's fetcher: it brings a system's changes into the store that it owns."""

    def preflight(self, run: SourceRun, /) -> str | None:
        """Say what the fetch cannot go on with, read from disk before any source starts."""

    def fetch(self, run: SourceRun, /) -> Outcome:
        """Fetch what changed, or in a dry run say what it would fetch; say how it ended."""


@runtime_checkable
class Preparer(Protocol):
    """A source's preparer: it writes the source's documents through the mirror."""

    def preflight(self, run: SourceRun, /) -> str | None:
        """Say what the preparer cannot go on with, read from disk before any source starts."""

    def prepare(self, run: SourceRun, /) -> Outcome:
        """Write the source's documents, or count what a dry run would; say how it ended."""
