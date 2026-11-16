"""The work log's fetcher: its folder, read in place, into its source's copy store.

The work log's declaration names this module, a ``Fetcher``: ``preflight`` refuses a work
log that is not a folder, which fails its row alone, and ``fetch`` reads it into its copy
store, or in a dry run says what that would change, and says the problems, as the work
log's events do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.outcome import Outcome, Problem
from kb_mcp.sources.worklog.fetch.adapters.copy_store import STORE, CopyStoreBusyError
from kb_mcp.sources.worklog.fetch.app.fetching import fetch_worklog

if TYPE_CHECKING:
    from kb_mcp.sources.stages import SourceRun
    from kb_mcp.sources.worklog.fetch.app.fetching import WorklogFetched

# What to do while another run writes the copy store.
BUSY = "another run is writing it; try again once that run ends"


def preflight(run: SourceRun) -> str | None:
    """Refuse a work log that is not a folder, by its setting, before it is read."""
    folder = run.source_table.path
    if folder is None or not folder.is_dir():
        return f"{run.source.paths[0]}: not a folder"
    return None


def fetch(run: SourceRun) -> Outcome[WorklogFetched]:
    """Read the run's work log into its copy store, or in a dry run say what that would change.

    Another run writing the store fails the fetch before it reads, a problem by the copy
    store and an error, ``fetch.store_busy``; so does a store that does not read, its
    error ``fetch.refused`` naming the file and the field. Both errors name the source.
    Each problem is a warning, ``worklog.problem``, by its place, its reason and what it
    held back, never content; so is that a fetch with problems, not a dry run, found no
    document gone, ``worklog.nothing_removed``.
    """
    source = run.source.name
    try:
        done = fetch_worklog(run.settings, run.source_table, source, run.now, dry_run=run.dry_run)
    except CopyStoreBusyError:
        store = str(run.settings.copies / source)
        structlog.get_logger().error("fetch.store_busy", source=source, store=store, hint=BUSY)
        return Outcome.of(problems=(Problem(where=STORE, reason=BUSY),))
    except RepresentationError as error:
        structlog.get_logger().error("fetch.refused", source=source, reason=str(error))
        return Outcome.of(problems=(Problem(where=STORE, reason=str(error)),))
    log = structlog.get_logger()
    for problem in done.problems:
        log.warning(
            "worklog.problem",
            where=problem.where,
            reason=problem.reason,
            held_back=done.counts.held_back[problem.where],
        )
    if done.problems and not run.dry_run:
        log.warning("worklog.nothing_removed", problems=len(done.problems))
    return done
