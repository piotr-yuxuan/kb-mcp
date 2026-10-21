"""Running embedding models, and pulling their pinned files (plan 011).

The adapter runs on a tiny model built at test time (``tests.tiny_model``); the real
models run only in the opt-in test at the end.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import httpx
import numpy as np
import pytest

from atlassian_offline_mcp.adapters import embedding, model_pull
from atlassian_offline_mcp.adapters.embedding import (
    CATALOGUE,
    CHUNK_BYTES,
    MAX_TOKENS,
    File,
    Model,
    ModelError,
    known,
    load,
    pulled,
)
from atlassian_offline_mcp.adapters.model_pull import (
    HUB,
    MAX_REDIRECTS,
    copy_from,
    download_client,
    pull,
)
from atlassian_offline_mcp.cli import main
from tests.tiny_model import DECODER, DIMENSIONS, ENCODER, registered

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

GRAPH = b"a graph, as bytes"
TOKENIZER = b'{"a": "tokeniser"}'
REFUSED = 2
SAME = 0.9999
# Requests that a hub redirecting for ever gets: the first, then MAX_REDIRECTS.
REQUESTS = 6
# Chunks read of an endless file pinned smaller than one chunk: one, and one ahead.
READS = 2
# Seconds within which a file past its deadline of half a second is given up.
GIVEN_UP_S = 3
# Real models, pulled beforehand, for the opt-in test: a folder of model folders.
MODELS = os.environ.get("ATLASSIAN_OFFLINE_MCP_MODELS")


def pinned(path: str, content: bytes) -> File:
    """Pin a file by its content, as the catalogue does."""
    return File(path, hashlib.sha256(content).hexdigest(), len(content))


MODEL = Model(
    name="pinned",
    repository="someone/pinned",
    revision="0123456789abcdef0123456789abcdef01234567",
    graph=pinned("onnx/model.onnx", GRAPH),
    tokenizer=pinned("tokenizer.json", TOKENIZER),
    pooling="mean",
    pad="<pad>",
    query_prefix="query: ",
    document_prefix="passage: ",
    dimensions=4,
)
SERVED = {"onnx/model.onnx": GRAPH, "tokenizer.json": TOKENIZER}


class Hub:
    """A scripted hub: each pinned address redirects to a file host that serves it."""

    def __init__(self, files: dict[str, bytes], scheme: str = "https") -> None:
        """Serve these files of the pinned model, redirecting to ``scheme``."""
        self.files = files
        self.scheme = scheme
        self.asked: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Redirect from the hub, then serve from the file host."""
        self.asked.append(str(request.url))
        prefix = f"/{MODEL.repository}/resolve/{MODEL.revision}/"
        if request.url.host == "huggingface.co" and request.url.path.startswith(prefix):
            name = request.url.path.removeprefix(prefix)
            location = f"{self.scheme}://files.example/{name}"
            return httpx.Response(302, headers={"location": location})
        name = request.url.path.removeprefix("/")
        if request.url.host == "files.example" and name in self.files:
            return httpx.Response(200, content=self.files[name])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        """Return the client that ``model pull`` uses, over this hub instead of the network."""
        return download_client(httpx.MockTransport(self.handle))


def files_in(folder: Path) -> list[str]:
    """List the files under a folder, by name."""
    return sorted(path.name for path in folder.rglob("*") if path.is_file())


@pytest.mark.parametrize(
    ("pooling", "inputs"), [("first", ENCODER), ("mean", ENCODER), ("last", DECODER)]
)
def test_a_text_embeds_alike_alone_and_beside_a_longer_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    pooling: Literal["first", "mean", "last"],
    inputs: tuple[str, ...],
) -> None:
    """Padding never changes a vector: pooling heeds the mask, the last token is the text's."""
    registered(tmp_path, monkeypatch, pooling=pooling, inputs=inputs)
    embedder = load("tiny", tmp_path)
    short = "undo the payout"
    alone = embedder.documents([short])[0]
    beside = embedder.documents([short, "a much longer text about a release and a holiday"])[0]
    assert float(alone @ beside) > SAME
    vectors = embedder.documents([short, "lunch"])
    assert vectors.shape == (2, DIMENSIONS)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)


def test_words_of_one_concept_are_near_and_others_far(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The tiny model's meaning: a paraphrase is nearer than another topic."""
    registered(tmp_path, monkeypatch)
    embedder = load("tiny", tmp_path)
    near, far = embedder.documents(["revert the seller payouts", "lunch at the canteen"])
    query = embedder.query("undo payout")[0]
    assert float(query @ near) > float(query @ far)


def test_queries_and_documents_take_their_own_prefixes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A query is embedded after the query prefix, a document after the document one."""
    model = registered(tmp_path, monkeypatch)
    plain = load("tiny", tmp_path)
    prefixed = replace(model, query_prefix="alpha ", document_prefix="beta ")
    monkeypatch.setitem(CATALOGUE, "tiny", prefixed)
    embedder = load("tiny", tmp_path)
    as_query, as_document = plain.documents(["alpha lunch", "beta lunch"])
    assert float(embedder.query("lunch")[0] @ as_query) > SAME
    assert float(embedder.documents(["lunch"])[0] @ as_document) > SAME


def test_a_text_beyond_the_token_limit_is_cut_not_refused(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Only the first MAX_TOKENS tokens count: what follows changes nothing."""
    registered(tmp_path, monkeypatch)
    embedder = load("tiny", tmp_path)
    head = " ".join(["alpha"] * MAX_TOKENS)
    long, alpha = embedder.documents([f"{head} {' '.join(['beta'] * 100)}", "alpha"])
    assert float(long @ alpha) > SAME


def test_a_graph_asking_for_an_unknown_input_does_not_load(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The adapter names what it cannot give, and the model counts as not loadable."""
    registered(tmp_path, monkeypatch, inputs=(*ENCODER, "pixel_values"))
    with pytest.raises(ModelError, match="the graph asks for pixel_values"):
        load("tiny", tmp_path)


def test_a_model_not_pulled_or_altered_does_not_load(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Each refusal says why and names the command that pulls the model again."""
    with pytest.raises(ModelError, match="not pulled; atlassian-offline-mcp model pull"):
        load("bge-small-en-v1.5", tmp_path)
    model = registered(tmp_path, monkeypatch)
    graph = tmp_path / "tiny" / model.graph.path
    content = bytearray(graph.read_bytes())
    content[-1] ^= 1  # same size, another hash
    graph.write_bytes(bytes(content))
    with pytest.raises(ModelError, match="files not as pinned"):
        load("tiny", tmp_path)


def test_the_fingerprint_changes_with_anything_that_makes_vectors() -> None:
    """Another commit, prefix or pooling: another fingerprint, so no vector is reused."""
    assert MODEL.fingerprint != replace(MODEL, revision="1" * 40).fingerprint
    assert MODEL.fingerprint != replace(MODEL, query_prefix="").fingerprint
    assert MODEL.fingerprint != replace(MODEL, pooling="first").fingerprint
    assert (
        MODEL.fingerprint != replace(MODEL, graph=replace(MODEL.graph, sha256="0" * 64)).fingerprint
    )
    assert MODEL.fingerprint == replace(MODEL).fingerprint


@pytest.mark.parametrize(("name", "value"), [("FORMAT", 2), ("MAX_TOKENS", 256)])
def test_the_fingerprint_changes_with_how_the_adapter_runs(
    monkeypatch: MonkeyPatch, name: str, value: int
) -> None:
    """A new format of the adapter, or another token limit, makes vectors anew."""
    before = MODEL.fingerprint
    monkeypatch.setattr(embedding, name, value)
    assert MODEL.fingerprint != before


def test_pull_stores_every_file_and_then_fetches_nothing(tmp_path: Path) -> None:
    """Pinned files land in the model's folder; a second pull asks for nothing."""
    hub = Hub(SERVED)
    assert pull(MODEL, tmp_path, hub.client()) == ["onnx/model.onnx", "tokenizer.json"]
    assert (tmp_path / "pinned" / "onnx" / "model.onnx").read_bytes() == GRAPH
    assert pulled(MODEL, tmp_path)
    assert hub.asked[0] == f"{HUB}/someone/pinned/resolve/{MODEL.revision}/onnx/model.onnx"
    hub.asked.clear()
    assert pull(MODEL, tmp_path, hub.client()) == []
    assert hub.asked == []


@pytest.mark.parametrize("served", [b"a graph, as bytez", b"a graph, as bytes and more", b"a"])
def test_pull_refuses_a_file_not_as_pinned_and_leaves_nothing(
    tmp_path: Path, served: bytes
) -> None:
    """Another hash, a larger file or a shorter one: refused, named, and removed."""
    hub = Hub({**SERVED, "onnx/model.onnx": served})
    with pytest.raises(ModelError, match=r"pinned: onnx/model\.onnx"):
        pull(MODEL, tmp_path, hub.client())
    assert files_in(tmp_path) == []


def test_pull_fetches_again_a_file_of_the_right_size_but_another_hash(tmp_path: Path) -> None:
    """A file in place is hashed, not trusted for its size."""
    hub = Hub(SERVED)
    pull(MODEL, tmp_path, hub.client())
    (tmp_path / "pinned" / "tokenizer.json").write_bytes(b'{"a": "tokenizer"}')
    assert pull(MODEL, tmp_path, hub.client()) == ["tokenizer.json"]
    assert (tmp_path / "pinned" / "tokenizer.json").read_bytes() == TOKENIZER


def test_pull_refuses_a_redirect_to_plain_http_and_a_file_not_served(tmp_path: Path) -> None:
    """Each failure names the file; files fetched before it stay for the next run."""
    with pytest.raises(ModelError, match=r"onnx/model\.onnx: SiteError"):
        pull(MODEL, tmp_path, Hub(SERVED, scheme="http").client())
    with pytest.raises(ModelError, match=r"tokenizer\.json: the hub answered 404"):
        pull(MODEL, tmp_path, Hub({"onnx/model.onnx": GRAPH}).client())
    assert files_in(tmp_path) == ["model.onnx"]


def test_pull_follows_a_few_redirects_and_no_more(tmp_path: Path) -> None:
    """A hub that redirects for ever is given up, after MAX_REDIRECTS (5) redirects."""
    asked: list[str] = []

    def endless(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(302, headers={"location": f"https://files.example/{len(asked)}"})

    with pytest.raises(ModelError, match="TooManyRedirects"):
        pull(MODEL, tmp_path, download_client(httpx.MockTransport(endless)))
    assert len(asked) == MAX_REDIRECTS + 1 == REQUESTS
    assert files_in(tmp_path) == []


def test_pull_stops_reading_a_file_past_its_pinned_size(tmp_path: Path) -> None:
    """An endless body is cut short at the first chunk beyond the pin, not read to its end."""
    sent: list[int] = []

    def chunks() -> Iterator[bytes]:
        while True:
            sent.append(1)
            assert len(sent) <= READS, "read past the pinned size"
            yield b"x" * CHUNK_BYTES

    def endless(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks())

    with pytest.raises(ModelError, match="larger or slower than pinned"):
        pull(MODEL, tmp_path, download_client(httpx.MockTransport(endless)))
    assert files_in(tmp_path) == []


def test_pull_gives_up_a_file_past_its_deadline(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """However small, a file that comes too slowly is given up, and nothing is left."""
    monkeypatch.setattr(model_pull, "FILE_DEADLINE_S", -1)
    with pytest.raises(ModelError, match="larger or slower than pinned"):
        pull(MODEL, tmp_path, Hub(SERVED).client())
    assert files_in(tmp_path) == []


def test_files_from_a_folder_replace_one_in_place_of_another_hash(tmp_path: Path) -> None:
    """A file of the right size but not the pinned one is copied again from the folder."""
    source = tmp_path / "source"
    (source / "onnx").mkdir(parents=True)
    (source / "onnx" / "model.onnx").write_bytes(GRAPH)
    (source / "tokenizer.json").write_bytes(TOKENIZER)
    copy_from(MODEL, tmp_path / "models", source)
    (tmp_path / "models" / "pinned" / "tokenizer.json").write_bytes(b'{"a": "tokenizer"}')
    assert copy_from(MODEL, tmp_path / "models", source) == ["tokenizer.json"]
    assert (tmp_path / "models" / "pinned" / "tokenizer.json").read_bytes() == TOKENIZER


def test_files_from_a_folder_are_checked_as_pulled_ones(tmp_path: Path) -> None:
    """``--from`` copies files laid out as the hub's, and refuses one not as pinned."""
    source = tmp_path / "source"
    (source / "onnx").mkdir(parents=True)
    (source / "onnx" / "model.onnx").write_bytes(GRAPH)
    (source / "tokenizer.json").write_bytes(b"not the tokeniser")
    with pytest.raises(ModelError, match=r"tokenizer\.json: not the file pinned"):
        copy_from(MODEL, tmp_path / "models", source)
    (source / "tokenizer.json").write_bytes(TOKENIZER)
    assert copy_from(MODEL, tmp_path / "models", source) == ["tokenizer.json"]
    assert pulled(MODEL, tmp_path / "models")


def test_an_unknown_model_is_refused_with_the_known_names() -> None:
    """The message lists what the catalogue has."""
    with pytest.raises(ModelError, match=r"bge-small-en-v1\.5") as raised:
        known("no-such-model")
    assert all(name in str(raised.value) for name in CATALOGUE)


def test_the_command_lists_the_catalogue_and_refuses_an_unknown_model(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """``model list`` names every model and the setting's; ``pull`` of a stranger exits 2."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = ["--config", str(home / "none.toml")]
    assert main(["model", "list", *config]) == 0
    listed = capsys.readouterr().out
    assert all(f"{name}: " in listed for name in CATALOGUE)
    chosen = "bge-small-en-v1.5: BAAI/bge-small-en-v1.5, 133 MB, not pulled, the setting"
    assert chosen in listed
    assert main(["model", "pull", "no-such-model", *config]) == REFUSED
    assert "the known models" in capsys.readouterr().err


@pytest.mark.skipif(MODELS is None, reason="set ATLASSIAN_OFFLINE_MCP_MODELS to pulled models")
@pytest.mark.parametrize("name", sorted(CATALOGUE))
def test_a_pulled_model_embeds_by_meaning(name: str) -> None:
    """Unit vectors of the catalogue's length; a paraphrase is nearer than another topic."""
    if not pulled(CATALOGUE[name], Path(str(MODELS))):
        pytest.skip(f"{name} is not pulled")
    embedder = load(name, Path(str(MODELS)))
    documents = embedder.documents(
        [
            "To undo a bad release of the payout service, roll back to the previous image.",
            "The Paris office canteen opens at noon and closes at two.",
        ]
    )
    query = embedder.query("how do I revert a broken deployment of the payments service?")
    assert documents.shape == (2, CATALOGUE[name].dimensions)
    assert np.allclose(np.linalg.norm(documents, axis=1), 1, atol=1e-5)
    near, far = (query @ documents.T)[0]
    assert near > far


def test_pull_gives_up_a_file_trickled_in_past_its_deadline(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A byte at a time, as a scanning proxy sends it: each read is checked, not each MiB."""
    monkeypatch.setattr(model_pull, "FILE_DEADLINE_S", 0.5)
    began = time.monotonic()

    def trickle() -> Iterator[bytes]:
        while True:
            assert time.monotonic() - began < GIVEN_UP_S, "still reading past the deadline"
            time.sleep(0.05)
            yield b"x"

    def slow(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=trickle())

    with pytest.raises(ModelError, match="larger or slower than pinned"):
        pull(MODEL, tmp_path, download_client(httpx.MockTransport(slow)))
    assert time.monotonic() - began < GIVEN_UP_S
