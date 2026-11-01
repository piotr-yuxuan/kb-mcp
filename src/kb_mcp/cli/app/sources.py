"""``fetch``'s run: each source's role, as its declaration names it, a row each.

The sources taken come as runs, one each, in the registry's order. Each role is loaded by
the module path that its source's declaration names; then every role's ``preflight`` says
what it cannot go on with, before the first row. Then each runs, a row for each, even when
an earlier one failed, since the next reads what is on disk; Ctrl-C stops the run, and no
later row runs. In a dry run each role says what it would do. Each row is a span of the
step's, ``fetch.source``, naming its source, within which its role's own spans and events
are recorded, as ``docs/reference/telemetry/fetch.md`` says.
"""

from __future__ import annotations

import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from kb_mcp.cli.domain.rows import Ran, Row
from kb_mcp.cli.domain.sources import RANKED
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record
from kb_mcp.sources.roles import Fetcher, Preparer, Result, Run

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.cli.domain.sources import Outcome
    from kb_mcp.sources.declaration import Declared


TRACER = trace.get_tracer(__name__)


class SourcesRefusedError(ValueError):
    """What a run cannot go on with, found before its first row; the message names it."""


class Planned(Record):
    """A row to run: its source's run, its role's preflight and what does the step."""

    run: Run
    preflight: Callable[[Run], str | None]
    act: Callable[[Run], Result]


def loaded[R: (Fetcher, Preparer)](declared: Declared, path: str, role: type[R]) -> R:
    """Load a role by the module path that its source's declaration names.

    Raises ``SourcesRefusedError``, naming the source and the path, for a path that does
    not load, whatever its import raises, such as a syntax error in a module of the
    source's or its own error at import, or for what it names that lacks the role's
    methods.
    """
    try:
        found = pkgutil.resolve_name(path)
    except Exception as error:
        message = f"source {declared.name!r}: {path}: does not load: {error}"
        raise SourcesRefusedError(message) from error
    if not isinstance(found, role):
        message = f"source {declared.name!r}: {path}: not a {role.__name__}"
        raise SourcesRefusedError(message)
    return found


def fetch_each(runs: Sequence[Run], *, dry_run: bool) -> Ran:
    """Run each source's fetcher; return a row each, and the status that they rank.

    Raises ``SourcesRefusedError`` for a role that does not load, and for what a role's
    ``preflight`` refuses, both before the first row. Ctrl-C ends the row it stops as
    interrupted, and each later one as not run; the run is interrupted even when Ctrl-C
    comes once every row has ended. The status is the first of ``RANKED``'s outcomes that
    the run had, else OK. ``fetch.start`` and ``fetch.end`` say at INFO the sources planned
    and how each ended, ``fetch.source`` each as it ends; ``fetch.interrupted``, a warning,
    which source Ctrl-C stopped.
    """
    roles = (
        (run, loaded(run.declared, run.declared.fetcher, Fetcher))
        for run in runs
        if run.declared.fetcher is not None
    )
    planned = [Planned(run=run, preflight=role.preflight, act=role.fetch) for run, role in roles]
    refusal = next((said for each in planned if (said := each.preflight(each.run))), None)
    if refusal is not None:
        raise SourcesRefusedError(refusal)
    log = structlog.get_logger()
    names = [each.run.declared.name for each in planned]
    log.info("fetch.start", sources=names, dry_run=dry_run)
    rows: list[Row] = []
    outcomes: set[Outcome] = set()
    try:
        for each, source in zip(planned, names, strict=True):
            attributes = {"kb_mcp.source": source}
            with TRACER.start_as_current_span("fetch.source", attributes=attributes) as span:
                result = each.act(each.run)
                span.set_attribute("kb_mcp.outcome", result.outcome)
                log.info("fetch.source", source=source, outcome=result.outcome)
                rows.append(Row(source=source, outcome=result.outcome, result=result))
    except KeyboardInterrupt:
        stopped = len(rows)
        log.warning("fetch.interrupted", source=names[stopped] if stopped < len(names) else None)
        outcomes.add("interrupted")
        rows.extend(
            Row(source=name, outcome="interrupted" if at == stopped else "not run", result=None)
            for at, name in enumerate(names[stopped:], stopped)
        )
    outcomes.update(row.outcome for row in rows)
    status = next((status for outcome, status in RANKED if outcome in outcomes), ExitStatus.OK)
    log.info("fetch.end", status=int(status), sources=[f"{r.source}: {r.outcome}" for r in rows])
    return Ran(exit_status=status, sources=tuple(rows))
