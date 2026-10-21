"""Pulling a model's pinned files, and running a pulled model (plan 011)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import numpy as np
import pytest

from atlassian_offline_mcp.adapters.embedding import (
    CATALOGUE,
    HUB,
    File,
    Model,
    ModelError,
    known,
    load,
    pull,
    pulled,
)
from atlassian_offline_mcp.cli import main

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

GRAPH = b"a graph, as bytes"
TOKENIZER = b'{"a": "tokeniser"}'
REFUSED = 2
# Real models, pulled beforehand, for the opt-in test: a folder of model folders.
MODELS = os.environ.get("ATLASSIAN_OFFLINE_MCP_MODELS")


def pinned(path: str, content: bytes) -> File:
    """Pin a file by its content, as the catalogue does."""
    return File(path, hashlib.sha256(content).hexdigest(), len(content))


MODEL = Model(
    name="tiny",
    repository="someone/tiny",
    revision="0123456789abcdef0123456789abcdef01234567",
    graph=pinned("onnx/model.onnx", GRAPH),
    tokenizer=pinned("tokenizer.json", TOKENIZER),
    pooling="mean",
    pad="<pad>",
    query_prefix="query: ",
    document_prefix="passage: ",
    dimensions=4,
)


class Hub:
    """A scripted hub: each pinned address redirects to a file host that serves it."""

    def __init__(self, files: dict[str, bytes]) -> None:
        """Serve these files of ``someone/tiny`` at its pinned commit."""
        self.files = files
        self.asked: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Redirect from the hub, then serve from the file host."""
        self.asked.append(str(request.url))
        prefix = f"/{MODEL.repository}/resolve/{MODEL.revision}/"
        if request.url.host == "huggingface.co" and request.url.path.startswith(prefix):
            name = request.url.path.removeprefix(prefix)
            return httpx.Response(302, headers={"location": f"https://files.example/{name}"})
        name = request.url.path.removeprefix("/")
        if request.url.host == "files.example" and name in self.files:
            return httpx.Response(200, content=self.files[name])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        """Return a client over this hub, following redirects as the real one does."""
        return httpx.Client(transport=httpx.MockTransport(self.handle), follow_redirects=True)


def test_pull_stores_every_file_and_then_fetches_nothing(tmp_path: Path) -> None:
    """Pinned files land in the model's folder; a second pull asks for nothing."""
    hub = Hub({"onnx/model.onnx": GRAPH, "tokenizer.json": TOKENIZER})
    assert pull(MODEL, tmp_path, hub.client()) == ["onnx/model.onnx", "tokenizer.json"]
    assert (tmp_path / "tiny" / "onnx" / "model.onnx").read_bytes() == GRAPH
    assert pulled(MODEL, tmp_path)
    assert hub.asked[0] == f"{HUB}/someone/tiny/resolve/{MODEL.revision}/onnx/model.onnx"
    hub.asked.clear()
    assert pull(MODEL, tmp_path, hub.client()) == []
    assert hub.asked == []


@pytest.mark.parametrize(
    "served", [b"a graph, as bytez", b"a graph, as bytes and more", b"a graph"]
)
def test_pull_refuses_a_file_not_as_pinned_and_leaves_nothing(
    tmp_path: Path, served: bytes
) -> None:
    """Another hash, a larger file or a shorter one: refused, named, and removed."""
    hub = Hub({"onnx/model.onnx": served, "tokenizer.json": TOKENIZER})
    with pytest.raises(ModelError, match=r"tiny: onnx/model\.onnx"):
        pull(MODEL, tmp_path, hub.client())
    assert [path.name for path in tmp_path.rglob("*") if path.is_file()] == []
    assert not pulled(MODEL, tmp_path)


def test_pull_refuses_a_file_the_hub_does_not_serve(tmp_path: Path) -> None:
    """A status other than 200 names the file and the status."""
    hub = Hub({"onnx/model.onnx": GRAPH})
    with pytest.raises(ModelError, match=r"tokenizer\.json: the hub answered 404"):
        pull(MODEL, tmp_path, hub.client())
    assert (tmp_path / "tiny" / "onnx" / "model.onnx").is_file()
    assert not (tmp_path / "tiny" / "tokenizer.json").exists()


def test_a_file_of_another_size_is_not_pulled(tmp_path: Path) -> None:
    """A truncated file left by hand does not count as pulled, and is fetched again."""
    hub = Hub({"onnx/model.onnx": GRAPH, "tokenizer.json": TOKENIZER})
    pull(MODEL, tmp_path, hub.client())
    (tmp_path / "tiny" / "tokenizer.json").write_bytes(b"{}")
    assert not pulled(MODEL, tmp_path)
    assert pull(MODEL, tmp_path, hub.client()) == ["tokenizer.json"]


def test_an_unknown_model_is_refused_with_the_known_names() -> None:
    """The message lists what the catalogue has."""
    with pytest.raises(ModelError, match=r"bge-small-en-v1\.5") as raised:
        known("no-such-model")
    assert all(name in str(raised.value) for name in CATALOGUE)


def test_a_model_not_pulled_loads_as_nothing(tmp_path: Path) -> None:
    """The server and index then work without it; nothing is downloaded."""
    assert load("bge-small-en-v1.5", tmp_path) is None


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
    chosen = "multilingual-e5-small: intfloat/multilingual-e5-small, 487 MB, not pulled, the"
    assert chosen in listed
    assert main(["model", "pull", "no-such-model", *config]) == REFUSED
    assert "the known models" in capsys.readouterr().err


@pytest.mark.skipif(MODELS is None, reason="set ATLASSIAN_OFFLINE_MCP_MODELS to pulled models")
@pytest.mark.parametrize("name", sorted(CATALOGUE))
def test_a_pulled_model_embeds_by_meaning(name: str) -> None:
    """Unit vectors of the catalogue's length; a paraphrase is nearer than another topic."""
    embedder = load(name, Path(str(MODELS)))
    if embedder is None:
        pytest.skip(f"{name} is not pulled")
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
