"""Embeddings from an OpenAI-compatible API: Ollama on this machine, by default.

Only this module knows the API: its requests and answers, the one part of Ollama's own
API used (its list of models, for a model's digest), and the prefixes that each known
model asks for. The rest of the code sees an ``Embedder``: a name, a fingerprint, its
dimensions, and texts in, unit vectors of float32 out.

The mirror's text leaves this machine only when the run's command line allows it:
``model_api.endpoint`` is the only way to a client, and refuses any other address.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import httpx
import numpy as np
from numpy.typing import NDArray
from opentelemetry import trace
from pydantic import ConfigDict

from kb_mcp.kernel.record import Record
from kb_mcp.observability.adapters.http import client_span, server
from kb_mcp.search.adapters.model_api import (
    OPERATION_DURATION,
    TOKEN_USAGE,
    WAITS_S,
    Bounds,
    ModelError,
    send,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from kb_mcp.search.adapters.model_api import Endpoint

type Vectors = NDArray[np.float32]
# The environment variable that holds the endpoint's API key, if it needs one.
KEY_VARIABLE = "KB_MCP_EMBEDDING_API_KEY"
# Texts sent in one request; a piece is at most about 1,500 characters.
BATCH = 32
MAX_DIMENSIONS = 8192
# Statuses that may point at what was sent, so that a text sent alone may still embed:
# 500 too, as bge-m3 answers to some Markdown. A gateway's 502, 503 or 504, and a 429,
# are the endpoint's, never the text's.
REFUSING = frozenset({400, 413, 422, 500})
PROBE = "probe"
# The version of how this module turns texts into vectors; a change that alters any
# vector raises it, so that no vector embedded before is reused.
FORMAT = 1
# The provider, as the GenAI conventions name it by the client's best knowledge: the API
# that this module speaks, whichever server answers.
PROVIDER = "openai"


DOCUMENTS = Bounds(deadline_s=120, attempts=len(WAITS_S) + 1)
# Queries, the probe, the list of models and texts tried alone: a search falls back to
# words at once, and the next one tries again.
SINGLE = Bounds(deadline_s=30, attempts=1)


class Prefixes(Record):
    """What a model's card asks to put before a query, and before a document."""

    query: str
    document: str


GEMMA = Prefixes(query="task: search result | query: ", document="title: none | text: ")
NOMIC = Prefixes(query="search_query: ", document="search_document: ")
# Each known family's prefixes, from its model card; a model of another family, such as
# bge-m3, whose card asks for none, embeds texts as they are.
PREFIXES = {
    "qwen3-embedding": Prefixes(
        query="Instruct: Given a web search query, retrieve relevant passages that answer the query"
        "\nQuery:",
        document="",
    ),
    "embeddinggemma": GEMMA,
    "embeddinggemma-2": GEMMA,
    "nomic-embed-text": NOMIC,
    "nomic-embed-text-v2-moe": NOMIC,
    "snowflake-arctic-embed2": Prefixes(query="query: ", document=""),
}


def prefixes(model: str) -> Prefixes | None:
    """Give the prefixes that a model's card asks for, or None for a model not known.

    The family is the name before its tag, as Ollama resolves the name.
    """
    return PREFIXES.get(ollama_name(model).partition(":")[0])


class RefusedError(ModelError):
    """An answer that points at what was sent: a text sent alone may still embed."""


class Embedder(Protocol):
    """Texts in, unit vectors of float32 out.

    Raises ModelError when the model does not embed.
    """

    @property
    def name(self) -> str:
        """The model's name, as the endpoint knows it and the index records it."""
        ...

    @property
    def fingerprint(self) -> str:
        """What the model's vectors depend on; vectors of another one are never reused."""
        ...

    @property
    def dimensions(self) -> int:
        """The length of each vector."""
        ...

    @property
    def tokens(self) -> int | None:
        """The tokens counted for the texts of ``documents`` so far, None if not all were."""
        ...

    def documents(self, texts: Sequence[str]) -> list[NDArray[np.float32] | None]:
        """Embed texts to be found: a vector for each, or None for one the model refuses."""
        ...

    def query(self, text: str) -> Vectors:
        """Embed a query, as a vector of one row."""
        ...


class Embeddings(Record):
    """What the endpoint gave for texts: a unit vector each, and the tokens it counted."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    vectors: Vectors
    tokens: int | None  # the answer's usage.prompt_tokens, None when it says none


def embeddings(
    endpoint: Endpoint, model: str, texts: Sequence[str], bounds: Bounds, dimensions: int = 0
) -> Embeddings:
    """Embed texts with a model, each to a unit vector, in the order given.

    ``dimensions``, when not 0, is the length that every vector must have. The tokens are
    the answer's ``usage.prompt_tokens``, None when it gives none or null; a ``usage``
    that is not an object, or any value there but an integer of 0 or more, refuses the
    answer. Raises RefusedError when the answer points at what was sent, and ModelError
    otherwise.

    The embedding is a span ``embeddings <model>`` that holds its attempts and the
    tokens counted, if any; its duration and those tokens are measured, as the GenAI
    conventions have them.
    """
    measured = {
        "gen_ai.operation.name": "embeddings",
        "gen_ai.provider.name": PROVIDER,
        "gen_ai.request.model": model,
        **server(endpoint.http.base_url),
    }
    with client_span(f"embeddings {model}", OPERATION_DURATION, measured, {}):
        status, body = send(
            endpoint, "POST", "embeddings", bounds, {"model": model, "input": texts}
        )
        if status in {401, 403}:
            message = f"{model}: the endpoint refused its key ({status}); see {KEY_VARIABLE}"
            raise ModelError(message)
        if status == httpx.codes.NOT_FOUND:
            message = (
                f"{model}: not there, or the address is not the API's (Ollama's ends in /v1);"
                f" with Ollama: ollama pull {model}"
            )
            raise ModelError(message)
        if status != httpx.codes.OK:
            message = f"{model}: the endpoint answered {status}"
            raise (RefusedError if status in REFUSING else ModelError)(message)
        try:
            answer = json.loads(body)
            items = sorted(answer["data"], key=lambda item: item["index"])
            indexes = [item["index"] for item in items]
            vectors = np.array([item["embedding"] for item in items])
        except (ValueError, KeyError, TypeError, RecursionError) as error:
            message = f"{model}: the endpoint's answer is not embeddings ({type(error).__name__})"
            raise ModelError(message) from None
        wanted = (len(texts), dimensions or vectors.shape[-1])
        if (
            indexes != list(range(len(texts)))
            or vectors.dtype.kind not in "iuf"
            or vectors.shape != wanted
            or not 0 < wanted[1] <= MAX_DIMENSIONS
        ):
            message = f"{model}: the endpoint's answer is not one vector of {wanted[1]} per text"
            raise ModelError(message)
        usage = answer.get("usage")  # an object, since its "data" was read
        tokens = usage.get("prompt_tokens") if type(usage) is dict else None
        if (usage is not None and type(usage) is not dict) or (
            tokens is not None and (type(tokens) is not int or tokens < 0)
        ):
            message = f"{model}: the endpoint's usage is not a count of tokens"
            raise ModelError(message)
        if tokens is not None:
            trace.get_current_span().set_attribute("gen_ai.usage.input_tokens", tokens)
            TOKEN_USAGE.record(tokens, {**measured, "gen_ai.token.type": "input"})
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.all(np.isfinite(norms) & (norms > 0)):
            message = f"{model}: the endpoint gave a vector of no length, or not of numbers"
            raise ModelError(message)
        return Embeddings(vectors=(vectors / norms).astype(np.float32), tokens=tokens)


def embed(
    endpoint: Endpoint, model: str, texts: Sequence[str], bounds: Bounds, dimensions: int = 0
) -> Vectors:
    """Embed texts with a model, each to a unit vector, as ``embeddings`` does; no tokens."""
    return embeddings(endpoint, model, texts, bounds, dimensions).vectors


def ollama_name(name: str) -> str:
    """Write a model's name as Ollama resolves it, to compare two.

    In lower case, with its tag (``latest`` when none is given), and without the default
    registry and namespace.
    """
    lower = name.lower()
    tagged = lower if ":" in lower.rpartition("/")[2] else f"{lower}:latest"
    # Ollama refuses a default registry without a namespace; so does the embedding then.
    host = tagged.removeprefix("registry.ollama.ai/").removeprefix("ollama.com/")
    return host.removeprefix("library/")


def digest(endpoint: Endpoint, model: str) -> str:
    """Give the digest that Ollama lists for a model, or "" from a server that lists none.

    Names compare as Ollama resolves them; the digests of every row of the name are
    joined, as Ollama has listed one model twice. Raises ModelError when the list
    cannot be read, when Ollama's list lacks the model, and for a model that Ollama
    serves from elsewhere (a cloud model) unless the run allows it.
    """
    root = str(endpoint.http.base_url).removesuffix("/").removesuffix("/v1")
    status, body = send(endpoint, "GET", f"{root}/api/tags", SINGLE)
    if status in {httpx.codes.NOT_FOUND, httpx.codes.METHOD_NOT_ALLOWED}:
        return ""
    if status != httpx.codes.OK:
        message = f"{model}: the endpoint's list of models answered {status}"
        raise ModelError(message)
    wanted = ollama_name(model)
    try:
        rows = [row for row in json.loads(body)["models"] if ollama_name(row["name"]) == wanted]
        found = "+".join(sorted(row["digest"] for row in rows))
        elsewhere = any(row.get("remote_host") for row in rows)
    except ValueError, KeyError, TypeError, AttributeError, RecursionError:
        return ""  # not Ollama's list: a server that reports no digest
    if not rows:
        message = f"{model}: not in Ollama's list of models; with Ollama: ollama pull {model}"
        raise ModelError(message)
    if elsewhere and not endpoint.remote_allowed:
        message = (
            f"{model}: Ollama serves it from elsewhere (a cloud model), where the mirror's"
            f" text would go; pass {endpoint.service.flag}"
        )
        raise ModelError(message)
    return found


@dataclass(frozen=True)
class ApiEmbedder:
    """A model behind the endpoint, as connected: what its vectors depend on, and how to ask."""

    endpoint: Endpoint
    name: str
    digest: str
    dimensions: int
    prefixes: Prefixes
    # The tokens that the endpoint counted in each answer to ``documents``, if it did.
    counted: list[int | None] = field(default_factory=list, init=False, compare=False)

    @property
    def tokens(self) -> int | None:
        """Sum the tokens counted for ``documents`` so far; None unless every answer counted."""
        return None if not self.counted or None in self.counted else sum(self.counted)

    @property
    def fingerprint(self) -> str:
        """Name everything that makes the model's vectors, and how this module asks for them."""
        described = json.dumps(
            {
                "model": self.name,
                "digest": self.digest,
                "dimensions": self.dimensions,
                "query": self.prefixes.query,
                "document": self.prefixes.document,
                "format": FORMAT,
            }
        )
        return hashlib.sha256(described.encode()).hexdigest()

    def check(self) -> None:
        """Refuse when the model's digest is no longer the one connected to."""
        if digest(self.endpoint, self.name) != self.digest:
            message = f"{self.name}: the model changed during this run (ollama pull?); run again"
            raise ModelError(message)

    def documents(self, texts: Sequence[str]) -> list[NDArray[np.float32] | None]:
        """Embed texts to be found, BATCH at a time; None for a text the endpoint refuses.

        A batch refused goes again text by text. Every text of several refused alone is
        the endpoint's fault, a limit of its own; one text refused alone is the text's
        unless the probe fails too. The digest is read before and after, so that no
        vector of other weights is given under this fingerprint. Raises ModelError.
        """
        self.check()
        found: list[NDArray[np.float32] | None] = []
        for start in range(0, len(texts), BATCH):
            batch = [self.prefixes.document + text for text in texts[start : start + BATCH]]
            try:
                answer = embeddings(self.endpoint, self.name, batch, DOCUMENTS, self.dimensions)
                found += list(answer.vectors)
                self.counted.append(answer.tokens)
            except RefusedError:
                alone: list[NDArray[np.float32] | None] = []
                for text in batch:
                    try:
                        answer = embeddings(
                            self.endpoint, self.name, [text], SINGLE, self.dimensions
                        )
                        alone.append(answer.vectors[0])
                        self.counted.append(answer.tokens)
                    except RefusedError:
                        alone.append(None)
                if all(vector is None for vector in alone):
                    if len(alone) > 1:
                        message = f"{self.name}: the endpoint refuses every text, each alone"
                        raise ModelError(message) from None
                    probe = [self.prefixes.query + PROBE]
                    embed(self.endpoint, self.name, probe, SINGLE, self.dimensions)
                found += alone
        self.check()
        return found

    def query(self, text: str) -> Vectors:
        """Embed a query, with the model's query prefix."""
        return embed(
            self.endpoint, self.name, [self.prefixes.query + text], SINGLE, self.dimensions
        )


def connect(endpoint: Endpoint, model: str) -> ApiEmbedder:
    """Connect to a model behind the endpoint: its digest, then a probe for its dimensions.

    Raises ModelError, saying what to do, when the endpoint does not answer, lacks the
    model, or gives vectors that cannot be used.
    """
    known = prefixes(model) or Prefixes(query="", document="")
    found = digest(endpoint, model)
    probe = embed(endpoint, model, [known.query + PROBE], SINGLE)
    return ApiEmbedder(endpoint, model, found, probe.shape[1], known)
