"""Embedding models: which ones, where their files come from, and how they run.

Only this module knows a model's files, its tokeniser, the inputs of its graph and how
its output becomes one vector per text. The rest of the code sees an ``Embedder``: a
name, a number of dimensions, and texts in, unit vectors out. A model whose format
changes is a change of its entry in ``CATALOGUE``, and of nothing else.

Files are downloaded by ``adapters.model_pull`` alone; ``load`` reads them from the
models folder, checks them against their pinned SHA-256, and never reaches the network.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, Protocol

import numpy as np
import onnxruntime
from tokenizers import Tokenizer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

    type Vectors = NDArray[np.float32]

# Tokens a text is cut to: the window of the smaller models.
MAX_TOKENS = 512
# Texts run through a graph at once; texts of like length are batched together.
BATCH = 16
CHUNK_BYTES = 1024 * 1024
# The graph output whose rows are pooled into one vector per text.
OUTPUT = "last_hidden_state"
# The version of how this module turns texts into vectors; a change that alters any
# vector raises it, so that no vector embedded before is reused.
FORMAT = 1


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

    @property
    def fingerprint(self) -> str:
        """Name everything that makes the model's vectors, and how this module runs it."""
        described = json.dumps({**asdict(self), "format": FORMAT, "max_tokens": MAX_TOKENS})
        return hashlib.sha256(described.encode()).hexdigest()


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
    """Texts in, unit vectors of float32 out, one row per text.

    Raises ModelError when the model fails to embed.
    """

    @property
    def name(self) -> str:
        """The model's name in the catalogue, which the index records."""
        ...

    @property
    def fingerprint(self) -> str:
        """What the model's vectors depend on; vectors of another one are never reused."""
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


class NotPulledError(ModelError):
    """A model of the catalogue whose files are not all in the models folder."""


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
    def fingerprint(self) -> str:
        """What the model's vectors depend on."""
        return self._model.fingerprint

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
        try:
            hidden = self._session.run([OUTPUT], feed)[0]
        except Exception as error:
            # onnxruntime raises exceptions of its own, of no stable type.
            message = f"{self.name}: does not embed ({type(error).__name__})"
            raise ModelError(message) from error
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


def matches(path: Path, file: File) -> bool:
    """Say whether a file on disk is the one pinned: its size, then its SHA-256."""
    if not path.is_file() or path.stat().st_size != file.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest() == file.sha256


def load(name: str, models: Path) -> OnnxEmbedder:
    """Load a model of the catalogue from ``models``, once its files are checked.

    Raises ModelError, saying why and what to do, for a name the catalogue does not
    have, a model not pulled, files that are not those pinned, or a graph that does not
    load.
    """
    model = known(name)
    folder = models / model.name
    if not pulled(model, models):
        message = f"{name}: not pulled; atlassian-offline-mcp model pull {name}"
        raise NotPulledError(message)
    if not all(matches(folder / file.path, file) for file in model.files):
        message = f"{name}: files not as pinned; atlassian-offline-mcp model pull {name}"
        raise ModelError(message)
    try:
        return OnnxEmbedder(model, folder)
    except ModelError:
        raise
    except Exception as error:
        # onnxruntime and tokenizers raise exceptions of their own, of no stable type.
        message = f"{name}: does not load ({type(error).__name__})"
        raise ModelError(message) from error


def known(name: str) -> Model:
    """Find a model of the catalogue; raise ModelError, naming the known ones, if absent."""
    if name not in CATALOGUE:
        message = f"no model {name!r}; the known models: {', '.join(sorted(CATALOGUE))}"
        raise ModelError(message)
    return CATALOGUE[name]
