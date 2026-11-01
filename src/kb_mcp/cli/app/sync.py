"""``sync``'s run: each source's roles, as its declaration names them, then the index.

The sources taken come as runs, one each, in the registry's order. Each role is loaded
by the module path that its source's declaration names; then every role's ``preflight``
says what it cannot go on with, before the first row. Then every fetcher runs, a row
for each source that has one, then every preparer, a row for each of a source's, then
the index, from the whole mirror. Each row runs even when an earlier one failed, since
the next reads what is on disk; Ctrl-C stops the run, and no later row runs, as does a
cache of pandoc's conversions that a preparer cannot use, such as one locked past the
wait, or one that breaks as it prepares. In a dry run each role says what it would do,
as its own run does, and the index does not run. Each row is a span, ``sync.step``,
naming its step and its source, within which its role's own spans and events are
recorded, those of the source's commands, or ``index``'s, as
``docs/reference/telemetry/sync.md`` says.
"""

from __future__ import annotations

import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace
from pydantic import ConfigDict, Field

from kb_mcp.cli.domain.rows import Row, Synced
from kb_mcp.cli.domain.sync import RANKED, Outcome, label
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record
from kb_mcp.search.app.indexing import Indexing, refresh
from kb_mcp.sources.roles import Fetcher, Preparer, Result, Run

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from kb_mcp.sources.declaration import Declared


TRACER = trace.get_tracer(__name__)


class SyncRefusedError(ValueError):
    """What a sync cannot run with, found before its first row; the message names it."""


class Index(Record):
    """The index's step: how it is built, from the whole mirror, whatever sources were taken."""

    indexing: Indexing


class Planned(Record):
    """A row to run: its step, its source's run, its role's preflight and what does the step."""

    step: str
    run: Run
    preflight: Callable[[Run], str | None]
    act: Callable[[Run], Result]


class Rows(Record):
    """A sync's rows so far, in their order."""

    model_config = ConfigDict(frozen=False)

    added: list[Row] = Field(default_factory=list)

    def add(self, row: Row) -> None:
        """Keep a row that ended within its step's span: log it, and set its outcome there."""
        trace.get_current_span().set_attribute("kb_mcp.outcome", row.outcome)
        structlog.get_logger().info(
            "sync.step", step=label(row.step, row.source), outcome=row.outcome
        )
        self.added.append(row)


def loaded[R: (Fetcher, Preparer)](declared: Declared, path: str, role: type[R]) -> R:
    """Load a role by the module path that its source's declaration names.

    Raises ``SyncRefusedError``, naming the source and the path, for a path that does
    not load, whatever its import raises, such as a syntax error in a module of the
    source's or its own error at import, or for what it names that lacks the role's
    methods.
    """
    try:
        found = pkgutil.resolve_name(path)
    except Exception as error:
        message = f"source {declared.name!r}: {path}: does not load: {error}"
        raise SyncRefusedError(message) from error
    if not isinstance(found, role):
        message = f"source {declared.name!r}: {path}: not a {role.__name__}"
        raise SyncRefusedError(message)
    return found


def index(
    step: Index, now: Callable[[], datetime], add: Callable[[Row], None], *, dry_run: bool
) -> None:
    """Build the index from the whole mirror at ``now``, unless a dry run, as index does."""
    with TRACER.start_as_current_span("sync.step", attributes={"kb_mcp.step": "index"}):
        if dry_run:
            add(Row(step="index", source=None, outcome="not run", result=None))
            return
        indexed = refresh(step.indexing, now())
        add(
            Row(
                step="index",
                source=None,
                outcome="done" if indexed and indexed.report.whole else "failed",
                result=indexed,
            )
        )


def sync(runs: Sequence[Run], step: Index, now: Callable[[], datetime], *, dry_run: bool) -> Synced:
    """Run each source's roles, then the index; return a row each, and the status they rank.

    Raises ``SyncRefusedError`` for a role that does not load, and for what a role's
    ``preflight`` refuses, both before the first row. A row's result is its role's;
    each fetcher runs, in the order of ``runs``, then each preparer, then the index,
    which a dry run leaves not run. Ctrl-C ends the row it stops as interrupted, and
    each later one as not run; the run is interrupted even when Ctrl-C comes once every
    row has ended. The status is the first of ``RANKED``'s outcomes that the run had,
    else OK. ``sync.start`` and ``sync.end`` say at INFO the rows planned and how each
    ended; ``sync.interrupted``, a warning, which row Ctrl-C stopped.
    """
    fetchers = [
        (run, loaded(run.declared, run.declared.fetcher, Fetcher))
        for run in runs
        if run.declared.fetcher is not None
    ]
    preparers = [
        (run, loaded(run.declared, path, Preparer))
        for run in runs
        for path in run.declared.preparers
    ]
    planned = [
        *(
            Planned(step="fetch", run=run, preflight=role.preflight, act=role.fetch)
            for run, role in fetchers
        ),
        *(
            Planned(step="prepare", run=run, preflight=role.preflight, act=role.prepare)
            for run, role in preparers
        ),
    ]
    refusal = next((said for each in planned if (said := each.preflight(each.run))), None)
    if refusal is not None:
        raise SyncRefusedError(refusal)
    log = structlog.get_logger()
    named = [*((each.step, each.run.declared.name) for each in planned), ("index", None)]
    log.info("sync.start", steps=[label(*row) for row in named], dry_run=dry_run)
    rows = Rows()
    outcomes: set[Outcome] = set()
    try:
        for each in planned:
            source = each.run.declared.name
            attributes = {"kb_mcp.step": each.step, "kb_mcp.source": source}
            with TRACER.start_as_current_span("sync.step", attributes=attributes):
                result = each.act(each.run)
                rows.add(Row(step=each.step, source=source, outcome=result.outcome, result=result))
        index(step, now, rows.add, dry_run=dry_run)
    except KeyboardInterrupt:
        stopped = len(rows.added)
        interrupted = label(*named[stopped]) if stopped < len(named) else None
        log.warning("sync.interrupted", step=interrupted)
        outcomes.add("interrupted")
        rows.added.extend(
            Row(
                step=name,
                source=source,
                outcome="interrupted" if number == stopped else "not run",
                result=None,
            )
            for number, (name, source) in enumerate(named[stopped:], stopped)
        )
    outcomes.update(row.outcome for row in rows.added)
    status = next((status for outcome, status in RANKED if outcome in outcomes), ExitStatus.OK)
    ended = [f"{label(row.step, row.source)}: {row.outcome}" for row in rows.added]
    log.info("sync.end", status=int(status), steps=ended)
    return Synced(exit_status=status, steps=tuple(rows.added))
