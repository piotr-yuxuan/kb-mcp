"""``fetch``'s and ``prepare``'s run: each source's fetcher or preparers, as declared.

The sources taken come as runs, one each, in the registry's order. Each fetcher or
preparer is loaded by the module path that its source's declaration names; then each one's
``preflight`` says
what it cannot go on with, before the first row. Then each runs, a row for each, even when
an earlier one failed, since the next reads what is on disk; Ctrl-C stops the run, and no
later row runs. In a dry run each says what it would do. Each row is a span of the
stage's, ``fetch.source`` or ``prepare.source``, naming its source, within which its
fetcher's or preparer's
own spans and events are recorded, as ``docs/reference/telemetry/fetch.md`` and
``prepare.md`` say.
"""

from __future__ import annotations

import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from kb_mcp.cli.domain.rows import RANKED, Ran, Row
from kb_mcp.cli.domain.sources import FETCH, PREPARE
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record
from kb_mcp.sources.stages import Fetcher, Preparer, Result, SourceRun

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.cli.domain.rows import RowOutcome
    from kb_mcp.sources.declaration import Source


TRACER = trace.get_tracer(__name__)


class EventNames(Record):
    """What a stage records, each name written out, so that a search for a page's name finds it."""

    start: str
    source: str
    interrupted: str
    end: str


RECORDED = {
    FETCH: EventNames(
        start="fetch.start",
        source="fetch.source",
        interrupted="fetch.interrupted",
        end="fetch.end",
    ),
    PREPARE: EventNames(
        start="prepare.start",
        source="prepare.source",
        interrupted="prepare.interrupted",
        end="prepare.end",
    ),
}


class SourcesRefusedError(ValueError):
    """What a run cannot go on with, found before its first row; the message names it."""


class PlannedRow(Record):
    """A row to run: its source's run, its fetcher's or preparer's preflight, and its act."""

    run: SourceRun
    preflight: Callable[[SourceRun], str | None]
    act: Callable[[SourceRun], Result]


def loaded[R: (Fetcher, Preparer)](declared: Source, path: str, interface: type[R]) -> R:
    """Load a fetcher or a preparer by the module path that its source's declaration names.

    Raises ``SourcesRefusedError``, naming the source and the path, for a path that does
    not load, whatever its import raises, such as a syntax error in a module of the
    source's or its own error at import, or for what it names that lacks the interface's
    methods.
    """
    try:
        found = pkgutil.resolve_name(path)
    except Exception as error:
        message = f"source {declared.name!r}: {path}: does not load: {error}"
        raise SourcesRefusedError(message) from error
    if not isinstance(found, interface):
        message = f"source {declared.name!r}: {path}: not a {interface.__name__}"
        raise SourcesRefusedError(message)
    return found


def planned(stage: str, runs: Sequence[SourceRun]) -> list[PlannedRow]:
    """Load what each run takes part in this stage with: its fetcher, or each of its preparers."""
    if stage == FETCH:
        fetchers = (
            (run, loaded(run.source, run.source.fetcher, Fetcher))
            for run in runs
            if run.source.fetcher is not None
        )
        return [
            PlannedRow(run=run, preflight=each.preflight, act=each.fetch) for run, each in fetchers
        ]
    preparers = (
        (run, loaded(run.source, path, Preparer)) for run in runs for path in run.source.preparers
    )
    return [
        PlannedRow(run=run, preflight=each.preflight, act=each.prepare) for run, each in preparers
    ]


def run_each(stage: str, runs: Sequence[SourceRun]) -> Ran:
    """Run each source's part in this stage; return a row each, and the status that they rank.

    Each run's ``dry_run`` is what its fetcher or preparer reads, and the events follow the
    runs. Raises ``SourcesRefusedError`` for one that does not load, and for what its
    ``preflight`` refuses, after its source's name and the stage, both before the first
    row. Ctrl-C ends the row it stops as interrupted, and each later one as not run; the
    run is interrupted even when Ctrl-C comes once every row has ended. The status is the
    first of ``RANKED``'s outcomes that the run had, else OK. A stage's ``start`` and ``end``
    say at INFO the sources planned and how each ended, its ``source`` each as it ends; its
    ``interrupted``, a warning, which source Ctrl-C stopped.
    """
    plans = planned(stage, runs)
    refusal = next(
        (
            f"source {each.run.source.name!r}: {stage}: {said}"
            for each in plans
            if (said := each.preflight(each.run))
        ),
        None,
    )
    if refusal is not None:
        raise SourcesRefusedError(refusal)
    log = structlog.get_logger()
    recorded = RECORDED[stage]
    names = [each.run.source.name for each in plans]
    log.info(recorded.start, sources=names, dry_run=any(run.dry_run for run in runs))
    rows: list[Row] = []
    outcomes: set[RowOutcome] = set()
    try:
        for each, source in zip(plans, names, strict=True):
            attributes = {"kb_mcp.source": source}
            with TRACER.start_as_current_span(recorded.source, attributes=attributes) as span:
                result = each.act(each.run)
                span.set_attribute("kb_mcp.outcome", result.outcome)
                log.info(recorded.source, source=source, outcome=result.outcome)
                rows.append(Row(source=source, outcome=result.outcome, result=result))
    except KeyboardInterrupt:
        stopped = len(rows)
        log.warning(recorded.interrupted, source=names[stopped] if stopped < len(names) else None)
        outcomes.add("interrupted")
        rows.extend(
            Row(source=name, outcome="interrupted" if at == stopped else "not run", result=None)
            for at, name in enumerate(names[stopped:], stopped)
        )
    outcomes.update(row.outcome for row in rows)
    status = next((status for outcome, status in RANKED if outcome in outcomes), ExitStatus.OK)
    log.info(recorded.end, status=int(status), sources=[f"{r.source}: {r.outcome}" for r in rows])
    return Ran(exit_status=status, sources=tuple(rows))
