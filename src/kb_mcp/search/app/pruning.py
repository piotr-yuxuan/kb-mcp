"""Pruning the vector cache to what the indexes on disk read, after an index by meaning.

The vectors kept are those that the index in place and the evaluation's indexes read,
and those of the index that the run wrote: the files are the truth, so that deleting an
evaluation's index lets the next prune drop its vectors. A prune holds the store's lock
exclusive, which no build in progress holds, so that it never deletes what a build
embeds; ``docs/reference/telemetry/embed.md`` lists what it records.
"""

from __future__ import annotations

import os
import sqlite3
import time
from copy import replace
from typing import TYPE_CHECKING, Literal

import structlog
from opentelemetry import metrics, trace

from kb_mcp.kernel.record import Record
from kb_mcp.search.adapters import sqlite_index, vector_cache
from kb_mcp.search.domain.indexes import UnavailableIndexError

if TYPE_CHECKING:
    from pathlib import Path

    from opentelemetry.trace import Span

    from kb_mcp.kernel.output import Detail

TRACER = trace.get_tracer(__name__)
METER = metrics.get_meter(__name__)
VECTORS = METER.create_counter(
    "kb_mcp.vectors", unit="{vector}", description="A prune's vectors, kept or pruned"
)
STORE_SIZE = METER.create_gauge(
    "kb_mcp.vectors.bytes", unit="By", description="The vector cache's size after a prune"
)

type PruneOutcome = Literal["pruned", "deferred", "held back", "failed"]
DEFERRED = "a build, or another prune, is using the vector cache; the next embed prunes it"
SKIPPED = "the index skipped a file, so it lacks documents of the mirror"
NO_DOCUMENT = "the index holds no document"
UNREADABLE = (
    "it cannot say which vectors it reads, built by words alone or by an earlier version, or"
    " damaged: rebuild the index with index --rebuild, then embed, an evaluation's with"
    " eval and its model and chunking, or delete it"
)
UNLISTED = (
    "it cannot be reached or listed, or it is a link below the evaluation's folder, which"
    " is not followed: make it readable, or put what it points to in its place; deleting it"
    " would let the next prune delete the vectors of the indexes it holds"
)
# How each outcome is said: its level, its event and the fields of its event.
SAID: dict[PruneOutcome, tuple[str, str, tuple[str, ...]]] = {
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
            "converted",
            "reclaimed",
            "reason",
        ),
    ),
    "deferred": ("info", "index.prune_deferred", ("reason",)),
    "held back": ("warning", "index.prune_skipped", ("outcome", "reason", "file")),
    "failed": ("warning", "index.prune_skipped", ("outcome", "reason", "file")),
}


class Written(Record):
    """What the index that a run wrote holds, as its prune reads it.

    The files of the mirror that it skipped, its documents, and the keys of its chunks'
    vectors, which another run's index renamed into place since may read no longer.
    """

    skipped: int
    documents: int
    keys: frozenset[str] = frozenset()


# Bytes in a megabyte, as the text says the vector cache's size.
MB = 1_000_000
# A vector cache made by an earlier version, converted to give freed space back.
CONVERTED = "; converted, as made by an earlier version, so that it gives freed space back"
# One whose conversion failed, its reason given, which the next prune tries again.
SHRINKS_NOT = (
    "; made by an earlier version, it is not yet converted to give freed space back ({}):"
    " the next prune tries again, given about the vector cache's size free on disk"
)


class Pruned(Record):
    """What a prune did: its outcome, the vectors kept and deleted, and the store's size.

    ``kept`` counts the vectors left in the store, ``kept_for_evaluation`` those of them
    that the evaluation's indexes alone read. ``shrinks`` says whether the store gives
    freed pages back to the file system at all, as one made before plan 023 never does;
    ``reclaimed``, whether this prune's went back.
    ``reason`` and ``file`` say why it did not prune, or why the space stayed.
    """

    outcome: PruneOutcome
    kept: int = 0
    kept_for_evaluation: int = 0
    deleted: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    seconds: float = 0.0
    shrinks: bool = False
    converted: bool = False
    reclaimed: bool = False
    reason: str = ""
    file: str | None = None

    def text(self, detail: Detail) -> str:
        """Say what the prune did, or why it did not prune."""
        if detail == "short":
            if self.outcome != "pruned":
                return f"vectors pruned: none, {self.outcome}\n"
            return f"vectors pruned: {self.deleted}\nvector cache: {self.bytes_after / MB:.1f} MB\n"
        if self.outcome != "pruned":
            place = f" ({self.file})" if self.file else ""
            return f"vector cache not pruned, {self.outcome}: {self.reason}{place}\n"
        written = (
            f"kept {self.kept} vectors ({self.kept_for_evaluation} for the evaluation"
            f" alone), pruned {self.deleted}; the vector cache from"
            f" {self.bytes_before / MB:.1f} to {self.bytes_after / MB:.1f} MB in"
            f" {self.seconds:.1f} s"
        )
        if self.converted:
            written += CONVERTED
        if not self.shrinks:
            written += SHRINKS_NOT.format(self.reason)
        elif not self.reclaimed:
            written += f"; space not reclaimed: {self.reason}"
        return f"{written}\n"


def shown(path: Path | str) -> str:
    """Write a path as text that every output takes, its bytes not UTF-8 as U+FFFD."""
    return os.fsencode(path).decode(errors="replace")


def said(pruned: Pruned, span: Span, started: float) -> Pruned:
    """Record a prune's outcome on its span and as its event; give it with its seconds."""
    pruned = replace(pruned, seconds=round(time.monotonic() - started, 3))
    span.set_attribute("kb_mcp.outcome", pruned.outcome)
    span.set_attribute("kb_mcp.deleted", pruned.deleted)
    level, event, names = SAID[pruned.outcome]
    fields = pruned.model_dump()
    getattr(structlog.get_logger(), level)(event, **{name: fields[name] for name in names})
    return pruned


def prune(store: Path, index: Path, evaluation_indexes: Path, written: Written) -> Pruned:
    """Delete from the store every vector that neither the index nor the evaluation reads.

    Nor any that the index that the run wrote reads, by ``written``'s keys. A file that
    it skipped, or no document, holds the prune back, as the index then lacks what the
    mirror still holds; so does an index that cannot say which vectors it
    reads, being by words alone or damaged, and a folder that cannot be listed, or a
    link, among the evaluation's. Either way, it would delete what the mirror still
    needs. A build holding the store's lock
    defers it. The store's own failure to delete fails it, nothing deleted; the span
    ``index.prune`` holds it.
    """
    started = time.monotonic()
    with TRACER.start_as_current_span("index.prune") as span:
        if written.skipped or not written.documents:
            reason = SKIPPED if written.skipped else NO_DOCUMENT
            return said(Pruned(outcome="held back", reason=reason), span, started)
        with vector_cache.exclusive(store) as held:
            if not held:
                return said(Pruned(outcome="deferred", reason=DEFERRED), span, started)
            keys: dict[Path, set[str]] = {}
            path = evaluation_indexes  # what the listing reads, before any index
            try:
                for path in [index, *sqlite_index.indexes_in(evaluation_indexes)]:
                    with sqlite_index.reading(path) as reader:
                        keys[path] = reader.keys()
            except OSError as error:
                unlisted = Pruned(
                    outcome="held back", reason=UNLISTED, file=shown(error.filename or path)
                )
                return said(unlisted, span, started)
            except UnavailableIndexError, sqlite3.DatabaseError:
                held_back = Pruned(outcome="held back", reason=UNREADABLE, file=shown(path))
                return said(held_back, span, started)
            read = keys.pop(index) | written.keys
            evaluation = set().union(*keys.values()) - read
            kept = read | evaluation
            try:
                with vector_cache.opened(store) as opened:
                    alone = opened.count(evaluation)
                    swept = opened.prune(kept)
            except sqlite3.Error as error:
                return said(Pruned(outcome="failed", reason=str(error)), span, started)
        VECTORS.add(swept.kept, {"kb_mcp.outcome": "kept"})
        VECTORS.add(swept.deleted, {"kb_mcp.outcome": "pruned"})
        STORE_SIZE.set(swept.bytes_after)
        pruned = Pruned(
            outcome="pruned",
            kept=swept.kept,
            kept_for_evaluation=alone,
            deleted=swept.deleted,
            bytes_before=swept.bytes_before,
            bytes_after=swept.bytes_after,
            shrinks=swept.shrinks,
            converted=swept.converted,
            reclaimed=swept.shrinks and not swept.unreclaimed,
            reason=swept.unreclaimed,
        )
        return said(pruned, span, started)
