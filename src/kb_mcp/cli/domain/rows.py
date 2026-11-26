"""What a recorded run writes as its result: its run id first, then its units' outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import Field, InstanceOf, model_serializer

from kb_mcp.cli.domain.runs import Recorded, Unit
from kb_mcp.kernel.names import ExitStatus
from kb_mcp.kernel.records import Outcome, Record

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

    ``recorded``, which JSON leaves out, is false for a dry run, whose id no resume takes.
    """

    run: str
    exit_status: ExitStatus
    sources: tuple[Row, ...]
    recorded: bool = Field(default=True, exclude=True)


class Ended(Outcome):
    """What a run of one unit over the whole did: its run id, then its unit's outcome.

    ``recorded``, which JSON leaves out, is false when the data directory does not exist.
    """

    run: str
    recorded: bool = Field(default=True, exclude=True)

    @model_serializer(mode="wrap")
    def run_first(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Write the run id before the outcome's fields."""
        written = handler(self)
        return {"run": written.pop("run"), **written}


class Refreshed(Record):
    """What an invocation of a refresh, or of a resume, did: its run id, status and units.

    ``units`` are each unit's last entry, in order, earlier invocations' included;
    ``outcomes``, which JSON leaves out, this invocation's, by unit.
    """

    run: str
    exit_status: ExitStatus
    units: tuple[Recorded, ...]
    outcomes: Mapping[Unit, InstanceOf[Outcome]] = Field(default_factory=dict, exclude=True)
