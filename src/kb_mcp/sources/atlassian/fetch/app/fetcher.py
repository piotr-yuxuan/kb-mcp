"""Confluence's and Jira's fetcher: a download of one source's targets, as its role.

Both declarations name this module, a ``Fetcher``: ``preflight`` and ``fetch`` read the
source that a run is for from its declaration, by its kinds, and fetch that source's
targets alone, its table's spaces or projects, over the period that its options give.
``fetch_targets`` downloads them, or plans their download, and says what went wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore, StoreBusyError
from kb_mcp.sources.atlassian.fetch.adapters.sign_in import sign_in
from kb_mcp.sources.atlassian.fetch.app.download import Outcome, download, plan, read_targets
from kb_mcp.sources.atlassian.fetch.domain.content import BlogPost, Issue, Page
from kb_mcp.sources.atlassian.fetch.domain.period import PeriodError
from kb_mcp.sources.stages import Result

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources import stages
    from kb_mcp.sources.atlassian.fetch.app.download import Targets
    from kb_mcp.sources.stages import SourceRun

# How a download or its plan ended, by its status. A download that Ctrl-C stops raises
# KeyboardInterrupt, so its status is never none here.
FETCHED: dict[ExitStatus | None, stages.Outcome] = {
    ExitStatus.OK: "done",
    ExitStatus.FAILED: "failed",
    ExitStatus.SIGN_IN_AGAIN: "sign in",
}
# What to do while another run writes the raw store.
BUSY = "another run is writing it; try again once that run ends"


class Fetched(Result):
    """A fetch: how it ended, and what the download did, None when it could not start."""

    downloaded: Outcome | None

    def text(self, summary: Summary) -> str:
        """Write the download's counts; nothing when it could not start."""
        return "" if self.downloaded is None else self.downloaded.text(summary)


def targets_of(run: SourceRun) -> Targets:
    """Read the targets of ``run``'s source, by its resource types: spaces or projects.

    Confluence's pages and blog posts are listed per space, Jira's issues searched per
    project; the period is its options', as ``read_targets`` reads them.
    """
    resource_types = {each.name for each in run.source.resource_types}
    return read_targets(
        run.source_table.spaces if resource_types & {Page.kind, BlogPost.kind} else (),
        run.source_table.projects if Issue.kind in resource_types else (),
        run.options,
        run.now(),
    )


def preflight(run: SourceRun) -> str | None:
    """Say why the fetch cannot start: an --until before --since, or a store's record not read.

    Those are the records that a download reads before its first request: what is
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


def fetch(run: SourceRun) -> Fetched:
    """Download what changed of the run's source, or in a dry run plan it, by ``fetch_targets``.

    What ``preflight`` refuses may still come once the run began: a period read at a
    later fetch's start, or a record damaged since. It fails this fetch alone, an error,
    ``fetch.refused``, naming the source, and the run's next rows go on.
    """
    try:
        return fetch_targets(run.settings, targets_of(run), run.now, run.sleep, dry_run=run.dry_run)
    except (PeriodError, RepresentationError) as error:
        structlog.get_logger().error("fetch.refused", source=run.source.name, reason=str(error))
        return Fetched(outcome="failed", downloaded=None)


def fetch_targets(
    settings: Settings,
    targets: Targets,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    *,
    dry_run: bool,
) -> Fetched:
    """Download these targets, one source's, or plan their download; say what went wrong.

    Another run writing the raw store fails the fetch before it starts, an error,
    ``fetch.store_busy``; each target that failed is a warning, ``fetch.target_failed``,
    and a sign-in that no longer holds an error, ``fetch.sign_in_needed``, saying how to
    sign in again; both errors name the source, since each source's fetch can give them.
    """
    act = plan if dry_run else download
    source = targets.source
    try:
        downloaded = act(settings, targets, now, sleep)
    except StoreBusyError:
        structlog.get_logger().error(
            "fetch.store_busy", source=source, store=str(settings.raw), hint=BUSY
        )
        return Fetched(outcome="failed", downloaded=None)
    log = structlog.get_logger()
    for target in downloaded.failed_targets:
        log.warning("fetch.target_failed", target=target)
    if downloaded.status == ExitStatus.SIGN_IN_AGAIN:
        log.error("fetch.sign_in_needed", source=source, hint=sign_in(settings).again)
    return Fetched(outcome=FETCHED[downloaded.status], downloaded=downloaded)
