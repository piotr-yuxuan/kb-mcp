"""Embedding models: which ones, where their files come from, and how they run.

Only this module knows a model's files, its tokeniser, the inputs of its graph and how
its output becomes one vector per text. The rest of the code sees an ``Embedder``: a
name, a number of dimensions, and texts in, unit vectors out. A model whose format
changes is a change of its entry in ``CATALOGUE``, and of nothing else.

Files are downloaded by ``pull`` alone, pinned by commit and checked by SHA-256;
``load`` reads them from the models folder and never reaches the network.
"""

from __future__ import annotations

import hashlib
import os
import ssl
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import httpx
import numpy as np
import onnxruntime
import truststore
from tokenizers import Tokenizer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from numpy.typing import NDArray

    type Vectors = NDArray[np.float32]

HUB = "https://huggingface.co"
# Tokens a text is cut to: the window of the smaller models.
MAX_TOKENS = 512
# Texts run through a graph at once; texts of like length are batched together.
BATCH = 16
CHUNK_BYTES = 1024 * 1024
# How long one file's download may take, in seconds, and wait between two reads.
FILE_DEADLINE_S = 3600
READ_TIMEOUT_S = 60
# The graph output whose rows are pooled into one vector per text.
OUTPUT = "last_hidden_state"


@dataclass(frozen=True)
class File:
    """A file of a model: its path in the repository and in the model's folder."""

    path: str
    sha256: str
    size: int  # bytes


@dataclass(frozen=True)
class Model:
    """A model of the catalogue, pinned to one commit of its repository.

    ``pooling`` says which hidden states make a text's vector: the first token's, the
    mean of all, or the last token's. A query and a document take their prefixes.
    """

    name: str
    repository: str
    revision: str
    graph: File
    tokenizer: File
    pooling: Literal["first", "mean", "last"]
    pad: str  # the tokeniser's padding token
    query_prefix: str
    document_prefix: str
    dimensions: int

    @property
    def files(self) -> tuple[File, ...]:
        """Every file that the model needs."""
        return (self.graph, self.tokenizer)


CATALOGUE = {
    model.name: model
    for model in (
        Model(
            name="bge-small-en-v1.5",
            repository="BAAI/bge-small-en-v1.5",
            revision="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
            graph=File(
                "onnx/model.onnx",
                "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",
                133_093_490,
            ),
            tokenizer=File(
                "tokenizer.json",
                "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
                711_396,
            ),
            pooling="first",
            pad="[PAD]",
            query_prefix="Represent this sentence for searching relevant passages: ",
            document_prefix="",
            dimensions=384,
        ),
        Model(
            name="multilingual-e5-small",
            repository="intfloat/multilingual-e5-small",
            revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
            graph=File(
                "onnx/model.onnx",
                "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665",
                470_268_510,
            ),
            tokenizer=File(
                "tokenizer.json",
                "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
                17_082_730,
            ),
            pooling="mean",
            pad="<pad>",
            query_prefix="query: ",
            document_prefix="passage: ",
            dimensions=384,
        ),
        Model(
            name="qwen3-embedding-0.6b",
            repository="onnx-community/Qwen3-Embedding-0.6B-ONNX",
            revision="c25a394dd583836952667c12f008335071b3f43d",
            graph=File(
                "onnx/model_int8.onnx",
                "6d0ea863f78b4a84afa3c7fcba1ec341572b5e28121aef77b7092b1dfdf679c7",
                613_527_539,
            ),
            tokenizer=File(
                "tokenizer.json",
                "def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a",
                11_423_705,
            ),
            pooling="last",
            pad="<|endoftext|>",
            query_prefix=(
                "Instruct: Given a web search query, retrieve relevant passages that answer"
                " the query\nQuery:"
            ),
            document_prefix="",
            dimensions=1024,
        ),
    )
}


class Embedder(Protocol):
    """Texts in, unit vectors of float32 out, one row per text."""

    @property
    def name(self) -> str:
        """The model's name in the catalogue, which the index records."""
        ...

    @property
    def dimensions(self) -> int:
        """The length of each vector."""
        ...

    def documents(self, texts: Sequence[str]) -> Vectors:
        """Embed texts to be found."""
        ...

    def query(self, text: str) -> Vectors:
        """Embed a query, as a vector of one row."""
        ...


class ModelError(Exception):
    """A model that cannot be pulled or run as its entry says; the message says why."""


# How each input that a graph may declare is made from a batch's ids and mask; decoder
# graphs also declare their past keys and values, given empty.
INPUTS: dict[str, Callable[[NDArray[np.int64], NDArray[np.int64]], NDArray[np.int64]]] = {
    "input_ids": lambda ids, _: ids,
    "attention_mask": lambda _, mask: mask,
    "token_type_ids": lambda ids, _: np.zeros_like(ids),
    "position_ids": lambda _, mask: np.maximum(np.cumsum(mask, axis=1) - 1, 0),
}
PAST = "past_key_values."
POOLING: dict[str, Callable[[NDArray[np.float32], NDArray[np.int64]], NDArray[np.float32]]] = {
    "first": lambda hidden, _: hidden[:, 0],
    "mean": lambda hidden, mask: (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True),
    "last": lambda hidden, mask: hidden[np.arange(len(hidden)), mask.sum(1) - 1],
}


class OnnxEmbedder:
    """A model of the catalogue, run on the CPU from its pulled files."""

    def __init__(self, model: Model, folder: Path) -> None:
        """Load the model's tokeniser and graph from ``folder``.

        Raises ModelError when the graph asks for an input this module cannot give.
        """
        self._model = model
        self._tokenizer = Tokenizer.from_file(str(folder / model.tokenizer.path))
        self._tokenizer.enable_truncation(MAX_TOKENS)
        pad = self._tokenizer.token_to_id(model.pad)
        if pad is None:
            message = f"{model.name}: no padding token {model.pad!r} in its tokeniser"
            raise ModelError(message)
        self._tokenizer.enable_padding(pad_id=pad, pad_token=model.pad)
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3  # errors only, on stderr
        self._session = onnxruntime.InferenceSession(
            str(folder / model.graph.path), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = [(each.name, each.shape) for each in self._session.get_inputs()]
        unknown = [
            name for name, _ in self._inputs if name not in INPUTS and not name.startswith(PAST)
        ]
        if unknown:
            message = f"{model.name}: the graph asks for {', '.join(unknown)}"
            raise ModelError(message)

    @property
    def name(self) -> str:
        """The model's name in the catalogue."""
        return self._model.name

    @property
    def dimensions(self) -> int:
        """The length of each vector."""
        return self._model.dimensions

    def _run(self, texts: Sequence[str]) -> Vectors:
        encodings = self._tokenizer.encode_batch(list(texts))
        ids = np.array([each.ids for each in encodings], dtype=np.int64)
        mask = np.array([each.attention_mask for each in encodings], dtype=np.int64)
        feed: dict[str, NDArray[np.int64] | NDArray[np.float32]] = {}
        for name, shape in self._inputs:
            if name.startswith(PAST):
                feed[name] = np.zeros((len(texts), shape[1], 0, shape[3]), dtype=np.float32)
            else:
                feed[name] = INPUTS[name](ids, mask)
        hidden = self._session.run([OUTPUT], feed)[0]
        vectors = POOLING[self._model.pooling](hidden, mask)
        return (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float32)

    def documents(self, texts: Sequence[str]) -> Vectors:
        """Embed texts to be found, in batches of texts of like length."""
        prefixed = [self._model.document_prefix + text for text in texts]
        order = sorted(range(len(prefixed)), key=lambda index: len(prefixed[index]))
        vectors = np.empty((len(prefixed), self.dimensions), dtype=np.float32)
        for start in range(0, len(order), BATCH):
            chosen = order[start : start + BATCH]
            vectors[chosen] = self._run([prefixed[index] for index in chosen])
        return vectors

    def query(self, text: str) -> Vectors:
        """Embed a query, with the model's query prefix."""
        return self._run([self._model.query_prefix + text])


def pulled(model: Model, models: Path) -> bool:
    """Say whether every file of a model is in its folder, with its size."""
    folder = models / model.name
    return all(
        (folder / file.path).is_file() and (folder / file.path).stat().st_size == file.size
        for file in model.files
    )


def load(name: str, models: Path) -> OnnxEmbedder | None:
    """Load a model of the catalogue from ``models``, or None when it is not pulled.

    Raises ModelError for a name the catalogue does not have.
    """
    model = known(name)
    return OnnxEmbedder(model, models / model.name) if pulled(model, models) else None


def known(name: str) -> Model:
    """Find a model of the catalogue; raise ModelError, naming the known ones, if absent."""
    if name not in CATALOGUE:
        message = f"no model {name!r}; the known models: {', '.join(sorted(CATALOGUE))}"
        raise ModelError(message)
    return CATALOGUE[name]


def download_client() -> httpx.Client:
    """Return a client for the hub: the OS trust store, redirects to its file hosts."""
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    timeout = httpx.Timeout(READ_TIMEOUT_S, connect=READ_TIMEOUT_S)
    return httpx.Client(verify=context, timeout=timeout, follow_redirects=True)


def pull(model: Model, models: Path, client: httpx.Client) -> list[str]:
    """Download the files of a model that its folder lacks; return the paths fetched.

    Each file is pinned by the catalogue's commit, stopped past its size, checked by
    SHA-256 and only then renamed into place. Raises ModelError naming a file that the
    hub refuses or that does not match; nothing of that file is left.
    """
    folder = models / model.name
    fetched: list[str] = []
    for file in model.files:
        target = folder / file.path
        if target.is_file() and target.stat().st_size == file.size:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".pull-", dir=target.parent)
        temporary = Path(name)
        try:
            digest, size = hashlib.sha256(), 0
            deadline = time.monotonic() + FILE_DEADLINE_S
            address = f"{HUB}/{model.repository}/resolve/{model.revision}/{file.path}"
            with os.fdopen(descriptor, "wb") as out, client.stream("GET", address) as response:
                if response.status_code != httpx.codes.OK:
                    message = f"{model.name}: {file.path}: the hub answered {response.status_code}"
                    raise ModelError(message)
                for chunk in response.iter_bytes(CHUNK_BYTES):
                    size += len(chunk)
                    if size > file.size or time.monotonic() > deadline:
                        message = f"{model.name}: {file.path}: larger or slower than expected"
                        raise ModelError(message)
                    digest.update(chunk)
                    out.write(chunk)
            if size != file.size or digest.hexdigest() != file.sha256:
                message = f"{model.name}: {file.path}: not the file pinned (size or SHA-256)"
                raise ModelError(message)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        fetched.append(file.path)
    return fetched
