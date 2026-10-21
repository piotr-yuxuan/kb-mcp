"""Embeddings from an OpenAI-compatible API: Ollama on this machine, by default.

Only this module knows the API: its requests and answers, the one part of Ollama's own
API used (its list of models, for a model's digest), and the prefixes that each known
model asks for. The rest of the code sees an ``Embedder``: a name, a fingerprint, its
dimensions, and texts in, unit vectors of float32 out.

The mirror's text leaves this machine only when the run's command line allows it:
``endpoint`` is the only way to a client, and refuses any other address.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, Self

import httpx
import numpy as np
import truststore

from atlassian_offline_mcp.domain.settings import SettingsError, loopback

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from numpy.typing import NDArray

    type Vectors = NDArray[np.float32]

# The environment variable that holds the endpoint's API key, if it needs one.
KEY_VARIABLE = "ATLASSIAN_OFFLINE_MCP_EMBEDDING_API_KEY"
# Texts sent in one request; a piece is at most about 1,500 characters.
BATCH = 32
MAX_DIMENSIONS = 8192
MAX_ANSWER_BYTES = 64 * 1024 * 1024
# Statuses worth another attempt: the endpoint busy, or failing for a while.
RETRIED = frozenset({429, 500, 502, 503, 504})
# Statuses that point at what was sent, or at a failure that outlived its retries: a
# text sent alone may still embed. A 429 is the endpoint's limit, never the text's.
REFUSING = frozenset({400, 413, 422}) | RETRIED - {429}
# Seconds waited before the second attempt, and before the third.
WAITS_S = (1.0, 4.0)
PROBE = "probe"
# The version of how this module turns texts into vectors; a change that alters any
# vector raises it, so that no vector embedded before is reused.
FORMAT = 1


@dataclass(frozen=True)
class Bounds:
    """How long one attempt may take, in seconds, and how many attempts a request gets."""

    deadline_s: float
    attempts: int


DOCUMENTS = Bounds(120, len(WAITS_S) + 1)
# Queries, the probe, the list of models and texts tried alone: a search falls back to
# words at once, and the next one tries again.
SINGLE = Bounds(30, 1)


@dataclass(frozen=True)
class Prefixes:
    """What a model's card asks to put before a query, and before a document."""

    query: str
    document: str


GEMMA = Prefixes("task: search result | query: ", "title: none | text: ")
NOMIC = Prefixes("search_query: ", "search_document: ")
# Each known family's prefixes, from its model card; a model of another family, such as
# bge-m3, whose card asks for none, embeds texts as they are.
PREFIXES = {
    "qwen3-embedding": Prefixes(
        "Instruct: Given a web search query, retrieve relevant passages that answer the query"
        "\nQuery:",
        "",
    ),
    "embeddinggemma": GEMMA,
    "embeddinggemma-2": GEMMA,
    "nomic-embed-text": NOMIC,
    "nomic-embed-text-v2-moe": NOMIC,
    "snowflake-arctic-embed2": Prefixes("query: ", ""),
}


def prefixes(model: str) -> Prefixes | None:
    """Give the prefixes that a model's card asks for, or None for a model not known."""
    return PREFIXES.get(model.partition(":")[0])


class ModelError(Exception):
    """An embedding that the endpoint did not give; the message says why and what to do."""


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

    def documents(self, texts: Sequence[str]) -> list[NDArray[np.float32] | None]:
        """Embed texts to be found: a vector for each, or None for one the model refuses."""
        ...

    def query(self, text: str) -> Vectors:
        """Embed a query, as a vector of one row."""
        ...


@dataclass(frozen=True)
class Endpoint:
    """An open client to the embedding API, what this run allows, and its clock.

    Closed after use, as a context manager.
    """

    http: httpx.Client
    remote_allowed: bool
    sleep: Callable[[float], None] = field(default=time.sleep)
    clock: Callable[[], float] = field(default=time.monotonic)

    def __enter__(self) -> Self:
        """Use the endpoint."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close its client."""
        self.http.close()


def endpoint(
    url: str, key: str | None, *, remote_allowed: bool, transport: httpx.BaseTransport | None = None
) -> Endpoint:
    """Open a client to the API at ``url``, with ``key`` as its bearer token, if any.

    Raises SettingsError for an address that is not a literal address of this machine,
    unless ``remote_allowed``, and for plain http to one even then. On this machine the
    environment's proxies are ignored, since one would carry the text away; redirects
    are never followed. ``transport`` replaces the network, for tests.
    """
    here = loopback(url)
    if not here and not remote_allowed:
        message = (
            "embedding_url: not an address of this machine, where the mirror's text would"
            " go; write 127.0.0.1 for this one, or pass --allow-remote-embeddings"
        )
        raise SettingsError(message)
    if not here and not url.startswith("https://"):
        message = "embedding_url: an endpoint off this machine is reached over https only"
        raise SettingsError(message)
    http = httpx.Client(
        base_url=url,
        headers={"Authorization": f"Bearer {key}"} if key else {},
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        trust_env=not here,
        follow_redirects=False,
        transport=transport,
    )
    return Endpoint(http, remote_allowed)


def send(
    endpoint: Endpoint, method: str, url: str, bounds: Bounds, payload: object = None
) -> tuple[int, bytes]:
    """Make a request within its bounds; give the status and body of its last answer.

    httpx bounds each phase of an attempt by the deadline (connecting, sending, the
    answer's first byte), and the body must end by the deadline itself, checked at every
    read, within MAX_ANSWER_BYTES. A transport error, a passed deadline, an answer too
    large or a status of RETRIED is tried again, after a wait, while attempts remain.
    Raises ModelError when no attempt got a whole answer.
    """
    reason = "no attempt"
    for attempt in range(bounds.attempts):
        if attempt:
            endpoint.sleep(WAITS_S[attempt - 1])
        deadline = endpoint.clock() + bounds.deadline_s
        answer = None
        try:
            with endpoint.http.stream(
                method, url, json=payload, timeout=bounds.deadline_s
            ) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_ANSWER_BYTES or endpoint.clock() > deadline:
                        reason = "an answer too large or too slow"
                        break
                else:
                    answer = (response.status_code, bytes(body))
        except httpx.HTTPError as error:
            reason = type(error).__name__
        if answer is not None and (answer[0] not in RETRIED or attempt + 1 == bounds.attempts):
            return answer
    message = (
        f"no answer from the embedding endpoint ({reason}); is it running?"
        " With Ollama: ollama serve"
    )
    raise ModelError(message)


def embed(
    endpoint: Endpoint, model: str, texts: Sequence[str], bounds: Bounds, dimensions: int = 0
) -> Vectors:
    """Embed texts with a model, each to a unit vector, in the order given.

    ``dimensions``, when not 0, is the length that every vector must have. Raises
    RefusedError when the answer points at what was sent, and ModelError otherwise.
    """
    status, body = send(endpoint, "POST", "embeddings", bounds, {"model": model, "input": texts})
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
        items = sorted(json.loads(body)["data"], key=lambda item: item["index"])
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
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms) & (norms > 0)):
        message = f"{model}: the endpoint gave a vector of no length, or not of numbers"
        raise ModelError(message)
    return (vectors / norms).astype(np.float32)


def ollama_name(name: str) -> str:
    """Write a model's name as Ollama resolves it, to compare two.

    In lower case, with its tag (``latest`` when none is given), and without the default
    registry and namespace.
    """
    lower = name.lower()
    tagged = lower if ":" in lower.rpartition("/")[2] else f"{lower}:latest"
    return tagged.removeprefix("registry.ollama.ai/").removeprefix("library/")


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
            " text would go; pass --allow-remote-embeddings"
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

        A batch refused goes again text by text. When every text is refused alone, the
        probe tells whether the endpoint is at fault rather than the texts. The digest
        is read before and after, so that no vector of other weights is given under this
        fingerprint. Raises ModelError.
        """
        self.check()
        found: list[NDArray[np.float32] | None] = []
        for start in range(0, len(texts), BATCH):
            batch = [self.prefixes.document + text for text in texts[start : start + BATCH]]
            try:
                found += list(embed(self.endpoint, self.name, batch, DOCUMENTS, self.dimensions))
            except RefusedError:
                alone: list[NDArray[np.float32] | None] = []
                for text in batch:
                    try:
                        alone.append(
                            embed(self.endpoint, self.name, [text], SINGLE, self.dimensions)[0]
                        )
                    except RefusedError:
                        alone.append(None)
                if all(vector is None for vector in alone):
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
    known = prefixes(model) or Prefixes("", "")
    found = digest(endpoint, model)
    probe = embed(endpoint, model, [known.query + PROBE], SINGLE)
    return ApiEmbedder(endpoint, model, found, probe.shape[1], known)
