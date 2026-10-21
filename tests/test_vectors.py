"""Vectors in the index: each piece embedded once per model, kept across builds (011, 018)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pytest

from atlassian_offline_mcp.adapters import vector_store
from atlassian_offline_mcp.adapters.embedding import ModelError
from atlassian_offline_mcp.adapters.sqlite_index import reading
from atlassian_offline_mcp.app.indexing import Embedding, build_index
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.search import Embedded
from tests.endpoint import DIMENSIONS, Scripted, nothing_listening, serving, tiny
from tests.mirrors import MOMENT, fillers, page, write

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from numpy.typing import NDArray

    from atlassian_offline_mcp.adapters.embedding import ApiEmbedder

BODY = "# Rollback\n\nUndo the payout.\n\n## Release\n\nThe deploy of the seller service.\n"
FILLER_PAGES = 5
FAILED = 1


@dataclass
class Counting:
    """An embedder that counts the texts it embeds, and may fail after some calls."""

    inner: ApiEmbedder
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

    def documents(self, texts: Sequence[str]) -> list[NDArray[np.float32] | None]:
        """Count, then embed; fail as a model would once ``fail_after`` calls are done."""
        if self.fail_after is not None and len(self.texts) >= self.fail_after:
            message = "tiny: the endpoint answered 500"
            raise ModelError(message)
        self.texts += texts
        return self.inner.documents(texts)

    def query(self, text: str) -> NDArray[np.float32]:
        """Embed a query."""
        return self.inner.query(text)


@pytest.fixture
def data(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a data directory whose mirror has a few pages."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    fillers(tmp_path / "data" / "docs", FILLER_PAGES)
    write(tmp_path / "data" / "docs", page("196845", "Rollback"), BODY)
    return tmp_path / "data"


def build(data: Path, embedder: Counting) -> None:
    """Build the data directory's index with an embedder and its vector store."""
    build_index(data / "docs", data / "index.sqlite", MOMENT, Embedding(embedder, data / "v.db"))


def counting() -> Counting:
    """Return a counting embedder over the tiny model."""
    return Counting(tiny())


def test_an_index_with_a_model_holds_a_unit_vector_for_every_piece(data: Path) -> None:
    """Every section has a piece here, each with the model's dimensions and unit length."""
    embedder = counting()
    build(data, embedder)
    with reading(data / "index.sqlite") as reader:
        assert reader.embedded() == Embedded("tiny", tiny().fingerprint, DIMENSIONS)
        pieces = reader.pieces()
        assert len(pieces.documents) == reader.summary().sections == len(embedder.texts)
        assert np.allclose(np.linalg.norm(pieces.matrix, axis=1), 1)
    assert "Rollback\nRelease\nThe deploy of the seller service." in embedder.texts


def test_a_rebuild_embeds_only_the_pieces_that_changed(data: Path) -> None:
    """One section edited: one text embedded; the vectors equal a fresh build's."""
    build(data, counting())
    write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "sellers"))
    again = counting()
    build(data, again)
    assert again.texts == ["Rollback\nRelease\nThe deploy of the sellers service."]
    with reading(data / "index.sqlite") as reader:
        kept = reader.pieces().matrix
    (data / "v.db").unlink()
    build(data, counting())
    with reading(data / "index.sqlite") as reader:
        assert np.array_equal(reader.pieces().matrix, kept)


def test_another_fingerprint_reuses_no_vector(data: Path) -> None:
    """The same name with another digest is other weights: every text is embedded again."""
    first = counting()
    build(data, first)
    second = Counting(tiny(Scripted({"tiny:latest": "d2" * 32})))
    build(data, second)
    assert len(second.texts) == len(first.texts)


def test_an_interrupted_build_keeps_the_batches_it_finished(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """A model failing after its first batch: the old index stays, that batch is kept."""
    monkeypatch.setattr(vector_store, "BATCH", 2)
    failing = Counting(tiny(), fail_after=2)
    with pytest.raises(ModelError):
        build(data, failing)
    assert not (data / "index.sqlite").exists()
    assert len(failing.texts) == vector_store.BATCH
    resumed = counting()
    build(data, resumed)
    (data / "v.db").unlink()
    whole = counting()
    build(data, whole)
    assert sorted(failing.texts + resumed.texts) == sorted(whole.texts)


def config(data: Path, model: str, url: str) -> list[str]:
    """Write settings naming a model and an endpoint; give the options that point at them."""
    settings = data.parent / "config.toml"
    settings.write_text(
        f"model = {json.dumps(model)}\nembedding_url = {json.dumps(url)}\n", encoding="utf-8"
    )
    return ["--config", str(settings), "--data-dir", str(data)]


def test_the_command_embeds_with_the_settings_model(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """``index`` names the model and what it embedded; the next run embeds nothing."""
    with serving(Scripted()) as url:
        assert main(["index", *config(data, "tiny", url)]) == 0
        out = capsys.readouterr().out
        assert "pieces by meaning, with tiny (no prefixes known: texts as they are);" in out
        assert main(["index", *config(data, "tiny", url)]) == 0
    assert "; 0 embedded now, the others kept" in capsys.readouterr().out


def test_an_endpoint_that_stops_answering_leaves_the_index_in_place(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Ollama not started: the build fails, the index keeps its vectors, and the exit says why."""
    with serving(Scripted()) as url:
        assert main(["index", *config(data, "tiny", url)]) == 0
    with reading(data / "index.sqlite") as reader:
        before = reader.summary()
    write(data / "docs", page("196846", "Added since"), BODY)
    capsys.readouterr()
    with nothing_listening() as url:
        assert main(["index", *config(data, "tiny", url)]) == FAILED
    err = capsys.readouterr().err
    assert "index not built: no answer from the embedding endpoint" in err
    assert "ollama serve" in err
    assert 'or set search_mode = "lexical" to index by words alone' in err
    with reading(data / "index.sqlite") as reader:
        assert reader.summary() == before


def test_a_piece_the_model_refuses_is_named_and_asked_again(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """The others are embedded, the index replaced, the exit 1; the next build asks again."""
    refused = "Rollback\nRelease\nThe deploy of the seller service."
    answers = Scripted(refused={refused})
    with serving(answers) as url:
        assert main(["index", *config(data, "tiny", url)]) == FAILED
        err = capsys.readouterr().err
        assert "not embedded: a piece of confluence/ENG/196845-rollback.md" in err
        with reading(data / "index.sqlite") as reader:
            assert len(reader.pieces().documents) == reader.summary().sections - 1
        asked = sum(refused in each for each in answers.asked)
        assert main(["index", *config(data, "tiny", url)]) == FAILED
        assert sum(refused in each for each in answers.asked) > asked


def test_two_runs_share_the_store_at_once(tmp_path: Path) -> None:
    """A read leaves no lock behind: another run writes while the first is open."""
    with (
        vector_store.opened(tmp_path / "v.db") as first,
        vector_store.opened(tmp_path / "v.db") as second,
    ):
        assert second.get(["a"]) == {}
        first.put({"a": b"1234"})
        assert second.get(["a"]) == {"a": b"1234"}
        second.put({"b": b"5678"})
        assert first.get(["a", "b"]) == {"a": b"1234", "b": b"5678"}
