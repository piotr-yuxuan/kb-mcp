"""Vectors in the index: each piece embedded once per model, kept across builds (plan 011)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
import pytest

from atlassian_offline_mcp.adapters import vector_store
from atlassian_offline_mcp.adapters.embedding import CATALOGUE, ModelError, load
from atlassian_offline_mcp.adapters.sqlite_index import reading
from atlassian_offline_mcp.app.indexing import Embedding, build_index
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.search import Embedded
from tests.mirrors import MOMENT, fillers, page, write
from tests.tiny_model import DIMENSIONS, registered

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from numpy.typing import NDArray

    from atlassian_offline_mcp.adapters.embedding import OnnxEmbedder

BODY = "# Rollback\n\nUndo the payout.\n\n## Release\n\nThe deploy of the seller service.\n"
FILLER_PAGES = 5
FAILED = 1


@dataclass
class Counting:
    """An embedder that counts the texts it embeds, and may fail after some calls."""

    inner: OnnxEmbedder
    texts: list[str] = field(default_factory=list)
    fail_after: int | None = None

    @property
    def name(self) -> str:
        """The inner model's name."""
        return self.inner.name

    @property
    def fingerprint(self) -> str:
        """The inner model's fingerprint."""
        return self.inner.fingerprint

    @property
    def dimensions(self) -> int:
        """The inner model's dimensions."""
        return self.inner.dimensions

    def documents(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """Count, then embed; fail as a model would once ``fail_after`` calls are done."""
        if self.fail_after is not None and len(self.texts) >= self.fail_after:
            message = "tiny: does not embed (Fail)"
            raise ModelError(message)
        self.texts += texts
        return self.inner.documents(texts)

    def query(self, text: str) -> NDArray[np.float32]:
        """Embed a query."""
        return self.inner.query(text)


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a data directory whose mirror has a few pages, and the tiny model pulled."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    fillers(tmp_path / "data" / "docs", FILLER_PAGES)
    write(tmp_path / "data" / "docs", page("196845", "Rollback"), BODY)
    registered(tmp_path / "data" / "models", monkeypatch)
    return tmp_path / "data"


def build(data: Path, embedder: Counting) -> None:
    """Build the data directory's index with an embedder and its vector store."""
    build_index(data / "docs", data / "index.sqlite", MOMENT, Embedding(embedder, data / "v.db"))


def counting(data: Path) -> Counting:
    """Return a counting embedder over the tiny model."""
    return Counting(load("tiny", data / "models"))


def test_an_index_with_a_model_holds_a_unit_vector_for_every_piece(data: Path) -> None:
    """Every section has a piece here, each with the model's dimensions and unit length."""
    embedder = counting(data)
    build(data, embedder)
    with reading(data / "index.sqlite") as reader:
        assert reader.embedded() == Embedded("tiny", CATALOGUE["tiny"].fingerprint, DIMENSIONS)
        pieces = reader.pieces()
        assert len(pieces.documents) == reader.summary().sections == len(embedder.texts)
        assert np.allclose(np.linalg.norm(pieces.matrix, axis=1), 1)
    assert "Rollback\nRelease\nThe deploy of the seller service." in embedder.texts


def test_a_rebuild_embeds_only_the_pieces_that_changed(data: Path) -> None:
    """One section edited: one text embedded; the vectors equal a fresh build's."""
    build(data, counting(data))
    write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "sellers"))
    again = counting(data)
    build(data, again)
    assert again.texts == ["Rollback\nRelease\nThe deploy of the sellers service."]
    with reading(data / "index.sqlite") as reader:
        kept = reader.pieces().matrix
    (data / "v.db").unlink()
    build(data, counting(data))
    with reading(data / "index.sqlite") as reader:
        assert np.array_equal(reader.pieces().matrix, kept)


def test_another_fingerprint_reuses_no_vector(data: Path, monkeypatch: MonkeyPatch) -> None:
    """The same name with another prefix is another model: every text is embedded again."""
    first = counting(data)
    build(data, first)
    changed = replace(CATALOGUE["tiny"], document_prefix="alpha ")
    monkeypatch.setitem(CATALOGUE, "tiny", changed)
    second = counting(data)
    build(data, second)
    assert len(second.texts) == len(first.texts)


def test_an_interrupted_build_keeps_the_batches_it_finished(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """A model failing after its first batch: the old index stays, that batch is kept."""
    monkeypatch.setattr(vector_store, "BATCH", 2)
    failing = Counting(load("tiny", data / "models"), fail_after=2)
    with pytest.raises(ModelError):
        build(data, failing)
    assert not (data / "index.sqlite").exists()
    assert len(failing.texts) == vector_store.BATCH
    resumed = counting(data)
    build(data, resumed)
    (data / "v.db").unlink()
    whole = counting(data)
    build(data, whole)
    assert sorted(failing.texts + resumed.texts) == sorted(whole.texts)


def config(data: Path, model: str) -> list[str]:
    """Write settings naming a model; return the options that point the command at them."""
    settings = data.parent / "config.toml"
    settings.write_text(f"model = {json.dumps(model)}\n", encoding="utf-8")
    return ["--config", str(settings), "--data-dir", str(data)]


def test_the_command_embeds_with_the_settings_model(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """``index`` names the model and what it embedded; the next run embeds nothing."""
    assert main(["index", *config(data, "tiny")]) == 0
    out = capsys.readouterr().out
    assert "pieces by meaning, with tiny;" in out
    assert main(["index", *config(data, "tiny")]) == 0
    assert "; 0 embedded now, the others kept" in capsys.readouterr().out


def test_a_model_whose_files_changed_leaves_the_index_in_place(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """A broken model fails the build: the index keeps its vectors, and the exit says so."""
    assert main(["index", *config(data, "tiny")]) == 0
    with reading(data / "index.sqlite") as reader:
        before = reader.summary()
    graph = data / "models" / "tiny" / "model.onnx"
    content = bytearray(graph.read_bytes())
    content[-1] ^= 1
    graph.write_bytes(bytes(content))
    write(data / "docs", page("196846", "Added since"), BODY)
    assert main(["index", *config(data, "tiny")]) == FAILED
    assert "index not built: tiny: files not as pinned" in capsys.readouterr().err
    with reading(data / "index.sqlite") as reader:
        assert reader.summary() == before
