"""``index`` and ``embed``: one recorded run of the command's stage over the whole."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.commands._runs import ended_text, whole_run
from kb_mcp.cli.domain.command import INDEX

if TYPE_CHECKING:
    import argparse
    from datetime import datetime

    from kb_mcp.cli.domain.rows import Ended
    from kb_mcp.config.settings import Loaded
    from kb_mcp.kernel.names import ExitStatus


def run(
    arguments: argparse.Namespace, loaded: Loaded, run: str, started: datetime
) -> tuple[ExitStatus, Ended | None]:
    """Run the command's stage over the whole, as a run recorded; exit as its outcome ends.

    ``index`` updates the index by words alone, never asking an endpoint, and its
    configuration records whether --rebuild was given. Nothing built is an error, and the
    index in place stays; each file skipped is a problem at each run, even when nothing
    changed, which exits 1. ``vectors.sqlite`` stays as it is.

    ``embed`` fills the index's chunks, then prunes the vector cache. The endpoint must
    answer with the setting's model, whatever ``search_mode`` says, which this run does
    not read; when it does not, the index in place stays, with its vectors. Nothing filled
    is an error; each document with a chunk that the endpoint refused, and each file that
    the index lacks, is a problem. A mirror changed since the index is a warning, whose
    exit status stays. The consent to an endpoint off this machine is this invocation's,
    never recorded.
    """
    options = {"--rebuild": arguments.rebuild} if arguments.command.name == INDEX else {}
    return whole_run(arguments, loaded, run, started, options)


# The run's id, then the outcome: its counts, then its problems and warnings.
text = ended_text
