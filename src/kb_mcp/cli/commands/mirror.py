"""``mirror``: write the Markdown mirror from the raw store, offline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mirror.adapters import conversions
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from kb_mcp.mirror.app.mirror import mirror
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary
    from kb_mcp.mirror.app.mirror import Outcome


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Outcome | None]:
    """Mirror; exit 0, or 1 when something was not mirrored or pandoc went missing.

    The entry refuses a run without pandoc on PATH, exit 2, before anything is asked:
    this run finds it again for its path, and exits 1 only if it went in between, an
    error. Pandoc's conversions are kept in the data folder's cache, open for the run.
    What was not mirrored is a warning, by its place in the raw store and the reason,
    never its content, as is that nothing was then removed. The outcome is given, None
    without pandoc.
    """
    settings = loaded.settings
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        structlog.get_logger().error("mirror.pandoc_missing", reason=str(error))
        return ExitStatus.FAILED, None
    with conversions.opened(settings.conversions, pandoc.html_converter, pandoc.markdown) as cache:
        outcome = mirror(RawStore(settings.raw), settings.docs, settings.site, cache)
    for problem in outcome.problems:
        structlog.get_logger().warning(
            "mirror.not_mirrored", where=problem.where, reason=problem.reason
        )
    if outcome.problems:
        structlog.get_logger().warning("mirror.nothing_removed", problems=len(outcome.problems))
    return ExitStatus.FAILED if outcome.problems else ExitStatus.OK, outcome


def text(outcome: Outcome, summary: Summary) -> str:
    """Write the counts of documents, of conversions run and reused, of files, then of problems.

    In detail, what the mirror does not show, by name, comes before the problems.
    """
    unsupported = sorted(outcome.unsupported.items()) if summary == "detailed" else []
    return (
        f"documents: {outcome.documents}\n"
        f"converted by pandoc: {outcome.converted}\n"
        f"reused from the cache: {outcome.reused}\n"
        f"files written: {outcome.changes.written}\n"
        f"files unchanged: {outcome.changes.unchanged}\n"
        f"files removed: {outcome.changes.removed}\n"
        + "".join(f"not shown, {name}: {count}\n" for name, count in unsupported)
        + f"problems: {len(outcome.problems)}\n"
    )
