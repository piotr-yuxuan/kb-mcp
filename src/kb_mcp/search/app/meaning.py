"""Search by meaning over an index: its model, connected once a build, and its vectors.

The model is the one the index names, never the setting, and only while the endpoint's
fingerprint for it is the index's: vectors of other weights would not compare with the
query's. Anything missing gives a reason instead of documents, so that the caller
answers by words and says why.
"""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING

from kb_mcp.kernel.record import Record
from kb_mcp.search.adapters.model_api import ModelError
from kb_mcp.search.domain.search import Score

if TYPE_CHECKING:
    from collections.abc import Callable

    from kb_mcp.search.adapters.embedding import Embedder
    from kb_mcp.search.adapters.sqlite_index import Reader
    from kb_mcp.search.domain.search import Embedded, Filters, Pieces

# The documents nearest a query that a search by meaning gives, at most.
DEPTH = 100
# Seconds during which a failed connection is not tried again: searches answer by words
# at once, rather than each wait on an endpoint that does not answer.
QUIET_S = 30.0
NO_VECTORS = (
    "the index holds no vectors; check the embedding model"
    " (kb-mcp model check), then run kb-mcp embed"
)
STALE = "{name}: the index was built with other weights of it; run kb-mcp embed"


class Nearest(Record):
    """The documents nearest a query, or why there are none to give."""

    found: dict[str, tuple[Score, int, int, int]]  # each path's score, then its best
    # piece's section number, and its start and end in the body
    reason: str = ""


class Meaning:
    """Searches by meaning, over whichever index each call reads."""

    def __init__(
        self, connect: Callable[[str], Embedder], clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Connect to the model an index names with ``connect``; time failures by ``clock``."""
        self._connect = connect
        self._clock = clock
        self._lock = threading.Lock()  # the SDK runs tools in worker threads
        # The build of the index last searched and its vectors; its connection; and why
        # there is none, and until when that stands.
        self._built: tuple[str, Pieces] | None = None
        self._embedder: Embedder | None = None
        self._failure = ("", 0.0)

    def nearest(self, reader: Reader, query: str, filters: Filters) -> Nearest:
        """Find the documents passing the filters whose best piece is nearest the query."""
        embedded = reader.embedded()
        if embedded is None:
            return Nearest(found={}, reason=NO_VECTORS)
        try:
            embedder, pieces = self.prepared(reader, embedded)
            fresh = embedder.fingerprint == embedded.fingerprint
            vector = embedder.query(query) if fresh else None
        except ModelError as error:
            return Nearest(found={}, reason=str(error))
        if vector is None:
            return Nearest(found={}, reason=STALE.format(name=embedded.model))
        kept = reader.kept(filters)
        allowed = None if kept is None else set(json.loads(kept))
        found = pieces.nearest(vector, allowed, DEPTH)
        return Nearest(
            found={
                path: (score, pieces.sections[index], pieces.offsets[index], pieces.ends[index])
                for path, (score, index) in found.items()
            }
        )

    def prepared(self, reader: Reader, embedded: Embedded) -> tuple[Embedder, Pieces]:
        """Give the connection to an index's model and its vectors, each made once a build.

        A connection that failed is not tried again for QUIET_S seconds, nor before the
        build changes once it succeeded, even when its fingerprint is not the index's.
        Raises ModelError.
        """
        with self._lock:
            build = reader.build()
            if self._built is None or self._built[0] != build:
                self._built = (build, reader.pieces())
                self._embedder, self._failure = None, ("", 0.0)
            if self._embedder is None:
                reason, until = self._failure
                if self._clock() < until:
                    raise ModelError(reason)
                try:
                    self._embedder = self._connect(embedded.model)
                except ModelError as error:
                    self._failure = (str(error), self._clock() + QUIET_S)
                    raise
            return self._embedder, self._built[1]
