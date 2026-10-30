"""Confluence's and Jira's fetcher: a download of one source's targets, as its role.

Both declarations name this module, a ``Fetcher``: ``preflight`` and ``fetch`` read the
source that a run is for from its declaration, by its kinds, and fetch that source's
targets alone, its table's spaces or projects, over the period that its options give.
``fetch_targets`` downloads one source's targets, or plans their download, and says
what went wrong as ``download``'s events do; ``download`` and ``sync``'s Atlassian step
run it too, for each source apart.
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
from kb_mcp.sources.roles import Result

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from kb_mcp.config.domain.settings import Settings
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources import roles
    from kb_mcp.sources.atlassian.fetch.app.download import Targets
    from kb_mcp.sources.roles import Run

# How a download or its plan ended, by its status. A download that Ctrl-C stops raises
# KeyboardInterrupt, so its status is never none here.
FETCHED: dict[ExitStatus | None, roles.Outcome] = {
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
        """Write the download's counts as ``download`` does; nothing when it could not start."""
        return "" if self.downloaded is None else self.downloaded.text(summary)


def targets_of(run: Run) -> Targets:
    """Read the targets of the source that ``run`` is for, by its kinds: spaces or projects.

    Confluence's pages and blog posts are listed per space, Jira's issues searched per
    project; the period is its options', as ``read_targets`` reads them.
    """
    kinds = {each.name for each in run.declared.types}
    return read_targets(
        run.table.spaces if kinds & {Page.kind, BlogPost.kind} else (),
        run.table.projects if Issue.kind in kinds else (),
        run.options,
        run.now(),
    )


def preflight(run: Run) -> str | None:
    """Say why the fetch cannot start: an --until before --since, or a coverage not read."""
    try:
        targets_of(run).windows(RawStore(run.settings.raw).coverage(), run.now())
    except (PeriodError, RepresentationError) as error:
        return str(error)
    return None


def fetch(run: Run) -> Fetched:
    """Download what changed of the run's source, or in a dry run plan it, by ``fetch_targets``."""
    return fetch_targets(run.settings, targets_of(run), run.now, run.sleep, dry_run=run.dry_run)


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
    ``download.store_busy``; each target that failed is a warning,
    ``download.target_failed``, and a sign-in that no longer holds an error,
    ``download.sign_in_needed``, saying how to sign in again; both errors name the
    source, since each source's fetch can give them.
    """
    act = plan if dry_run else download
    source = targets.source
    try:
        downloaded = act(settings, targets, now, sleep)
    except StoreBusyError:
        structlog.get_logger().error(
            "download.store_busy", source=source, store=str(settings.raw), hint=BUSY
        )
        return Fetched(outcome="failed", downloaded=None)
    log = structlog.get_logger()
    for target in downloaded.failed_targets:
        log.warning("download.target_failed", target=target)
    if downloaded.status == ExitStatus.SIGN_IN_AGAIN:
        log.error("download.sign_in_needed", source=source, hint=sign_in(settings).again)
    return Fetched(outcome=FETCHED[downloaded.status], downloaded=downloaded)
