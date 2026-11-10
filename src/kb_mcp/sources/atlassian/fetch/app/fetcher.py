"""Confluence's and Jira's fetcher: one source's targets fetched into the raw store.

Both declarations name this module, a ``Fetcher``: ``preflight`` and ``fetch`` read the
source that a run is for from its declaration, by its resource types, and fetch that source's
targets alone, its table's spaces or projects, over the period that its options give.
``fetch_targets`` fetches them, or plans their fetch, and says what went wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.outcome import Outcome, Problem
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore, StoreBusyError
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import choose_sign_in
from kb_mcp.sources.atlassian.fetch.app.fetching import plan_fetch, read_targets, run_fetch
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.atlassian.fetch.domain.period import PeriodError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.sources.atlassian.fetch.app.fetching import FetchCounts, Targets
    from kb_mcp.sources.stages import SourceRun

# What to do while another run writes the raw store.
BUSY = "another run is writing it; try again once that run ends"


def targets_of(run: SourceRun) -> Targets:
    """Read the targets of ``run``'s source, by its resource types: spaces or projects.

    Confluence's pages and blog posts are listed per space, Jira's issues searched per
    project; the period is its options', as ``read_targets`` reads them.
    """
    resource_types = {each.name for each in run.source.resource_types}
    return read_targets(
        run.source_table.spaces
        if resource_types & {Page.resource_type, BlogPost.resource_type}
        else (),
        run.source_table.projects if Issue.resource_type in resource_types else (),
        run.options,
        run.now(),
    )


def preflight(run: SourceRun) -> str | None:
    """Say why the fetch cannot start: an --until before --since, or a store's record not read.

    Those are the records that a fetch reads before its first request: what is
    covered, and for a fetch of spaces what answered as gone, which is Confluence's. So
    that one stops no fetch of projects.
    """
    store = RawStore(run.settings.raw)
    try:
        targets = targets_of(run)
        targets.windows(store.coverage(), run.now())
        if targets.spaces:
            store.tombstones()
    except (PeriodError, RepresentationError) as error:
        return str(error)
    return None


def fetch(run: SourceRun) -> Outcome[FetchCounts]:
    """Fetch what changed of the run's source, or in a dry run plan it, by ``fetch_targets``.

    What ``preflight`` refuses may still come once the run began: a period read at a
    later fetch's start, or a record damaged since. It fails this fetch alone, a problem
    by the source and an error, ``fetch.refused``, naming the source, and the run's next
    rows go on.
    """
    try:
        return fetch_targets(run.settings, targets_of(run), run.now, run.sleep, dry_run=run.dry_run)
    except (PeriodError, RepresentationError) as error:
        structlog.get_logger().error("fetch.refused", source=run.source.name, reason=str(error))
        return Outcome(
            ending="failed", problems=(Problem(where=run.source.name, reason=str(error)),)
        )


def fetch_targets(
    settings: Settings,
    targets: Targets,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    *,
    dry_run: bool,
) -> Outcome[FetchCounts]:
    """Fetch these targets, one source's, or plan their fetch; say what went wrong.

    Another run writing the raw store fails the fetch before it starts, a problem by the
    raw store and an error, ``fetch.store_busy``; each target that failed is a warning,
    ``fetch.target_failed``, and a sign-in that no longer holds an error,
    ``fetch.sign_in_needed``, saying how to sign in again; both errors name the source,
    since each source's fetch can give them.
    """
    act = plan_fetch if dry_run else run_fetch
    source = targets.source
    try:
        outcome = act(settings, targets, now, sleep)
    except StoreBusyError:
        structlog.get_logger().error(
            "fetch.store_busy", source=source, store=str(settings.raw), hint=BUSY
        )
        return Outcome(ending="failed", problems=(Problem(where="raw store", reason=BUSY),))
    if outcome.ending == "sign in again":
        structlog.get_logger().error(
            "fetch.sign_in_needed", source=source, hint=choose_sign_in(settings).again
        )
    return outcome
