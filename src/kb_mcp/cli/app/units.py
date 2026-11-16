"""A run's units, run in their order, each one's last entry written as it ends.

Each unit of a stage per source is a span, ``fetch.source`` or ``prepare.source``, naming
its source, within which its fetcher's or preparer's own spans and events are recorded,
as ``docs/reference/telemetry/fetch.md`` and ``prepare.md`` say; a unit over the whole
records what its use case does. ``run_units`` says the rest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import groupby
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace
from pydantic import AwareDatetime, ConfigDict, Field, InstanceOf
from pydantic_core import to_jsonable_python

from kb_mcp.cli.domain.command import FETCH, PREPARE, WHOLE
from kb_mcp.cli.domain.runs import Recorded, Unit, attempted, followed, keyed
from kb_mcp.kernel.exit_status import Ending, ExitStatus, folded
from kb_mcp.kernel.outcome import Outcome, Problem
from kb_mcp.kernel.record import Record

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from kb_mcp.cli.domain.command import Stage

TRACER = trace.get_tracer(__name__)
# What each stage per source records, by name, written out so that a search for an event
# finds it: its start, each source's unit, Ctrl-C, its end.
EVENTS = {
    FETCH: ("fetch.start", "fetch.source", "fetch.interrupted", "fetch.end"),
    PREPARE: ("prepare.start", "prepare.source", "prepare.interrupted", "prepare.end"),
}
# What each stage per source calls a refusal: of the run, or of one source's unit.
REFUSED = {FETCH: "fetch.refused", PREPARE: "prepare.refused"}


class SourcesRefusedError(ValueError):
    """What a run cannot go on with, found before its first unit; the message names it.

    ``stage`` is the stage whose fetcher or preparer does not load.
    """

    def __init__(self, message: str, stage: Stage) -> None:
        """Name what is refused, and of which stage."""
        super().__init__(message)
        self.stage = stage


class Planned(Record):
    """A unit as an invocation runs it: the unit, its work, and its preflight, if any.

    ``preflight`` says what the unit cannot go on with, read from disk, before its work:
    the unit then fails alone.
    """

    unit: Unit
    act: Callable[[], InstanceOf[Outcome]]
    preflight: Callable[[], str | None] | None = None


class Done(Record):
    """What an invocation of a run did: its exit status, each unit's last entry, its outcomes.

    ``entries`` are every unit's last, in their order, those of earlier invocations
    included; ``outcomes`` this invocation's, by unit, in their order.
    """

    exit_status: ExitStatus
    entries: tuple[Recorded, ...]
    outcomes: Mapping[Unit, InstanceOf[Outcome]]


class Progress(Record):
    """An invocation's units as they end, every unit's last entry written at each end.

    ``taken`` are the units that it runs; ``write`` is given every unit's last entry, in
    their order. ``acting`` is the unit at work, if any; ``own``, the invocation's own
    ending, if any: interrupted.
    """

    model_config = ConfigDict(frozen=False)

    units: tuple[Unit, ...]
    taken: frozenset[Unit]
    entries: dict[Unit, Recorded]
    invocation: AwareDatetime
    write: Callable[[tuple[Recorded, ...]], None]
    outcomes: dict[Unit, InstanceOf[Outcome]] = Field(default_factory=dict)
    acting: Unit | None = None
    own: tuple[Ending, ...] = ()

    def ready(self, unit: Unit) -> bool:
        """Say whether a unit per source may run: each unit that it follows last ended done."""
        return all(
            each in self.entries and self.entries[each].ending == "done"
            for each in followed(unit, self.units)
        )

    def end(self, unit: Unit, outcome: Outcome) -> None:
        """Keep how a unit ended, as this invocation's entry, and write every unit's last."""
        self.outcomes[unit] = outcome
        self.entries[unit] = Recorded(
            stage=unit.stage,
            source=unit.source,
            ending=outcome.ending,
            counts=to_jsonable_python(outcome.counts),
            problems=outcome.problems,
            warnings=outcome.warnings,
            invocation=self.invocation,
        )
        self.acting = None
        self.write(tuple(self.entries[each] for each in self.units if each in self.entries))

    def interrupted(self) -> None:
        """End the invocation interrupted: the unit at work so, each other taken not run.

        Once: Ctrl-C interrupts an invocation once, however many units it reaches.
        """
        if self.own:
            return
        self.own = ("interrupted",)
        if self.acting is not None:
            self.end(self.acting, Outcome(ending="interrupted"))
        for unit in [each for each in self.units if each in self.taken - set(self.outcomes)]:
            self.end(unit, Outcome(ending="not run"))

    def done(self) -> Done:
        """Give what the invocation did: its status folds its own ending and each unit's last."""
        entries = tuple(self.entries[each] for each in self.units if each in self.entries)
        return Done(
            exit_status=folded([*self.own, *(entry.ending for entry in entries)]),
            entries=entries,
            outcomes={unit: self.outcomes[unit] for unit in self.units if unit in self.outcomes},
        )


def run_sources(
    stage: Stage, taken: Sequence[Planned], progress: Progress, *, dry_run: bool
) -> None:
    """Run the units of a stage per source that an invocation takes, in their order.

    A unit whose source's unit before it did not last end done ends not run, and does
    nothing; what a ``preflight`` refuses fails its unit alone, a problem by its source and
    an error, ``fetch.refused`` or ``prepare.refused``, naming the source; a unit that
    failed stops no other. The stage says at INFO its ``start``, the sources taken and
    whether a dry run, its ``source`` as each unit ends, and its ``end``, the status that
    its units' endings fold and how each ended; Ctrl-C, its ``interrupted``, a warning
    naming the source of the unit that it stopped, none once that unit ended, and passes.
    """
    log = structlog.get_logger()
    started, ended, interrupted, finished = EVENTS[stage]
    log.info(started, sources=[each.unit.source for each in taken], dry_run=dry_run)
    try:
        for each in taken:
            source = each.unit.source
            with TRACER.start_as_current_span(ended, attributes={"kb_mcp.source": source}) as span:
                progress.acting = each.unit
                if not progress.ready(each.unit):
                    outcome = Outcome(ending="not run")
                elif said := each.preflight and each.preflight():
                    log.error(REFUSED[stage], source=source, reason=said)
                    outcome = Outcome.of(problems=(Problem(where=str(source), reason=said),))
                else:
                    outcome = each.act()
                span.set_attribute("kb_mcp.ending", outcome.ending)
                log.info(ended, source=source, ending=outcome.ending)
                progress.end(each.unit, outcome)
    except KeyboardInterrupt:
        acting = progress.acting
        log.warning(interrupted, source=None if acting is None else acting.source)
        progress.interrupted()
        raise
    finally:
        rows = [progress.entries[each.unit] for each in taken if each.unit in progress.outcomes]
        status = folded([*progress.own, *(row.ending for row in rows)])
        log.info(finished, status=int(status), sources=[f"{r.source}: {r.ending}" for r in rows])


def run_units(
    planned: Sequence[Planned],
    last: Sequence[Recorded],
    invocation: datetime,
    write: Callable[[tuple[Recorded, ...]], None],
    *,
    dry_run: bool,
) -> Done:
    """Run the units that this invocation takes, in their order; give what it did.

    It takes each unit whose last entry, among ``last``, did not end done, and each that
    follows one that it takes; the others keep their entries. A unit over the whole runs
    whatever the endings before it. ``write`` is given every unit's last entry, in their
    order, as each unit ends, those of this invocation started at ``invocation``. Ctrl-C
    ends the unit that it stops interrupted, each later one taken not run, and the
    invocation interrupted, even once every unit ended. The status is the most severe of
    the invocation's own ending and each unit's last, as ``folded`` gives it.
    """
    units = tuple(each.unit for each in planned)
    known = keyed(last)
    entries = {unit: known[unit] for unit in units if unit in known}
    taken = attempted(units, {unit: entry.ending for unit, entry in entries.items()})
    progress = Progress(
        units=units, taken=taken, entries=entries, invocation=invocation, write=write
    )
    try:
        for stage, group in groupby(
            (each for each in planned if each.unit in taken), key=lambda each: each.unit.stage
        ):
            if stage not in WHOLE:
                run_sources(stage, tuple(group), progress, dry_run=dry_run)
                continue
            for each in group:
                progress.acting = each.unit
                progress.end(each.unit, each.act())
    except KeyboardInterrupt:
        progress.interrupted()
    return progress.done()
