"""The work log's preparer: its folder, read in place, mirrored, as its role.

The work log's declaration names this module, a ``Preparer``: ``preflight`` refuses a
work log that is not a folder before any source starts, and ``prepare`` finds pandoc,
then mirrors the folder, or in a dry run counts what mirroring it would do, and says the
problems, as the work log's events do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocFailedError, PandocMissingError
from kb_mcp.sources.roles import Result
from kb_mcp.sources.worklog.prepare.app.prepare import (
    Outcome,
    Planned,
    mirror_worklog,
    plan_worklog,
)

if TYPE_CHECKING:
    from kb_mcp.kernel.output import Summary
    from kb_mcp.sources.roles import Run


class Prepared(Result):
    """A prepare: how it ended, and what it did or a dry run would, None when it could not."""

    mirrored: Outcome | Planned | None

    def text(self, summary: Summary) -> str:
        """Write the work log's counts as ``sync`` does; nothing when it could not run."""
        return "" if self.mirrored is None else self.mirrored.text(summary)


def preflight(run: Run) -> str | None:
    """Refuse a work log that is not a folder, by its setting, before any source starts."""
    folder = run.table.path
    if folder is None or not folder.is_dir():
        return "sources.worklog.path: not a folder"
    return None


def prepare(run: Run) -> Prepared:
    """Mirror the work log, or count what a dry run would, with the pandoc found now.

    Pandoc gone from PATH since the run began, or giving no version, fails it, writing
    nothing: an error, ``worklog.pandoc_failed``. Each problem is a warning,
    ``worklog.problem``, by its place, its reason and what it held back, never content;
    so is each warning, ``worklog.same_id``, and that a run with problems, not a dry
    run, removed nothing, ``worklog.nothing_removed``.
    """
    table = run.table
    act = plan_worklog if run.dry_run else mirror_worklog
    try:
        done = act(table.path, run.settings.docs, Pandoc.find(), archives=table.archives)
    except (PandocMissingError, PandocFailedError) as error:
        structlog.get_logger().error("worklog.pandoc_failed", reason=str(error))
        return Prepared(outcome="failed", mirrored=None)
    log = structlog.get_logger()
    for problem in done.problems:
        log.warning(
            "worklog.problem",
            where=problem.where,
            reason=problem.reason,
            held_back=problem.held_back,
        )
    for warning in done.warnings:
        log.warning("worklog.same_id", reason=warning)
    if done.problems and not run.dry_run:
        log.warning("worklog.nothing_removed", problems=len(done.problems))
    return Prepared(outcome="failed" if done.problems else "done", mirrored=done)
