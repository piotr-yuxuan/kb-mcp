"""The rows of a run of sources: a row per source, and the run's exit status.

``fetch`` and ``prepare`` give them, and the exit status folds how the rows ended. They
are records, and a row's outcome is its stage's, so not in ``cli.domain.sources``, which
``--help`` imports, nor in the use case, which loads what fetchers and preparers need, so
that a command writes rows without importing what it does not run.
"""

from __future__ import annotations

from kb_mcp.kernel.exit_status import Ending, ExitStatus
from kb_mcp.kernel.record import Record


class Row(Record):
    """A source's row: its name, how it ended, and its result, None if it gave none."""

    source: str
    outcome: Ending
    result: object | None


class Ran(Record):
    """What a run of sources did: its exit status, then a row per source, in their order."""

    exit_status: ExitStatus
    sources: tuple[Row, ...]
