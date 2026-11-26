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

    ``index`` never asks an endpoint, and leaves ``vectors.sqlite`` as it is; each file
    skipped is a problem at each run, even when nothing changed, which exits 1. ``embed``
    fills the index's chunks by the setting's model, whatever ``search_mode`` says, then
    prunes the vector cache; a mirror changed since the index is a warning, whose exit
    status stays, and its consent to an endpoint off this machine is never recorded; each
    document with a chunk refused, and each file that the index lacks, is a problem; an
    endpoint that answers with another model leaves the index and its vectors in place.
    Nothing built or filled is an error, and the index in place stays. Only ``index``
    records an option, ``--rebuild``.
    """
    options = {"--rebuild": arguments.rebuild} if arguments.command.name == INDEX else {}
    return whole_run(arguments, loaded, run, started, options)


# The run's id, then the outcome: its counts, then its problems and warnings.
text = ended_text
