"""``embed``: give the index's chunks their vectors, by the setting's model, then prune."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from kb_mcp.cli.commands._embedding import indexing_of, open_endpoint
from kb_mcp.kernel.exit_status import ENDED, ExitStatus
from kb_mcp.kernel.outcome import Outcome
from kb_mcp.search.app.indexing import fill_and_prune

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.search.app.indexing import Filled


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Outcome[Filled]]:
    """Fill the index's chunks; exit as the outcome ends, 1 for a problem or none written.

    The endpoint must answer with the setting's model, whatever ``search_mode`` says,
    which this run does not read; when it does not, the index in place stays, with its
    vectors. Nothing filled is an error, the index named by ``kb-mcp index``; each
    document with a chunk that the endpoint refused, and each file that the index lacks,
    is a problem. A mirror changed since the index is a warning, whose exit status stays.
    """
    settings = loaded.settings
    opening = partial(open_endpoint, arguments, settings)
    outcome = fill_and_prune(indexing_of(settings, opening))
    return ENDED[outcome.ending], outcome


# The outcome writes itself: its counts, then its problems and warnings.
text = Outcome.text
