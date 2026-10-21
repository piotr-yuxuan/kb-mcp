"""Search by meaning over an index: its model, loaded once, and its vectors, read once a build.

The model is the one the index names, never the setting, and only when the catalogue's
fingerprint for it is the index's: vectors of another version would not compare with
the query's. Anything missing gives a reason instead of documents, so that the caller
answers by words and says why.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters import embedding
from atlassian_offline_mcp.adapters.embedding import CATALOGUE, ModelError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from atlassian_offline_mcp.adapters.embedding import Embedder
    from atlassian_offline_mcp.adapters.sqlite_index import Reader
    from atlassian_offline_mcp.domain.search import Filters, Pieces, Score

# The documents nearest a query that a search by meaning gives, at most.
DEPTH = 100
NO_VECTORS = (
    "the index holds no vectors; pull a model (atlassian-offline-mcp model pull),"
    " then run atlassian-offline-mcp index"
)
STALE = "{name}: the index was built with another version of it; run atlassian-offline-mcp index"


@dataclass(frozen=True)
class Nearest:
    """The documents nearest a query, or why there are none to give."""

    found: dict[str, tuple[Score, int, int]]  # each path's score, then its best piece's
    # section number and offset in the body
    reason: str = ""


class Meaning:
    """Searches by meaning, over whichever index each call reads."""

    def __init__(
        self, models: Path, load: Callable[[str, Path], Embedder] = embedding.load
    ) -> None:
        """Load models from the folder ``models``, with ``load``."""
        self._models = models
        self._load = load
        self._lock = threading.Lock()  # the SDK runs tools in worker threads
        self._embedder: Embedder | None = None
        self._pieces: tuple[datetime, Pieces] | None = None

    def nearest(self, reader: Reader, query: str, filters: Filters) -> Nearest:
        """Find the documents passing the filters whose best piece is nearest the query."""
        embedded = reader.embedded()
        if embedded is None:
            return Nearest({}, NO_VECTORS)
        current = CATALOGUE.get(embedded.model)
        if current is None or current.fingerprint != embedded.fingerprint:
            return Nearest({}, STALE.format(name=embedded.model))
        try:
            with self._lock:
                if self._embedder is None or self._embedder.fingerprint != embedded.fingerprint:
                    self._embedder = self._load(embedded.model, self._models)
                built = reader.built_at()
                if self._pieces is None or self._pieces[0] != built:
                    self._pieces = (built, reader.pieces())
                embedder, pieces = self._embedder, self._pieces[1]
            vector = embedder.query(query)
        except ModelError as error:
            return Nearest({}, str(error))
        kept = reader.kept(filters)
        allowed = None if kept is None else set(json.loads(kept))
        found = pieces.nearest(vector, allowed, DEPTH)
        return Nearest(
            {
                path: (score, pieces.sections[index], pieces.offsets[index])
                for path, (score, index) in found.items()
            }
        )
