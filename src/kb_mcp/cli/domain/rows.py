"""The rows of a run of sources: a row per source, and the run's exit status.

``fetch`` gives them. They are records, so not in ``cli.domain.sources``, which ``--help``
imports, nor in the use case, which loads what roles need, so that a command writes rows
without importing what it does not run. ``sync`` and ``mirror`` give their own until they
go, a row per step and source.
"""

from __future__ import annotations

from kb_mcp.cli.domain.sources import Outcome
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record


class Row(Record):
    """A source's row: its name, how it ended, and its result, None if it gave none."""

    source: str
    outcome: Outcome
    result: object | None


class Ran(Record):
    """What a run of sources did: its exit status, then a row per source, in their order."""

    exit_status: ExitStatus
    sources: tuple[Row, ...]


class SyncRow(Record):
    """A step's row: its name, its source, how it ended, and its result, None if it gave none.

    ``source`` is None on a row of no single source: the index.
    """

    step: str
    source: str | None
    outcome: Outcome
    result: object | None


class Synced(Record):
    """What a sync, or a mirror, did: its exit status, then a row per step, in their order."""

    exit_status: ExitStatus
    steps: tuple[SyncRow, ...]
