"""The work log's preparer: what its fetch kept in its copy store, written into the mirror.

The work log's declaration names this module, a ``Preparer``: ``preflight`` refuses
nothing, as a store missing or that does not read fails the source's row alone; and
``prepare`` reads the store, finds pandoc, then writes the mirror through the source's
rows of the cache of conversions, or in a dry run counts what that would do, and says the
problems, as the work log's events do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.fields import RepresentationError
from kb_mcp.kernel.outcome import Outcome, Problem
from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocFailedError, PandocMissingError
from kb_mcp.sources.worklog.fetch.adapters.copy_store import STORE, CopyStore
from kb_mcp.sources.worklog.prepare.app.prepare import plan_worklog, prepare_worklog

if TYPE_CHECKING:
    from kb_mcp.sources.stages import SourceRun
    from kb_mcp.sources.worklog.prepare.app.prepare import WorklogCounts, WorklogPlanned


def preflight(_run: SourceRun) -> str | None:
    """Refuse nothing: a copy store missing or that does not read fails the row alone."""
    return None


def prepare(run: SourceRun) -> Outcome[WorklogCounts | WorklogPlanned]:
    """Mirror the work log's copy store, or count what a dry run would, with the pandoc found now.

    A store that no fetch wrote fails the row, writing nothing, a problem by the copy store
    that names ``kb-mcp fetch`` and the source; so does one that does not read, naming its
    file and field; either is an error, ``worklog.store_unread``. Pandoc gone from PATH
    since the run began, or giving no version, fails it too, writing nothing: a problem by
    pandoc and an error, ``worklog.pandoc_failed``. The cache's rows of a former layout,
    should this prepare open it first, become rows of every source configured. Each
    problem is a warning, ``worklog.problem``, by its place, its reason and what it held
    back, never content; so is that a run with problems removed nothing,
    ``worklog.nothing_removed``.
    """
    source, settings = run.source.name, run.settings
    reason = f"none yet: `kb-mcp fetch {source}` writes it"
    try:
        copies = CopyStore(settings.copies, source).read()
    except RepresentationError as error:
        copies, reason = None, str(error)
    if copies is None:
        structlog.get_logger().error("worklog.store_unread", source=source, reason=reason)
        return Outcome.of(problems=(Problem(where=STORE, reason=reason),))
    if run.dry_run:
        return plan_worklog(copies, settings.docs, source=source)
    try:
        pandoc = Pandoc.find()
        converter = pandoc.org_converter()
    except (PandocMissingError, PandocFailedError) as error:
        structlog.get_logger().error("worklog.pandoc_failed", reason=str(error))
        return Outcome.of(problems=(Problem(where="pandoc", reason=str(error)),))
    adopted = tuple(each.name for each in run.sources)
    with conversions.opened(
        settings.conversions, lambda: converter, pandoc.org_markdown, source=source, adopted=adopted
    ) as cache:
        done = prepare_worklog(copies, settings.docs, cache, source=source)
    log = structlog.get_logger()
    for problem in done.problems:
        log.warning(
            "worklog.problem",
            where=problem.where,
            reason=problem.reason,
            held_back=done.counts.held_back[problem.where],
        )
    if done.problems:
        log.warning("worklog.nothing_removed", problems=len(done.problems))
    return done
