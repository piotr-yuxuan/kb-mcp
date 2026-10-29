"""Reranking through a server: the order that its scores give, or why there is none.

The server's failures are remembered for QUIET_S seconds, as the embedding endpoint's
are: searches then keep their own order at once, rather than each wait on a server
that does not answer. A refusal is the request's, not the server's: it is not
remembered, and the next search asks again.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics

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


@dataclass(frozen=True)
class Reordered:
    """The order of the texts, the best first, by their places; or why there is none."""

    order: tuple[int, ...] | None
    reason: str = ""  # why the texts were not reranked
    kind: str = ""  # the failure's kind, or "quiet" while one is remembered


class Reranking:
    """Reranks the first documents of searches, as many as its depth, through a server."""

    def __init__(
        self,
        score: Callable[[str, Sequence[str]], Reranked],
        depth: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Score with ``score``, a query and its texts; rerank ``depth`` documents at most.

        Failures are timed by ``clock``.
        """
        self.depth = depth
        self._score = score
        self._clock = clock
        self._lock = threading.Lock()  # the SDK runs tools in worker threads
        self._failure = ("", 0.0)  # why the last failure remembered, and until when

    def reorder(self, query: str, texts: Sequence[str]) -> Reordered:
        """Order the texts by their relevance to the query, the highest first, ties as given.

        The request is made outside the lock, which guards only the failure remembered. A
        search not reranked is counted in ``kb_mcp.rerank.fallbacks`` by why, and a failure
        said by the warning ``rerank.fallback``, once: the next ones are quiet.
        """
        with self._lock:
            reason, until = self._failure
        if self._clock() < until:
            FALLBACKS.add(1, {"kb_mcp.rerank.fallback": "quiet"})
            return Reordered(None, reason, "quiet")
        try:
            scores = self._score(query, texts).scores
        except RerankError as error:
            FALLBACKS.add(1, {"kb_mcp.rerank.fallback": error.kind})
            structlog.get_logger().warning("rerank.fallback", kind=error.kind, reason=str(error))
            if error.kind != "refused":
                with self._lock:
                    self._failure = (str(error), self._clock() + QUIET_S)
            return Reordered(None, str(error), error.kind)
        return Reordered(tuple(sorted(range(len(scores)), key=lambda place: -scores[place])))
