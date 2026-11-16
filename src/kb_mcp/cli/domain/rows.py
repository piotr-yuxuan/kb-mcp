"""What a recorded run writes as its result: its run id first, then its units' outcomes.

``fetch`` and ``prepare`` give a row per source; ``index`` and ``embed``, the outcome of
their one unit; ``refresh``, each unit's last entry. They are records, and an outcome is
its stage's, so not in ``cli.domain.sources``, which ``--help`` imports, nor in the use
case, which loads what fetchers and preparers need, so that a command writes its result
without importing what it does not run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import Field, InstanceOf, model_serializer

from kb_mcp.cli.domain.runs import Recorded, Unit
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
    """What a run of sources did: its run id, its exit status, then a row per source, in order.

    ``recorded``, which its text says and JSON leaves out, is whether the run is recorded,
    so that refresh --resume takes its id: a dry run is not.
    """

    run: str
    exit_status: ExitStatus
    sources: tuple[Row, ...]
    recorded: bool = Field(default=True, exclude=True)


class Ended(Outcome):
    """What a run of one unit over the whole did: its run id, then its unit's outcome."""

    run: str

    @model_serializer(mode="wrap")
    def run_first(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Write the run id before the outcome's fields."""
        written = handler(self)
        return {"run": written.pop("run"), **written}


class Refreshed(Record):
    """What an invocation of a refresh, or of a resume, did: its run id, status and units.

    ``units`` are each unit's last entry, in their order, those of earlier invocations
    included; ``outcomes``, this invocation's, by unit, which its text writes and JSON
    leaves out, as its entries hold them.
    """

    run: str
    exit_status: ExitStatus
    units: tuple[Recorded, ...]
    outcomes: Mapping[Unit, InstanceOf[Outcome]] = Field(default_factory=dict, exclude=True)
