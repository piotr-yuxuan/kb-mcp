"""``fetch``'s and ``prepare``'s run: each source's fetcher or preparers, as declared, a row each.

Each row is a span of the stage's, ``fetch.source`` or ``prepare.source``, naming its
source, within which its fetcher's or preparer's own spans and events are recorded, as
``docs/reference/telemetry/fetch.md`` and ``prepare.md`` say; ``run_each`` says the rest.
"""

from __future__ import annotations

import pkgutil
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from kb_mcp.cli.domain.rows import Ran, Row
from kb_mcp.cli.domain.sources import FETCH, PREPARE
from kb_mcp.kernel.exit_status import folded
from kb_mcp.sources.stages import Fetcher, Preparer, SourceRun

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.kernel.exit_status import Ending
    from kb_mcp.sources.declaration import Source


TRACER = trace.get_tracer(__name__)
# What each stage records, by name, written out so that a search for an event finds it:
# its start, each source's row, Ctrl-C, its end.
EVENTS = {
    FETCH: ("fetch.start", "fetch.source", "fetch.interrupted", "fetch.end"),
    PREPARE: ("prepare.start", "prepare.source", "prepare.interrupted", "prepare.end"),
}


class SourcesRefusedError(ValueError):
    """What a run cannot go on with, found before its first row; the message names it."""


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


def planned(stage: str, runs: Sequence[SourceRun]) -> list[tuple[SourceRun, Fetcher | Preparer]]:
    """Load what each run takes part in this stage with: its fetcher, or each of its preparers."""
    if stage == FETCH:
        return [
            (run, loaded(run.source, run.source.fetcher, Fetcher))
            for run in runs
            if run.source.fetcher is not None
        ]
    return [
        (run, loaded(run.source, path, Preparer)) for run in runs for path in run.source.preparers
    ]


def run_each(stage: str, runs: Sequence[SourceRun]) -> Ran:
    """Run each source's part in this stage; return a row each, and the status that they fold.

    Each run's ``dry_run`` is what its fetcher or preparer reads, and the events follow the
    runs. Raises ``SourcesRefusedError`` for one that does not load, and for what its
    ``preflight`` refuses, after its source's name and the stage, both before the first
    row. A row that failed stops no other: the next reads what is on disk. Only Ctrl-C
    stops the run: it ends the row it stops as interrupted, and each later one as not run;
    the run is interrupted even when Ctrl-C comes once every row has ended. The status is the
    most severe of the rows' endings, as ``folded`` gives it. A stage's ``start`` and
    ``end`` say at INFO the sources planned and how each ended, its ``source`` each as it
    ends; its ``interrupted``, a warning, which source Ctrl-C stopped.
    """
    plans = planned(stage, runs)
    refusal = next(
        (
            f"source {run.source.name!r}: {stage}: {said}"
            for run, each in plans
            if (said := each.preflight(run))
        ),
        None,
    )
    if refusal is not None:
        raise SourcesRefusedError(refusal)
    log = structlog.get_logger()
    started, row_event, interrupted, finished = EVENTS[stage]
    names = [run.source.name for run, _ in plans]
    log.info(started, sources=names, dry_run=any(run.dry_run for run in runs))
    rows: list[Row] = []
    own: list[Ending] = []  # the run's own ending, beside its rows'
    try:
        for (run, each), source in zip(plans, names, strict=True):
            attributes = {"kb_mcp.source": source}
            with TRACER.start_as_current_span(row_event, attributes=attributes) as span:
                outcome = each.fetch(run) if stage == FETCH else each.prepare(run)
                span.set_attribute("kb_mcp.ending", outcome.ending)
                log.info(row_event, source=source, ending=outcome.ending)
                rows.append(Row(source=source, **dict(outcome)))
    except KeyboardInterrupt:
        stopped = len(rows)
        own.append("interrupted")
        log.warning(interrupted, source=names[stopped] if stopped < len(names) else None)
        rows.extend(
            Row(source=name, ending="interrupted" if at == stopped else "not run")
            for at, name in enumerate(names[stopped:], stopped)
        )
    status = folded([*own, *(row.ending for row in rows)])
    log.info(finished, status=int(status), sources=[f"{r.source}: {r.ending}" for r in rows])
    return Ran(exit_status=status, sources=tuple(rows))
