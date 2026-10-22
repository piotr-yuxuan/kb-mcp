"""``mirror``: write the Markdown mirror from the raw store, offline."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from atlassian_offline_mcp.mirror.app.mirror import mirror
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore

if TYPE_CHECKING:
    import argparse

    from atlassian_offline_mcp.config.domain.settings import Loaded
    from atlassian_offline_mcp.kernel.output import Summary
    from atlassian_offline_mcp.mirror.app.mirror import Outcome


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Outcome | None]:
    """Mirror; exit 0, or 1 when pandoc is missing or something was not mirrored.

    What was not mirrored goes to standard error, by its place in the raw store and the
    reason, never its content. The outcome is given, None without pandoc.
    """
    settings = loaded.settings
    try:
        pandoc = Pandoc.find()
    except PandocMissingError as error:
        sys.stderr.write(f"{error}\n")
        return ExitStatus.FAILED, None
    outcome = mirror(RawStore(settings.raw), settings.docs, settings.site, pandoc.markdown)
    for problem in outcome.problems:
        sys.stderr.write(f"not mirrored: {problem.where}: {problem.reason}\n")
    if outcome.problems:
        sys.stderr.write("nothing was removed, since something was not mirrored\n")
    return ExitStatus.FAILED if outcome.problems else ExitStatus.OK, outcome


def text(outcome: Outcome, summary: Summary) -> str:
    """Write the counts of documents and files, then of problems.

    In detail, what the mirror does not show, by name, comes before the problems.
    """
    unsupported = sorted(outcome.unsupported.items()) if summary == "detailed" else []
    return (
        f"documents: {outcome.documents}\n"
        f"files written: {outcome.changes.written}\n"
        f"files unchanged: {outcome.changes.unchanged}\n"
        f"files removed: {outcome.changes.removed}\n"
        + "".join(f"not shown, {name}: {count}\n" for name, count in unsupported)
        + f"problems: {len(outcome.problems)}\n"
    )
