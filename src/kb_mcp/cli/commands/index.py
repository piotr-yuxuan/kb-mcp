"""``index``: update the search index of the mirror's words, never asking any endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.commands._runs import ended_text, whole_run

if TYPE_CHECKING:
    import argparse
    from datetime import datetime

    from kb_mcp.cli.domain.rows import Ended
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.exit_status import ExitStatus


def run(
    arguments: argparse.Namespace, loaded: Loaded, run: str, started: datetime
) -> tuple[ExitStatus, Ended | None]:
    """Update the index by words alone, as a run recorded; exit as its outcome ends.

    Its configuration records whether --rebuild was given. Nothing built is an error, and
    the index in place stays; each file skipped is a problem at each run, even when
    nothing changed, which exits 1. ``vectors.sqlite`` stays as it is.
    """
    return whole_run(arguments, loaded, run, started, {"--rebuild": arguments.rebuild})


# The run's id, then the outcome: its counts, then its problems and warnings.
text = ended_text
