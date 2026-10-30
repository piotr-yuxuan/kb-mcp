"""``sync``'s steps: Atlassian's download and each source's mirror, the work log's, the index.

Each step runs even when an earlier one failed, since the next reads what is on disk;
Ctrl-C stops the run, and no later step runs, as does a cache of pandoc's conversions
that the mirror cannot use, such as one locked past the wait, or one that breaks during
the mirror. What can be refused is refused before the
first step: an --until before --since, and a work log that is not a folder. A dry
run plans the download and counts the work log, and writes nothing. Each row is a span,
``sync.step``, within which its step's own spans and events are recorded, those of
``download``, ``mirror``, the work log or ``index``, as
``docs/reference/telemetry/sync.md`` says. ``mirror``'s command makes its rows here too,
one per source, by ``prepare_source``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import structlog
from opentelemetry import trace
from pydantic import ConfigDict, Field

from kb_mcp.cli.domain.rows import Row, Synced
from kb_mcp.cli.domain.sync import RANKED, Outcome, label
from kb_mcp.config.domain.settings import Settings
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.record import Record
from kb_mcp.mirror.adapters.pandoc import Pandoc
from kb_mcp.search.app.indexing import Indexing, refresh
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.app.download import Targets
from kb_mcp.sources.atlassian.fetch.app.fetcher import fetch_targets
from kb_mcp.sources.atlassian.prepare.app.prepare import PREPARED
from kb_mcp.sources.atlassian.prepare.app.preparer import prepare_kinds
from kb_mcp.sources.worklog.prepare.app.preparer import prepare_folder

if TYPE_CHECKING:
    from collections.abc import Sequence


TRACER = trace.get_tracer(__name__)


class SyncRefusedError(ValueError):
    """What a sync cannot run with, found before its first step; the message names it."""


class Atlassian(Record):
    """Confluence's and Jira's step: what to download, then the sources to mirror, in order.

    Each source of ``sources`` is one of ``PREPARED``.
    """

    targets: Targets
    sources: tuple[str, ...]

    @property
    def rows(self) -> tuple[tuple[str, str | None], ...]:
        """Give the step's rows, each its step and source: the download, then each mirror."""
        return (("download", None), *(("mirror", source) for source in self.sources))


class Worklog(Record):
    """The work log's step: its folder, read in place, and whether archives are mirrored."""

    rows: ClassVar[tuple[tuple[str, str | None], ...]] = (("worklog", "worklog"),)

    folder: Path
    archives: bool


class Index(Record):
    """The index's step: how it is built, from the whole mirror, whatever sources were taken."""

    rows: ClassVar[tuple[tuple[str, str | None], ...]] = (("index", None),)

    indexing: Indexing


class Context(Record):
    """What every step needs: the settings, pandoc, the clock, the pause, and a dry run."""

    settings: Settings
    pandoc: Pandoc
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    dry_run: bool


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


def prepare_source(settings: Settings, pandoc: Pandoc, source: str) -> Row:
    """Mirror one Atlassian source, of ``PREPARED``, from the raw store; give its row.

    It mirrors as ``prepare_kinds`` does, through the source's rows of the cache, with
    the site of the Atlassian account.
    """
    site = settings.accounts.atlassian.site
    prepared = prepare_kinds(settings, site, pandoc, source, PREPARED[source])
    return Row(step="mirror", source=source, outcome=prepared.outcome, result=prepared.mirrored)


def atlassian(context: Context, step: Atlassian, add: Callable[[Row], None]) -> None:
    """Download, or plan the download, then mirror each source of the step, unless a dry run.

    Each mirror runs whatever the download did, since it reads what is stored, a row of
    its own. What went wrong is said by the events of ``fetch_targets`` and of
    ``prepare_kinds``.
    """
    settings = context.settings
    with TRACER.start_as_current_span("sync.step", attributes={"kb_mcp.step": "download"}):
        fetched = fetch_targets(
            settings, step.targets, context.now, context.sleep, dry_run=context.dry_run
        )
        add(Row(step="download", source=None, outcome=fetched.outcome, result=fetched.downloaded))
    for source in step.sources:
        with TRACER.start_as_current_span("sync.step", attributes={"kb_mcp.step": "mirror"}):
            if context.dry_run:
                add(Row(step="mirror", source=source, outcome="not run", result=None))
            else:
                add(prepare_source(settings, context.pandoc, source))


def worklog(context: Context, step: Worklog, add: Callable[[Row], None]) -> None:
    """Mirror the work log, or count what mirroring it would do, as ``prepare_folder`` does."""
    with TRACER.start_as_current_span("sync.step", attributes={"kb_mcp.step": "worklog"}):
        prepared = prepare_folder(
            step.folder,
            context.settings.docs,
            context.pandoc,
            archives=step.archives,
            dry_run=context.dry_run,
        )
        add(
            Row(
                step="worklog", source="worklog", outcome=prepared.outcome, result=prepared.mirrored
            )
        )


def index(context: Context, step: Index, add: Callable[[Row], None]) -> None:
    """Build the index from the whole mirror, unless a dry run; its problems as index says."""
    with TRACER.start_as_current_span("sync.step", attributes={"kb_mcp.step": "index"}):
        if context.dry_run:
            add(Row(step="index", source=None, outcome="not run", result=None))
            return
        indexed = refresh(step.indexing, context.now())
        add(
            Row(
                step="index",
                source=None,
                outcome="done" if indexed and indexed.report.whole else "failed",
                result=indexed,
            )
        )


def sync(context: Context, steps: Sequence[Atlassian | Worklog | Index]) -> Synced:
    """Run the steps in their order; return a row per step and the exit status they rank.

    Raises ``SyncRefusedError`` for a work log that is not a folder, and PeriodError for
    an --until before --since, both before the first step. Ctrl-C ends the step it
    stops as interrupted, and each later one as not run; the run is interrupted even
    when Ctrl-C comes once every step has ended. The status is the first of
    ``RANKED``'s outcomes that the run had, else OK. ``sync.start`` and ``sync.end`` say
    at INFO the rows planned and how each ended; ``sync.interrupted``, a warning, which
    row Ctrl-C stopped.
    """
    for step in steps:
        if isinstance(step, Atlassian):
            step.targets.windows(RawStore(context.settings.raw).coverage(), context.now())
        elif isinstance(step, Worklog) and not step.folder.is_dir():
            message = "sources.worklog.path: not a folder"
            raise SyncRefusedError(message)
    log = structlog.get_logger()
    planned = [row for step in steps for row in step.rows]
    log.info("sync.start", steps=[label(*row) for row in planned], dry_run=context.dry_run)
    rows = Rows()
    outcomes: set[Outcome] = set()
    try:
        for step in steps:
            if isinstance(step, Atlassian):
                atlassian(context, step, rows.add)
            elif isinstance(step, Worklog):
                worklog(context, step, rows.add)
            else:
                index(context, step, rows.add)
    except KeyboardInterrupt:
        stopped = len(rows.added)
        interrupted = label(*planned[stopped]) if stopped < len(planned) else None
        log.warning("sync.interrupted", step=interrupted)
        outcomes.add("interrupted")
        rows.added.extend(
            Row(
                step=name,
                source=source,
                outcome="interrupted" if number == stopped else "not run",
                result=None,
            )
            for number, (name, source) in enumerate(planned[stopped:], stopped)
        )
    outcomes.update(row.outcome for row in rows.added)
    status = next((status for outcome, status in RANKED if outcome in outcomes), ExitStatus.OK)
    ended = [f"{label(row.step, row.source)}: {row.outcome}" for row in rows.added]
    log.info("sync.end", status=int(status), steps=ended)
    return Synced(exit_status=status, steps=tuple(rows.added))
