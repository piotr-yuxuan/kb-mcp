"""The roles of a source: its fetcher, if any, and its preparers, each with one interface.

A ``Fetcher`` brings a system's changes into the store that it owns, raw first; a
``Preparer`` writes documents through the mirror, from that store or from a folder read
in place. Each takes a ``SourceRun``, the source it is run for and what it reads, and gives a
``Result``: how it ended and its counts, which ``--format json`` writes as every result,
and whose ``text`` writes them as its command does. A declaration names its roles by
module path, which a run loads, never ``--help``; any object with a role's methods is
one, and each source's is the module of its role, its functions the methods, which take
the run by position.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from kb_mcp.config.domain.settings import Settings
from kb_mcp.kernel.record import Record
from kb_mcp.sources.declaration import Source

if TYPE_CHECKING:
    from kb_mcp.kernel.output import Summary

# How a role ended: done, failed, the sign-in no longer holding, or not run, as a
# preparer that a dry run leaves alone.
type Outcome = Literal["done", "failed", "sign in", "not run"]


# What a check concludes: all is well, the user must sign in again, or something fails.
WELL, SIGN_IN, FAILED = "well", "sign in", "failed"


class Verdict(Record):
    """One check: what it looked at, what it found, and what that means."""

    name: str
    found: str
    state: str = WELL


class SignedIn(Record):
    """The site signed in to, and the folder that keeps its session."""

    site: str
    session: Path


class SourceRun(Record):
    """What a role runs with: its source, the settings, its tables and options, a dry run.

    ``source`` is the source that it is run for, its name and resource types, which a
    role serving several sources reads; ``source_table`` is that source's ``[sources.<name>]``,
    ``account_table`` its account's table, None for a source that signs in with none.
    ``options`` holds its options' values by flag, None when not given, and nothing for a
    preparer, a source's options being its fetch's; ``now`` and ``sleep`` are the clock and
    the pause between requests.
    """

    source: Source
    settings: Settings
    source_table: BaseModel
    account_table: BaseModel | None
    options: Mapping[str, object]
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    dry_run: bool


class Result(Record):
    """How a role ended; each role's result adds its counts, and writes them as text."""

    outcome: Outcome

    @abstractmethod
    def text(self, summary: Summary) -> str:
        """Write the counts as the role's command writes them, short or detailed."""


@runtime_checkable
class Fetcher(Protocol):
    """A source's fetcher: it brings a system's changes into the store that it owns."""

    def preflight(self, run: SourceRun, /) -> str | None:
        """Say what the fetch cannot go on with, read from disk before any source starts."""

    def fetch(self, run: SourceRun, /) -> Result:
        """Fetch what changed, or in a dry run say what it would fetch; say how it ended."""


@runtime_checkable
class Preparer(Protocol):
    """A source's preparer: it writes the source's documents through the mirror."""

    def preflight(self, run: SourceRun, /) -> str | None:
        """Say what the preparer cannot go on with, read from disk before any source starts."""

    def prepare(self, run: SourceRun, /) -> Result:
        """Write the source's documents, or count what a dry run would; say how it ended."""
