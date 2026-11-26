"""Reranking through a server: the order that its scores give, or why there is none.

Its failures are remembered for QUIET_S seconds, but for a refusal, the request's.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics

from kb_mcp.kernel.records import Record
from kb_mcp.search.adapters.reranking import RerankError
from kb_mcp.search.app.meaning import QUIET_S

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from kb_mcp.search.adapters.reranking import Reranked

# The searches that kept the order given, by why: the failure's kind, or "quiet" while
# one is remembered.
FALLBACKS = metrics.get_meter(__name__).create_counter(
    "kb_mcp.rerank.fallbacks", unit="{fallback}", description="Searches not reranked"
)


class Reordered(Record):
    """The order of the texts, the best first, by their places; or why there is none."""

    order: tuple[int, ...] | None
    reason: str = ""  # why the texts were not reranked


class Reranking:
    """Reranks the first documents of searches, as many as its depth, through a server."""

    def __init__(
        self,
        score: Callable[[str, Sequence[str]], Reranked],
        depth: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Score with ``score``, a query and its texts; rerank ``depth`` documents at most."""
        self.depth = depth
        self._score = score
        self._clock = clock
        self._lock = threading.Lock()  # the SDK runs tools in worker threads
        self._failure = ("", 0.0)  # why the last failure remembered, and until when

    def reorder(self, query: str, texts: Sequence[str]) -> Reordered:
        """Order the texts by their relevance to the query, the highest first, ties as given.

        The request is made outside the lock, which guards only the failure remembered. A
        failure is warned of once: the next ones within QUIET_S seconds are quiet.
        """
        with self._lock:
            reason, until = self._failure
        if self._clock() < until:
            FALLBACKS.add(1, {"kb_mcp.rerank.fallback": "quiet"})
            return Reordered(order=None, reason=reason)
        try:
            scores = self._score(query, texts).scores
        except RerankError as error:
            FALLBACKS.add(1, {"kb_mcp.rerank.fallback": error.kind})
            structlog.get_logger().warning("rerank.fallback", kind=error.kind, reason=str(error))
            if error.kind != "refused":
                with self._lock:
                    self._failure = (str(error), self._clock() + QUIET_S)
            return Reordered(order=None, reason=str(error))
        return Reordered(order=tuple(sorted(range(len(scores)), key=lambda place: -scores[place])))
