"""The rows of a run of sources: a row per step and source, and the run's exit status.

``sync``, ``mirror`` and ``download`` give them. They are records, so not in
``cli.domain.sync``, which ``--help`` imports, nor in ``sync``'s use case, which reaches
the index, so that a command writes rows without importing what it does not run.
"""

from __future__ import annotations

from kb_mcp.cli.domain.sync import Outcome
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record


class Row(Record):
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
    steps: tuple[Row, ...]
