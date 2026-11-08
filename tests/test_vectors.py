"""Vectors in the index: each piece embedded once per model, kept across builds (011, 018)."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from structlog.testing import capture_logs

from kb_mcp.cli.main import main
from kb_mcp.kernel.chunking import CHUNKINGS
from kb_mcp.mcp.app import responses
from kb_mcp.mcp.app.tools import Library
from kb_mcp.search.adapters import sqlite_index, vector_store
from kb_mcp.search.adapters.model_api import ModelError
from kb_mcp.search.adapters.sqlite_index import SqliteIndex, reading
from kb_mcp.search.app import indexing as indexing_module
from kb_mcp.search.app.indexing import (
    CHANGED_MEANWHILE,
    Embedding,
    Indexing,
    build_index,
    refresh,
    update_index,
)
from kb_mcp.search.app.meaning import Meaning
from kb_mcp.search.domain.indexes import Piece, Put, UnavailableIndexError
from kb_mcp.search.domain.search import Embedded, Filters, sections
from tests.answers import parts
from tests.endpoint import (
    DIMENSIONS,
    Scripted,
    connector,
    nothing_listening,
    scripted,
    serving,
    tiny,
)
from tests.mirrors import MOMENT, fillers, location, page, write
from tests.test_cli import logged_as
from tests.test_observed import said

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from numpy.typing import NDArray

    from kb_mcp.kernel.chunking import Chunking
    from kb_mcp.search.adapters.embedding import ApiEmbedder
    from kb_mcp.search.app.indexing import Filled
    from kb_mcp.search.app.pruning import Pruned
    from kb_mcp.search.domain.search import Pieces

BODY = "# Rollback\n\nUndo the payout.\n\n## Release\n\nThe deploy of the seller service.\n"
FILLER_PAGES = 5
FAILED = 1
REFUSED = 2
# The windows of the body of 2,562 characters below: starting at 0, 960 and 1,920.
WINDOWS = 3
RELEASE = 2  # the number of its section "Release", after 30 characters of the first


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
        assert reader.embedded() == Embedded(
            model="tiny", fingerprint=tiny().fingerprint, dimensions=DIMENSIONS
        )
        pieces = reader.vectors()
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
        kept = reader.vectors().matrix
    (data / "v.db").unlink()
    build(data, counting())
    with reading(data / "index.sqlite") as reader:
        assert np.array_equal(reader.vectors().matrix, kept)


def test_pieces_are_read_by_path_section_and_start_whatever_their_rowids(data: Path) -> None:
    """An updated index and a whole build number rows otherwise, and give one matrix."""
    embedded = Embedded(model="tiny", fingerprint="f", dimensions=1)
    first, second = page("1", "First"), page("2", "Second")
    cut = tuple(sections("# Top\n\nOne two.\n\n## Next\n\nThree.\n"))
    with sqlite_index.building(data / "index.sqlite", MOMENT, embedded) as writer:
        rows = {
            front: writer.add(Put(path=location(front), digest="d", front=front, sections=cut))
            for front in (second, first)
        }
        # Each piece's vector says when it was written.
        written = [(second, 0, 0), (first, 1, 6), (first, 0, 4), (second, 1, 0), (first, 1, 0)]
        writer.add_pieces(
            (
                rows[front] + number,
                start,
                start + 1,
                f"k{at}",
                vector_store.as_bytes(np.array([at], dtype=np.float32)),
            )
            for at, (front, number, start) in enumerate(written)
        )
    with reading(data / "index.sqlite") as reader:
        pieces = reader.vectors()
    assert [pieces.paths[each] for each in pieces.documents] == [
        *[location(first)] * 3,
        *[location(second)] * 2,
    ]
    assert pieces.sections == (1, 2, 2, 1, 2)
    assert pieces.matrix.reshape(-1).tolist() == [2, 4, 1, 0, 3]


def test_a_handle_reads_an_index_s_vectors_once_a_build(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Searches at once wait for one read; only the next build's search reads them again."""
    build(data, counting())
    reads: list[str] = []
    read = sqlite_index.Reader.vectors

    def slowly(reader: sqlite_index.Reader) -> Pieces:
        reads.append(reader.build())
        time.sleep(0.2)
        return read(reader)

    monkeypatch.setattr(sqlite_index.Reader, "vectors", slowly)
    index = SqliteIndex(data / "index.sqlite")
    query = tiny().query("deploy")

    def search() -> None:
        with index.reading() as reader:
            assert reader.nearest(query, Filters(), 3)

    threads = [threading.Thread(target=search) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    search()
    assert len(reads) == 1
    build(data, counting())
    search()
    search()
    (first, second) = reads
    assert first != second


def test_a_reader_without_a_handle_searches_alike(data: Path) -> None:
    """Opened by the path alone, as a prune opens one: the same documents, the same places."""
    build(data, counting())
    query = tiny().query("deploy")
    with reading(data / "index.sqlite") as reader:
        alone = reader.nearest(query, Filters(), 3)
    with SqliteIndex(data / "index.sqlite").reading() as reader:
        assert reader.nearest(query, Filters(), 3) == alone
    assert alone


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
        f'model = {json.dumps(model)}\nembedding_url = {json.dumps(url)}\nsearch_mode = "hybrid"\n',
        encoding="utf-8",
    )
    return ["--config", str(settings), "--data-dir", str(data)]


def chained(data: Path, capsys: CaptureFixture[str], url: str, *options: str) -> int:
    """Run ``index``, then ``embed``, with the tiny model at ``url``; give embed's exit status.

    What ``index`` wrote is left out of what the test then reads.
    """
    settings = config(data, "tiny", url)
    main(["index", "--yes", *settings])
    capsys.readouterr()
    return main(["embed", "--yes", *settings, *options])


def test_index_after_embed_asks_nothing_and_keeps_the_vectors(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Plan 035, in the hybrid mode: nothing changed, ``index`` writes nothing, said so.

    It asks the endpoint nothing and leaves ``vectors.sqlite`` byte for byte; the index
    keeps its pieces, so that search by meaning goes on; a page edited, its document
    alone awaits vectors, which the summary counts, and the rest keep theirs.
    """
    scripted = Scripted()
    with serving(scripted) as url:
        options = ["--yes", *config(data, "tiny", url)]
        assert chained(data, capsys, url) == 0
        store, index = data / "vectors.sqlite", data / "index.sqlite"
        kept, built = store.read_bytes(), index.read_bytes()
        asked = len(scripted.asked)
        with reading(index) as reader:
            pieces = reader.summary().pieces
        capsys.readouterr()
        assert main(["index", *options]) == 0
        assert len(scripted.asked) == asked
        assert (store.read_bytes(), index.read_bytes()) == (kept, built)
        out, err = capsys.readouterr()
        assert "then: documents added or changed have no vectors until kb-mcp embed" in err
        assert "nothing written\nskipped: 0\nawaiting vectors: 0\n" in out
        library = Library(SqliteIndex(index), data / "docs", Meaning(connector()), "hybrid")
        assert "search by meaning: tiny, " in parts(library.status())[1]
        write(data / "docs", page("196845", "Rollback"), BODY + "\nEdited.\n")
        assert main(["index", *options]) == 0
        assert len(scripted.asked) == asked
        assert "replaced: 1\nremoved: 0\nskipped: 0\nawaiting vectors: 1\n" in (
            capsys.readouterr().out
        )
        with reading(index) as reader:
            assert 0 < reader.summary().pieces < pieces


def test_the_command_embeds_with_the_settings_model(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """``embed`` names the model and what it embedded; the next run writes nothing."""
    detailed = ["--summary", "detailed"]
    model = "with tiny (no prefixes known: texts as they are)"
    with serving(Scripted()) as url:
        assert chained(data, capsys, url, *detailed) == 0
        out = capsys.readouterr().out
        assert f"pieces by meaning in {(data / 'index.sqlite').resolve()}, {model}:" in out
        assert " texts embedded now, 0 found in the vector store; 0 documents with a" in out
        assert main(["embed", "--yes", *config(data, "tiny", url), *detailed]) == 0
    assert f"nothing changed: {(data / 'index.sqlite').resolve()} holds " in (
        capsys.readouterr().out
    )


def test_the_command_in_short_counts_the_pieces_and_those_embedded_now(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Every piece added and embedded the first time; nothing written the next."""
    with serving(Scripted()) as url:
        assert chained(data, capsys, url) == 0
        pieces, added, removed, embedded = capsys.readouterr().out.splitlines()[:4]
        count = pieces.removeprefix("pieces: ")
        assert int(count) > 0
        assert (added, removed, embedded) == (
            f"added: {count}",
            "removed: 0",
            f"embedded now: {count}",
        )
        assert main(["embed", "--yes", *config(data, "tiny", url)]) == 0
    assert capsys.readouterr().out.splitlines()[:3] == [
        pieces,
        "nothing written",
        "embedded now: 0",
    ]


def test_the_command_reports_its_files_then_its_texts_to_embed(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """In the log file, each task's last event progress: index's files, embed's texts.

    Nothing changed, the next ``index`` reads no file, and ``embed`` embeds nothing; one
    page edited, ``index`` reads it alone, and ``embed`` embeds what changed of it.
    """
    with serving(Scripted()) as url:
        assert chained(data, capsys, url) == 0
        pieces = int(capsys.readouterr().out.splitlines()[0].removeprefix("pieces: "))
        assert chained(data, capsys, url) == 0
        write(data / "docs", page("196845", "Rollback"), BODY.replace("payout", "refund"))
        assert chained(data, capsys, url) == 0
    files = FILLER_PAGES + 1
    progress = sorted(
        (line["task"], line["done"], line["total"])
        for line in logged_as(data.parent / "home", "progress")
    )
    assert progress == sorted(
        [
            ("files", files, files),
            ("texts to embed", pieces, pieces),
            ("files", 1, 1),
            ("texts to embed", 1, 1),
        ]
    )


def test_an_endpoint_that_stops_answering_leaves_the_index_in_place(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Ollama not started: the fill fails, the index stays as it was, and the exit says why.

    By the error index.not_built, with its reason, which the run's log file holds too;
    the index holds the document added since, awaiting vectors, and its others' pieces.
    """
    with serving(Scripted()) as url:
        assert chained(data, capsys, url) == 0
    write(data / "docs", page("196846", "Added since"), BODY)
    with nothing_listening() as url:
        assert chained(data, capsys, url) == FAILED
    err = capsys.readouterr().err
    assert ("error", "index.not_built") in said(err)
    assert "no answer from the embedding endpoint" in err
    assert "ollama serve" in err
    (failed,) = logged_as(data.parent / "home", "index.not_built")
    assert failed["level"] == "error"
    assert "hint" not in failed
    assert str(failed["reason"]).startswith("no answer from the embedding endpoint")
    with reading(data / "index.sqlite") as reader:
        summary = reader.summary()
    assert (summary.awaiting, summary.pieces > 0) == (1, True)


def test_a_piece_the_model_refuses_is_named_and_asked_again(
    data: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """The others are embedded, the index replaced, the exit 1; the next run asks again.

    Refused again, that next run writes nothing.

    The piece's document is named by the warning index.piece_refused, in the log file too.
    Cut by sections, a piece a section, so that the piece refused is one section's.
    """
    monkeypatch.setenv("KB_MCP_CHUNKING", "sections")
    refused = "Rollback\nRelease\nThe deploy of the seller service."
    answers = Scripted(refused={refused})
    with serving(answers) as url:
        assert chained(data, capsys, url) == FAILED
        err = capsys.readouterr().err
        assert ("warning", "index.piece_refused") in said(err)
        assert "confluence/ENG/196845-rollback.md" in err
        (piece,) = logged_as(data.parent / "home", "index.piece_refused")
        assert (piece["level"], piece["path"]) == ("warning", "confluence/ENG/196845-rollback.md")
        with reading(data / "index.sqlite") as reader:
            assert len(reader.vectors().documents) == reader.summary().sections - 1
        asked = sum(refused in each for each in answers.asked)
        before = snapshot(data / "index.sqlite")
        assert main(["embed", "--yes", *config(data, "tiny", url)]) == FAILED
        assert sum(refused in each for each in answers.asked) > asked
        assert snapshot(data / "index.sqlite") == before


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


def chunked(data: Path, embedder: Counting, chunking: Chunking) -> None:
    """Build the data directory's index with an embedder, cutting by ``chunking``."""
    embedding = Embedding(embedder, data / "v.db", chunking=chunking)
    build_index(data / "docs", data / "index.sqlite", MOMENT, embedding)


def test_the_index_and_its_status_name_its_chunking(data: Path) -> None:
    """The meta row says how the pieces were cut, sections unless told; so does status."""
    build(data, counting())
    with reading(data / "index.sqlite") as reader:
        assert reader.embedded() == Embedded(
            model="tiny", fingerprint=tiny().fingerprint, dimensions=DIMENSIONS, chunking="sections"
        )
    chunked(data, counting(), "windows")
    with reading(data / "index.sqlite") as reader:
        assert reader.embedded() == Embedded(
            model="tiny", fingerprint=tiny().fingerprint, dimensions=DIMENSIONS, chunking="windows"
        )
        said = responses.status(reader.summary(), data / "docs")
    assert re.search(r"search by meaning: tiny, \d+ pieces cut by windows\n", said)


def test_an_index_built_before_the_row_reads_as_cut_by_sections(data: Path) -> None:
    """Indexes of 011 and 018 name no chunking: theirs is sections."""
    build(data, counting())
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        connection.execute("DELETE FROM meta WHERE name = 'chunking'")
        connection.commit()
    with reading(data / "index.sqlite") as reader:
        assert reader.embedded() == Embedded(
            model="tiny", fingerprint=tiny().fingerprint, dimensions=DIMENSIONS, chunking="sections"
        )
        assert reader.summary().chunking == "sections"


@pytest.mark.parametrize("chunking", CHUNKINGS)
def test_an_index_names_the_store_s_key_of_each_piece_s_vector(
    data: Path, chunking: Chunking
) -> None:
    """Its keys are the store's keys of the texts that its chunking embeds, and no other."""
    embedder = counting()
    chunked(data, embedder, chunking)
    with reading(data / "index.sqlite") as reader:
        keys = reader.keys()
    assert keys == {vector_store.key(tiny().fingerprint, text) for text in embedder.texts}


def test_an_index_built_before_keys_reads_as_before_but_cannot_say_them(data: Path) -> None:
    """Without the column, its pieces and summary read as ever; its keys are refused."""
    build(data, counting())
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        connection.execute("ALTER TABLE pieces DROP COLUMN key")
        connection.commit()
    with reading(data / "index.sqlite") as reader:
        assert len(reader.vectors().documents) == reader.summary().pieces > 0
        with pytest.raises(UnavailableIndexError, match="before pieces recorded their keys"):
            reader.keys()


def test_a_window_belongs_to_the_section_of_its_middle_and_spans_the_body(data: Path) -> None:
    """A window across sections: its section holds its middle, its span reads the body."""
    body = "# Rollback\n\nUndo the payout.\n\n## Release\n\n" + "The deploy goes out. " * 120
    write(data / "docs", page("196845", "Rollback"), body)
    embedder = counting()
    chunked(data, embedder, "windows")
    path = "confluence/ENG/196845-rollback.md"
    with reading(data / "index.sqlite") as reader:
        pieces = reader.vectors()
        bounds = reader.bounds(path)
        mine = [index for index, each in enumerate(pieces.documents) if pieces.paths[each] == path]
        assert len(mine) == WINDOWS
        for index in mine:
            start, end = pieces.offsets[index], pieces.ends[index]
            first, last = bounds[pieces.sections[index] - 1]
            assert first <= (start + end) // 2 < last
            assert reader.text(path, start, end) == body[start:end]
            assert f"Rollback\n{body[start:end].strip()}" in embedder.texts
    assert pieces.offsets[mine[0]] == 0
    assert pieces.sections[mine[0]] == RELEASE


def test_a_text_that_chunkings_share_is_embedded_once(data: Path) -> None:
    """Without a breadcrumb or nested headings, section-paths embeds what sections did."""
    build(data, counting())
    paths = counting()
    chunked(data, paths, "section-paths")
    assert paths.texts == []


def test_a_sections_rebuild_after_a_windows_one_embeds_nothing(data: Path) -> None:
    """The store keeps the vectors of every chunking built: none is embedded again."""
    build(data, counting())
    windows = counting()
    chunked(data, windows, "windows")
    assert windows.texts
    again = counting()
    report = build_index(
        data / "docs", data / "index.sqlite", MOMENT, Embedding(again, data / "v.db")
    )
    assert again.texts == []
    assert report.embedded == 0


def test_a_chunking_that_the_kernel_does_not_name_is_refused(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """``chunking = "window"`` exits 2 naming the setting and its layer; nothing is built."""
    settings = data.parent / "config.toml"
    settings.write_text('chunking = "window"\n', encoding="utf-8")
    options = ["--yes", "--config", str(settings), "--data-dir", str(data)]
    assert main(["embed", *options]) == REFUSED
    err = capsys.readouterr().err
    assert "chunking (config.toml):" in err
    assert all(f"'{name}'" in err for name in CHUNKINGS)
    assert not (data / "index.sqlite").exists()


def test_the_environment_s_chunking_replaces_the_file_s(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """``KB_MCP_CHUNKING`` is stronger than the file, and the index says so."""
    monkeypatch.setenv("KB_MCP_CHUNKING", "small-to-big")
    with serving(Scripted()) as url:
        options = config(data, "tiny", url)
        settings = Path(options[1])
        settings.write_text(f'{settings.read_text("utf-8")}chunking = "section-paths"\n', "utf-8")
        assert main(["index", "--yes", *options]) == 0
        assert main(["embed", "--yes", *options]) == 0
    with reading(data / "index.sqlite") as reader:
        embedded = reader.embedded()
    assert embedded is not None
    assert embedded.chunking == "small-to-big"


def test_an_index_cut_by_a_chunking_this_version_lacks_is_refused(data: Path) -> None:
    """Its pieces could be quoted by no unit known here: rebuilt, it is read again.

    The files are not in question, so the commands named are ``index``, then ``embed``.
    """
    build(data, counting())
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        connection.execute("UPDATE meta SET value = 'paragraphs' WHERE name = 'chunking'")
        connection.commit()
    refused = pytest.raises(
        UnavailableIndexError,
        match=r"this version reads: rebuild it with `kb-mcp index`, then `kb-mcp embed`$",
    )
    with refused, reading(data / "index.sqlite"):
        pass


def indexing(
    data: Path, answers: Scripted | None = None, chunking: Chunking = "sections"
) -> Indexing:
    """Say how ``index`` and ``embed`` write the data directory's index, as scripted."""
    return Indexing(
        docs=data / "docs",
        index=data / "index.sqlite",
        vectors=data / "v.db",
        evaluation_indexes=data / "eval" / "indexes",
        aliases=data / "aliases.toml",
        model="tiny",
        chunking=chunking,
        endpoint=lambda: scripted(answers),
    )


def filled_by(
    data: Path, answers: Scripted | None = None, chunking: Chunking = "sections"
) -> Filled:
    """Update the index, as ``index`` does, then fill it, as ``embed`` does; give the fill."""
    assert update_index(indexing(data), MOMENT) is not None
    filled = refresh(indexing(data, answers, chunking))
    assert filled is not None
    return filled


def texts_asked(answers: Scripted) -> list[str]:
    """Give the texts that the model was asked to embed, its probe for dimensions aside."""
    return [text for asked in answers.asked if asked != ["probe"] for text in asked]


def snapshot(index: Path) -> tuple[bytes, int, str]:
    """Give an index's bytes, its time and its build: what a run that writes nothing keeps."""
    with reading(index) as reader:
        return index.read_bytes(), index.stat().st_mtime_ns, reader.build()


def pieces_of(index: Path) -> list[Piece]:
    """Give the pieces that an index holds, by path, section number and start."""
    with reading(index) as reader:
        return reader.pieces()


def whole_pieces(data: Path, chunking: Chunking = "sections") -> list[Piece]:
    """Give the pieces of a whole build of the mirror as it is, by the tiny model."""
    whole = data.parent / "whole.sqlite"
    whole.unlink(missing_ok=True)
    build_index(data / "docs", whole, MOMENT, Embedding(tiny(), data.parent / "whole.db", chunking))
    return pieces_of(whole)


ROLLBACK_PATH = "confluence/ENG/196845-rollback.md"
TWICE = 2  # a fill's attempts, when another run wrote the index meanwhile


def test_nothing_changed_index_then_embed_write_nothing(data: Path) -> None:
    """Plan 035, criterion 3: the index's bytes, time and build as they were; nothing embedded."""
    filled_by(data)
    before = snapshot(data / "index.sqlite")
    answers = Scripted()
    filled = filled_by(data, answers)
    assert (filled.unchanged, filled.added, filled.removed, filled.embedded) == (True, 0, 0, 0)
    assert texts_asked(answers) == []
    assert snapshot(data / "index.sqlite") == before


def test_one_page_edited_embed_adds_its_pieces_alone(data: Path) -> None:
    """Criterion 3: its pieces alone are added, the model embedding only what the store lacks.

    Cut by sections: of its two sections, the one unchanged is found in the store.
    """
    filled_by(data)
    others = [piece for piece in pieces_of(data / "index.sqlite") if piece.path != ROLLBACK_PATH]
    write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "buyer"))
    answers = Scripted()
    filled = filled_by(data, answers)
    assert (filled.added, filled.removed, filled.embedded, filled.found) == (2, 0, 1, 1)
    (text,) = texts_asked(answers)
    assert "buyer" in text
    held = pieces_of(data / "index.sqlite")
    assert [piece for piece in held if piece.path != ROLLBACK_PATH] == others
    assert held == whole_pieces(data)


def test_a_removed_page_s_vectors_are_pruned_by_the_next_embed(data: Path) -> None:
    """Criterion 4: after ``index``, then ``embed``, the vectors that it alone read are gone."""
    filled_by(data)
    keys = {piece.key for piece in pieces_of(data / "index.sqlite") if piece.path == ROLLBACK_PATH}
    (data / "docs" / ROLLBACK_PATH).unlink()
    filled = filled_by(data)
    assert filled.pruned is not None
    assert (filled.pruned.outcome, filled.pruned.deleted) == ("pruned", len(keys))
    with closing(sqlite3.connect(data / "v.db")) as connection:
        stored = {row[0] for row in connection.execute("SELECT key FROM vectors")}
    assert stored.isdisjoint(keys)
    assert stored == {piece.key for piece in pieces_of(data / "index.sqlite")}


def stored_keys(store: Path) -> set[str]:
    """Give the keys of the vectors that a store holds."""
    with closing(sqlite3.connect(store)) as connection:
        return {row[0] for row in connection.execute("SELECT key FROM vectors")}


@pytest.mark.parametrize("chunking", ["windows", "section-paths"])
def test_a_change_of_chunking_embeds_only_what_the_store_lacks(
    data: Path, chunking: Chunking
) -> None:
    """Criterion 7: the pieces and model are a whole build's; no text of the store is embedded.

    Then back to the first chunking, likewise, the prune having left what it read.
    """
    filled_by(data)
    for cut in (chunking, "sections"):
        before = stored_keys(data / "v.db")
        answers = Scripted()
        filled = filled_by(data, answers, cut)
        asked = {vector_store.key(tiny().fingerprint, text) for text in texts_asked(answers)}
        assert asked.isdisjoint(before)
        assert filled.embedded == len(asked)
        assert pieces_of(data / "index.sqlite") == whole_pieces(data, cut)
        with reading(data / "index.sqlite") as reader:
            embedded = reader.embedded()
        assert embedded is not None
        assert embedded.chunking == cut


def embedded_at(data: Path, url: str, capsys: CaptureFixture[str]) -> tuple[int, str]:
    """Run ``embed`` with the tiny model at ``url``; give its exit status and its stderr."""
    capsys.readouterr()
    status = main(["embed", "--yes", *config(data, "tiny", url)])
    return status, capsys.readouterr().err


def test_embed_without_an_index_stops_naming_index(data: Path, capsys: CaptureFixture[str]) -> None:
    """Criterion 11: exit 1, ``index.not_built`` naming ``kb-mcp index``; no endpoint opened.

    With an index at another schema, ``reading``'s message, naming ``prepare``.
    """
    with nothing_listening() as url:
        status, err = embedded_at(data, url, capsys)
        assert (status, ("error", "index.not_built") in said(err)) == (FAILED, True)
        assert "build it with `kb-mcp index`" in err
        assert "no answer" not in err
        assert mirror_changed(err) == []
        assert main(["index", "--yes", *config(data, "tiny", url)]) == 0
        with closing(sqlite3.connect(data / "index.sqlite")) as connection:
            connection.execute("UPDATE meta SET value = '5' WHERE name = 'schema'")
            connection.commit()
        status, err = embedded_at(data, url, capsys)
    assert status == FAILED
    assert "rebuild it with `kb-mcp prepare`" in err
    assert "no answer" not in err


def unrecorded(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Make the index one of schema 6 before plan 035: no digest, no skipped, no words."""
    with closing(sqlite3.connect(data / "index.sqlite")) as connection:
        connection.execute("DELETE FROM meta WHERE name IN ('words', 'aliases')")
        connection.execute("ALTER TABLE documents DROP COLUMN digest")
        connection.execute("DROP TABLE skipped")
        connection.commit()
    del monkeypatch  # the code's cut stays


def recut(_: Path, monkeypatch: MonkeyPatch) -> None:
    """Change the code's cut, as a change of ``search.sections`` would, by its constant."""
    monkeypatch.setattr(indexing_module, "WORDS", "another")
    monkeypatch.setattr(sqlite_index, "WORDS", "another")


@pytest.mark.parametrize("made", [unrecorded, recut])
def test_embed_on_an_index_of_another_cut_stops_until_index_runs(
    data: Path,
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
    made: Callable[[Path, MonkeyPatch], None],
) -> None:
    """Criterion 7: "run kb-mcp index first", exit 1, the bytes kept, no endpoint opened.

    Once ``index`` has run, ``embed`` fills.
    """
    with nothing_listening() as url:
        assert main(["index", "--yes", *config(data, "tiny", url)]) == 0
    made(data, monkeypatch)
    write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "buyer"))
    before = (data / "index.sqlite").read_bytes()
    with nothing_listening() as url:
        status, err = embedded_at(data, url, capsys)
    assert (status, ("error", "index.not_built") in said(err)) == (FAILED, True)
    assert "run kb-mcp index first" in err
    assert "no answer" not in err
    assert mirror_changed(err) == []
    assert (data / "index.sqlite").read_bytes() == before
    with serving(Scripted()) as url:
        assert main(["index", "--yes", *config(data, "tiny", url)]) == 0
        status, _ = embedded_at(data, url, capsys)
    assert status == 0
    assert pieces_of(data / "index.sqlite")


def damage(index: Path, table: str) -> None:
    """Overwrite the root page of a table of the index, which ``reading`` alone passes."""
    with closing(sqlite3.connect(index)) as connection:
        root = connection.execute("SELECT rootpage FROM sqlite_master WHERE name = ?", (table,))
        page_number = root.fetchone()[0]
        size = connection.execute("PRAGMA page_size").fetchone()[0]
    with index.open("r+b") as file:
        file.seek((page_number - 1) * size)
        file.write(b"\xff" * size)


@pytest.mark.parametrize("table", ["documents", "sections"])
def test_embed_on_a_damaged_index_stops_naming_a_rebuild(
    data: Path, capsys: CaptureFixture[str], table: str
) -> None:
    """Criterion 7: ``index.not_built`` naming ``kb-mcp index --rebuild``; no endpoint opened."""
    with nothing_listening() as url:
        assert main(["index", "--yes", *config(data, "tiny", url)]) == 0
        damage(data / "index.sqlite", table)
        write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "buyer"))
        status, err = embedded_at(data, url, capsys)
    assert (status, ("error", "index.not_built") in said(err)) == (FAILED, True)
    assert "kb-mcp index --rebuild" in err
    assert "no answer" not in err
    assert mirror_changed(err) == []


@pytest.mark.parametrize("rebuild", [False, True])
def test_an_index_written_between_embed_s_read_and_write_starts_it_again(
    data: Path, monkeypatch: MonkeyPatch, *, rebuild: bool
) -> None:
    """Criterion 8: an update, or a whole rebuild, in between: no piece on an old rowid.

    The fill starts again once, reads the new build, and its pieces are a whole build's.
    """
    filled_by(data)
    write(data / "docs", page("196846", "Added"), BODY.replace("payout", "refund"))
    assert update_index(indexing(data), MOMENT) is not None
    fill = SqliteIndex.fill
    builds: list[str] = []

    def meanwhile(self: SqliteIndex, expected: str, *rest: object) -> str | None:
        builds.append(expected)
        if len(builds) == 1:
            write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "buyer"))
            assert update_index(indexing(data), MOMENT, rebuild=rebuild) is not None
        return fill(self, expected, *rest)

    monkeypatch.setattr(SqliteIndex, "fill", meanwhile)
    filled = refresh(indexing(data))
    assert filled is not None
    assert len(builds) == len(set(builds)) == TWICE
    assert pieces_of(data / "index.sqlite") == whole_pieces(data)


def test_an_index_written_at_each_attempt_stops_embed(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Criterion 8: twice, ``embed`` stops, ``index.not_built`` naming the other run."""
    assert update_index(indexing(data), MOMENT) is not None
    fill = SqliteIndex.fill

    def meanwhile(self: SqliteIndex, *arguments: object) -> str | None:
        assert update_index(indexing(data), MOMENT, rebuild=True) is not None
        return fill(self, *arguments)

    monkeypatch.setattr(SqliteIndex, "fill", meanwhile)
    with capture_logs() as logs:
        assert refresh(indexing(data)) is None
    (failed,) = [each for each in logs if each["event"] == "index.not_built"]
    assert failed["reason"] == CHANGED_MEANWHILE


def test_index_and_embed_started_together_take_turns(data: Path) -> None:
    """Criterion 8: both end well, whichever takes the lock first; then nothing is left to do."""
    filled_by(data)
    write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "buyer"))
    results: list[object] = []
    indexing_thread = threading.Thread(
        target=lambda: results.append(update_index(indexing(data), MOMENT))
    )
    indexing_thread.start()
    filled = refresh(indexing(data))
    indexing_thread.join()
    assert filled is not None
    assert results[0] is not None
    filled_by(data)
    assert pieces_of(data / "index.sqlite") == whole_pieces(data)


def test_a_lock_held_too_long_stops_embed_naming_it(data: Path, monkeypatch: MonkeyPatch) -> None:
    """Criterion 8: a wait past WAIT_S, shortened here: ``index.not_built`` naming the lock."""
    monkeypatch.setattr(vector_store, "WAIT_S", 0.3)
    assert update_index(indexing(data), MOMENT) is not None
    before = (data / "index.sqlite").read_bytes()
    lock = data / "index.sqlite.lock"
    with lock.open("a") as file, capture_logs() as logs:
        fcntl.flock(file, fcntl.LOCK_EX)
        assert refresh(indexing(data)) is None
    (failed,) = [each for each in logs if each["event"] == "index.not_built"]
    assert str(lock) in failed["reason"]
    assert (data / "index.sqlite").read_bytes() == before


def test_a_fill_that_fails_before_its_rename_leaves_the_index_as_it_was(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Criterion 9: its bytes as they were, no build file left, and the lock free."""
    assert update_index(indexing(data), MOMENT) is not None
    before = (data / "index.sqlite").read_bytes()

    def fail(*_: object) -> dict[str, object]:
        raise RuntimeError

    with monkeypatch.context() as patch:
        patch.setattr(Piece, "model_dump", fail)
        with pytest.raises(RuntimeError):
            refresh(indexing(data))
    assert (data / "index.sqlite").read_bytes() == before
    assert not list(data.glob(f"{sqlite_index.BUILDING}*"))
    assert refresh(indexing(data)) is not None


def test_a_fill_killed_leaves_the_index_as_it_was(data: Path, capsys: CaptureFixture[str]) -> None:
    """Criterion 9: killed by SIGKILL as it writes, its build file ignored; no write-ahead log."""
    with serving(Scripted()) as url:
        options = config(data, "tiny", url)
        assert main(["index", "--yes", *options]) == 0
        before = (data / "index.sqlite").read_bytes()
        environment = {
            "HOME": os.environ["HOME"],
            "PATH": os.environ["PATH"],
            "KB_MCP_DATA_DIR": str(data),
            "KB_MCP_MODEL": "tiny",
            "KB_MCP_EMBEDDING_URL": url,
        }
        with subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys, time\n"
                    "from kb_mcp.cli.main import main\n"
                    "from kb_mcp.search.domain.indexes import Piece\n"
                    "def model_dump(self):\n"
                    "    print('filling', flush=True)\n"
                    "    time.sleep(60)\n"
                    "Piece.model_dump = model_dump\n"
                    "sys.exit(main(['embed', '--yes']))\n"
                ),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            text=True,
            env=environment,
            cwd=data.parent,
        ) as child:
            assert child.stdout is not None
            assert child.stdout.readline() == "filling\n"
            child.kill()
            child.wait(30)
        assert (data / "index.sqlite").read_bytes() == before
        assert list(data.glob(f"{sqlite_index.BUILDING}*.sqlite"))
        assert data / "index.sqlite" in sqlite_index.indexes_in(data)
        assert not any(path.name.startswith(".") for path in sqlite_index.indexes_in(data))
        assert not (data / "index.sqlite-wal").exists()
        capsys.readouterr()
        assert main(["embed", "--yes", *options]) == 0
    assert pieces_of(data / "index.sqlite")


def test_the_prune_keeps_what_embed_wrote_when_an_index_ran_since(
    data: Path, monkeypatch: MonkeyPatch
) -> None:
    """Criterion 10: an ``index`` renamed in between ``embed``'s write and its prune.

    The page that ``embed`` filled is edited again and replaced by that ``index``: its
    vectors, which no index in place reads, stay, as ``embed`` wrote them.
    """
    filled_by(data)
    write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "buyer"))
    assert update_index(indexing(data), MOMENT) is not None
    prune = indexing_module.prune

    def meanwhile(*arguments: object, **options: object) -> Pruned:
        write(data / "docs", page("196845", "Rollback"), BODY.replace("seller", "agent"))
        assert update_index(indexing(data), MOMENT) is not None
        return prune(*arguments, **options)

    monkeypatch.setattr(indexing_module, "prune", meanwhile)
    filled = refresh(indexing(data))
    assert filled is not None
    assert filled.pruned is not None
    assert filled.pruned.outcome == "pruned"
    with closing(sqlite3.connect(data / "v.db")) as connection:
        stored = {row[0] for row in connection.execute("SELECT key FROM vectors")}
    assert filled.kept <= stored
    assert (
        vector_store.key(tiny().fingerprint, "Rollback\nRelease\nThe deploy of the buyer service.")
        in stored
    )


def mirror_changed(err: str) -> list[dict[str, object]]:
    """Give each ``embed.mirror_changed`` that stderr shows, with its fields."""
    return [
        dict(re.findall(r"(\w+)=('[^']*'|\S+)", line))
        for line in err.splitlines()
        if "embed.mirror_changed" in line
    ]


def test_a_mirror_changed_since_the_index_is_a_warning_and_nothing_else(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Criterion 16: a file edited, removed, then added, each before its own ``embed``.

    Each warns at the default level, counting it and naming ``kb-mcp index``; each exits
    as on a mirror unchanged, writes nothing, and the index still finds what it held.
    """
    with serving(Scripted()) as url:
        assert main(["index", "--yes", *config(data, "tiny", url)]) == 0
        assert embedded_at(data, url, capsys)[0] == 0
        before = snapshot(data / "index.sqlite")
        steps = [
            (
                lambda: write(data / "docs", page("196845", "Rollback"), "# Rollback\n\nNew.\n"),
                ("1", "0", "0"),
            ),
            ((data / "docs" / location(page("900000", "Lorem 0"))).unlink, ("1", "0", "1")),
            (lambda: write(data / "docs", page("196847", "Later")), ("1", "1", "1")),
        ]
        for change, counted in steps:  # each counted with those before, no index between
            change()
            status, err = embedded_at(data, url, capsys)
            assert status == 0
            (warned,) = mirror_changed(err)
            assert (warned["changed"], warned["added"], warned["removed"]) == counted
            assert "run kb-mcp index" in warned["hint"]
            assert snapshot(data / "index.sqlite") == before
    with reading(data / "index.sqlite") as reader:
        assert list(reader.scores('"payout"', Filters())[0]) == [ROLLBACK_PATH]
        assert reader.entries(paths=[location(page("900000", "Lorem 0"))])


def test_the_warning_comes_before_the_model_is_reached(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Criterion 16: an endpoint that does not answer fails the run after the warning."""
    with serving(Scripted()) as url:
        assert chained(data, capsys, url) == 0
    write(data / "docs", page("196845", "Rollback"), "# Rollback\n\nNew.\n")
    with nothing_listening() as url:
        status, err = embedded_at(data, url, capsys)
    assert status == FAILED
    (warned,) = mirror_changed(err)
    assert (warned["changed"], warned["added"], warned["removed"]) == ("1", "0", "0")
    lines = err.splitlines()
    warning = next(at for at, line in enumerate(lines) if "embed.mirror_changed" in line)
    assert warning < next(at for at, line in enumerate(lines) if "index.not_built" in line)
    assert "no answer from the embedding endpoint" in err


def test_no_warning_for_a_mirror_unchanged_a_skipped_file_or_an_alias_file(
    data: Path, capsys: CaptureFixture[str]
) -> None:
    """Criterion 16: a file that the index skipped among it, or an alias file changed: none."""
    broken = data / "docs" / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    with serving(Scripted()) as url:
        main(["index", "--yes", *config(data, "tiny", url)])
        assert embedded_at(data, url, capsys)[0] == FAILED  # the index lacks a file
        (data / "aliases.toml").write_text('"Jo" = "A Person"\n', encoding="utf-8")
        status, err = embedded_at(data, url, capsys)
    assert status == FAILED
    assert mirror_changed(err) == []
