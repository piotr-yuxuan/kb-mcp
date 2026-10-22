"""Build the search index from the Markdown mirror, and from nothing else.

With an embedding, each piece of each section also gets its vector: from the vector
store when it holds the piece's text, else from the model, then kept there. A piece
whose text the model refuses has no vector, and its document is named.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlassian_offline_mcp.adapters import markdown, sqlite_index, vector_store
from atlassian_offline_mcp.adapters.fields import RepresentationError
from atlassian_offline_mcp.domain.search import Embedded, passages, sections

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from atlassian_offline_mcp.adapters.embedding import Embedder


class MirrorMissingError(Exception):
    """No mirror to index; the message names where it was looked for."""


@dataclass
class Report:
    """What a build indexed, and which files it skipped and why."""

    types: Counter[str] = field(default_factory=Counter)  # documents indexed per type
    sections: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # each path and reason
    pieces: int = 0  # pieces with a vector
    embedded: int = 0  # texts that the model embedded, the store lacking them
    unembedded: list[str] = field(default_factory=list)  # paths with a piece refused


@dataclass(frozen=True)
class Embedding:
    """What gives an index its vectors: a model, the vector store, and who hears progress."""

    embedder: Embedder
    store: Path
    progress: Callable[[int, int], None] = lambda _done, _total: None


def build_index(
    docs: Path, index: Path, built_at: datetime, embedding: Embedding | None = None
) -> Report:
    """Index every document of the mirror at ``docs`` into a new index at ``index``.

    A file that cannot be read, that ``markdown.load`` refuses, or whose document is
    there already is skipped, and named in the report with a reason that holds no
    content. The index replaces the old one only once complete. Raises ModelError when
    the embedding fails; the old index then stays. A piece whose text the model refuses
    is left without a vector, and its document named in the report.
    """
    if not docs.is_dir():
        message = f"no mirror at {docs}: build it with `atlassian-offline-mcp mirror`"
        raise MirrorMissingError(message)
    report = Report()
    model = embedding.embedder if embedding else None
    embedded = Embedded(model.name, model.fingerprint, model.dimensions) if model else None
    pending: list[tuple[int, int, int, str, str]] = []  # each piece's section, span,
    # key and document
    texts: dict[str, str] = {}  # what each key's vector embeds
    with sqlite_index.building(index, built_at, embedded) as writer:
        for file in markdown.documents(docs):
            path = file.relative_to(docs).as_posix()
            try:
                # Line endings are kept as written, so that a body reads back exactly.
                text = file.read_text(encoding="utf-8", newline="")
                front, body = markdown.load(text, path)
                cut = sections(body)
                first = writer.add(path, front, cut)
            except UnicodeDecodeError:
                reason = "not UTF-8"
            except OSError as error:
                reason = f"not readable ({type(error).__name__})"
            except (RepresentationError, sqlite_index.DuplicateDocumentError) as error:
                reason = str(error).removeprefix(f"{path}: ")
            else:
                report.types[front.type] += 1
                report.sections += len(cut)
                for number, start, end, text in passages(front.title, cut) if model else ():
                    key = vector_store.key(model.fingerprint, text)
                    pending.append((first + number, start, end, key, path))
                    texts[key] = text
                continue
            writer.skip()
            report.skipped.append((path, reason))
        if embedding is not None:
            with vector_store.opened(embedding.store) as store:
                found, report.embedded = store.vectors(
                    texts, embedding.embedder.documents, embedding.progress
                )
            kept = [(*piece[:3], found[piece[3]]) for piece in pending if piece[3] in found]
            writer.add_pieces(kept)
            report.pieces = len(kept)
            report.unembedded = sorted({piece[4] for piece in pending if piece[3] not in found})
    return report
