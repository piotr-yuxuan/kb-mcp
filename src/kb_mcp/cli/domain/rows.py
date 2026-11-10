"""The rows of a run of sources: a row per source, and the run's exit status.

``fetch`` and ``prepare`` give them, and the exit status folds how the rows ended. They
are records, and a row's outcome is its stage's, so not in ``cli.domain.sources``, which
``--help`` imports, nor in the use case, which loads what fetchers and preparers need, so
that a command writes rows without importing what it does not run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import model_serializer

from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.outcome import Outcome
from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from pydantic import SerializerFunctionWrapHandler


class Row(Outcome):
    """A source's row: the name of its source, then its outcome, which JSON writes in order."""

    source: str

    @model_serializer(mode="wrap")
    def source_first(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Write the source before the outcome's fields, which a subclass's come after."""
        written = handler(self)
        return {"source": written.pop("source"), **written}


class Ran(Record):
    """What a run of sources did: its exit status, then a row per source, in their order."""

    exit_status: ExitStatus
    sources: tuple[Row, ...]
