"""``reranker check``: check that the reranking server ranks with its model, or say what to run.

It never starts the server nor downloads a model: the user does, as the guide shows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from kb_mcp.kernel.endpoint import RERANKING
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.kernel.reranking import BOUND_S, LONGEST_TEXT
from kb_mcp.search.adapters.model_api import Bounds, endpoint
from kb_mcp.search.adapters.reranking import SEARCH, RerankError, rerank, served

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary

# The probe: a question, a passage that answers it, and one that does not.
PROBE = "How do I roll back a release?"
ANSWER = "To undo a release, roll back the service to its previous image."
UNRELATED = "The canteen opens at noon and closes at two."
# Each text of the request timed: as long as any that a search sends.
LONGEST = (ANSWER + " ") * (LONGEST_TEXT // len(ANSWER) + 1)
# The request timed is made once, however long it takes, within an evaluation's deadline.
TIMED = Bounds(deadline_s=300, attempts=1)


@dataclass(frozen=True)
class Checked:
    """A reranker that ranks: its scores of the probe, and one request at the depth, timed."""

    model: str
    url: str
    served: tuple[str, ...]  # the models that the server lists, none if it lists none
    answering: float
    unrelated: float
    depth: int
    seconds: float


def run(arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, Checked | None]:
    """Check; exit 1 when the server does not answer, is not a reranker, or ranks amiss."""
    settings = loaded.settings.rerank
    name = arguments.name or settings.model
    texts = (LONGEST[:LONGEST_TEXT],) * settings.depth
    with endpoint(settings.url, None, RERANKING, remote_allowed=False) as opened:
        try:
            listed = served(opened)
            probe = rerank(opened, name, PROBE, (ANSWER, UNRELATED), SEARCH)
            started = time.monotonic()
            rerank(opened, name, PROBE, texts, TIMED)
            seconds = time.monotonic() - started
        except RerankError as error:
            structlog.get_logger().error("reranker.not_ready", reason=str(error))
            return ExitStatus.FAILED, None
    answering, unrelated = probe.scores
    if unrelated >= answering:
        reason = (
            f"{name}: an unrelated passage scores as high as the answer; is the server"
            " started with --reranking, and its model a reranker?"
        )
        structlog.get_logger().error("reranker.not_ready", reason=reason)
        return ExitStatus.FAILED, None
    checked = Checked(
        model=name,
        url=settings.url,
        served=listed,
        answering=answering,
        unrelated=unrelated,
        depth=settings.depth,
        seconds=seconds,
    )
    return ExitStatus.OK, checked


def text(checked: Checked, _summary: Summary) -> str:
    """Write the probe's scores and the time at the depth; say what to mind."""
    probe = (
        f"{checked.model}, at {checked.url}: the answer scores {checked.answering:.4f},"
        f" an unrelated passage {checked.unrelated:.4f}"
    )
    timed = f"{checked.depth} texts of {LONGEST_TEXT} characters: {checked.seconds:.1f} s"
    lines = [probe, timed]
    if checked.served and checked.model not in checked.served:
        lines.append(
            f"the server lists {', '.join(checked.served)}: it reranks with its own model,"
            " whatever the name; give it this name with --alias"
        )
    if checked.seconds > BOUND_S:
        lines.append(f"slower than {BOUND_S:g} s, the bound on a search: lower rerank.depth")
    return "".join(f"{line}\n" for line in lines)
