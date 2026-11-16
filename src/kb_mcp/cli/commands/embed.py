"""``embed``: give the index's chunks their vectors, by the setting's model, then prune."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.commands._runs import ended_text, whole_run
from kb_mcp.cli.domain.command import EMBED

if TYPE_CHECKING:
    import argparse

    from kb_mcp.cli.domain.rows import Ended
    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.exit_status import ExitStatus


def run(arguments: argparse.Namespace, loaded: Loaded, run: str) -> tuple[ExitStatus, Ended | None]:
    """Fill the index's chunks, as a run recorded; exit as the outcome ends.

    The endpoint must answer with the setting's model, whatever ``search_mode`` says,
    which this run does not read; when it does not, the index in place stays, with its
    vectors. Nothing filled is an error, the index named by ``kb-mcp index``; each
    document with a chunk that the endpoint refused, and each file that the index lacks,
    is a problem. A mirror changed since the index is a warning, whose exit status stays.
    The consent to an endpoint off this machine is this invocation's, never recorded.
    """
    return whole_run(arguments, loaded, run, EMBED, {})


# The run's id, then the outcome: its counts, then its problems and warnings.
text = ended_text
