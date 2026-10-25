"""Pruning the vector store to what the indexes on disk read, after an index by meaning.

The vectors kept are those that the index in place and the evaluation's indexes read:
the files are the truth, so that deleting an evaluation's index lets the next prune drop
its vectors. A prune holds the store's lock exclusive, which no build in progress holds,
so that it never deletes what a build embeds; ``docs/reference/telemetry/index.md``
lists what it records.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Literal

import structlog
from opentelemetry import metrics, trace

from atlassian_offline_mcp.search.adapters import sqlite_index, vector_store

if TYPE_CHECKING:
    from pathlib import Path

    from opentelemetry.trace import Span

TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
VECTORS = METER.create_counter(
    "aom.vectors", unit="{vector}", description="A prune's vectors, kept or pruned"
)
STORE_SIZE = METER.create_gauge(
    "aom.vectors.bytes", unit="By", description="The vector store's size after a prune"
)

type Outcome = Literal["pruned", "deferred", "held back", "failed"]
DEFERRED = "a build is using the vector store; the next index prunes it"
UNREADABLE = (
    "it cannot say which vectors it reads: rebuild it, with index or with eval --model and"
    " --chunking, or delete it"
)
# How each outcome is said: its level, its event and the fields of its event.
SAID: dict[Outcome, tuple[str, str, tuple[str, ...]]] = {
    "pruned": (
        "info",
        "index.pruned",
        (
            "kept",
            "kept_for_evaluation",
            "deleted",
            "bytes_before",
            "bytes_after",
            "seconds",
            "shrinks",
            "reclaimed",
            "reason",
        ),
    ),
    "deferred": ("info", "index.prune_deferred", ("reason",)),
    "held back": ("warning", "index.prune_skipped", ("outcome", "reason", "file")),
    "failed": ("warning", "index.prune_skipped", ("outcome", "reason", "file")),
}


@dataclass(frozen=True)
class Pruned:
    """What a prune did: its outcome, the vectors kept and deleted, and the store's size.

    ``kept_for_evaluation`` counts the vectors that the evaluation's indexes alone read.
    ``shrinks`` says whether the store gives freed pages back to the file system at all,
    as one made before plan 023 never does; ``reclaimed``, whether this prune's were.
    ``reason`` and ``file`` say why it did not prune, or why the space stayed.
    """

    outcome: Outcome
    kept: int = 0
    kept_for_evaluation: int = 0
    deleted: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    seconds: float = 0.0
    shrinks: bool = False
    reclaimed: bool = False
    reason: str = ""
    file: str | None = None


def said(pruned: Pruned, span: Span, started: float) -> Pruned:
    """Record a prune's outcome on its span and as its event; give it with its seconds."""
    pruned = replace(pruned, seconds=round(time.monotonic() - started, 3))
    span.set_attribute("aom.outcome", pruned.outcome)
    span.set_attribute("aom.deleted", pruned.deleted)
    level, event, names = SAID[pruned.outcome]
    fields = asdict(pruned)
    getattr(structlog.get_logger(), level)(event, **{name: fields[name] for name in names})
    return pruned


def prune(store: Path, index: Path, evaluation_indexes: Path, incomplete: str = "") -> Pruned:
    """Delete from the store every vector that neither the index nor the evaluation reads.

    ``incomplete`` says why the build that just ended is not the mirror whole (a file
    skipped, no document), which holds the prune back, as an index that cannot say which
    vectors it reads does: it would delete what the mirror still needs. A build holding
    the store's lock defers it. The store's own failure to delete fails it, nothing
    deleted; the span ``index.prune`` holds it.
    """
    started = time.monotonic()
    with TRACER.start_as_current_span("index.prune") as span:
        if incomplete:
            return said(Pruned("held back", reason=incomplete), span, started)
        with vector_store.exclusive(store) as held:
            if not held:
                return said(Pruned("deferred", reason=DEFERRED), span, started)
            keys: dict[Path, set[str]] = {}
            for path in [index, *sqlite_index.indexes_in(evaluation_indexes)]:
                try:
                    with sqlite_index.reading(path) as reader:
                        keys[path] = reader.keys()
                except sqlite_index.UnavailableIndexError:
                    held_back = Pruned("held back", reason=UNREADABLE, file=str(path))
                    return said(held_back, span, started)
            read = keys.pop(index)
            evaluation = set().union(*keys.values()) - read
            kept = read | evaluation
            try:
                with vector_store.opened(store) as opened:
                    swept = opened.prune(kept)
            except sqlite3.Error as error:
                return said(Pruned("failed", reason=str(error)), span, started)
        VECTORS.add(len(kept), {"aom.outcome": "kept"})
        VECTORS.add(swept.deleted, {"aom.outcome": "pruned"})
        STORE_SIZE.set(swept.bytes_after)
        pruned = Pruned(
            "pruned",
            kept=len(kept),
            kept_for_evaluation=len(evaluation),
            deleted=swept.deleted,
            bytes_before=swept.bytes_before,
            bytes_after=swept.bytes_after,
            shrinks=swept.shrinks,
            reclaimed=not swept.unreclaimed,
            reason=swept.unreclaimed,
        )
        return said(pruned, span, started)
