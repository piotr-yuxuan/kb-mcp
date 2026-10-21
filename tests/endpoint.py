"""A scripted OpenAI-compatible endpoint that lists its models as Ollama does.

Its model is the tiny model of the tests: words of one concept share an axis, so that a
query without a word of its target still finds it; every other word, and every mark,
shares one axis apart. ``Scripted`` answers ``/v1/embeddings`` and ``/api/tags`` for the
models it is given, records what it is asked, and fails as it is told; it runs behind
``httpx.MockTransport`` (``scripted``), or behind a server on this machine
(``serving``) for the commands and the stdio server. Its answers take their shape from
Ollama's, captured in ``fixtures/ollama``.

``REACHABLE`` holds the ports of this machine that tests have opened: the only places
that the guard of ``conftest`` lets a test connect to.
"""

from __future__ import annotations

import functools
import json
import re
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING, Any, override
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import httpx
import numpy as np

from atlassian_offline_mcp.adapters.embedding import Endpoint, connect, endpoint

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from atlassian_offline_mcp.adapters.embedding import ApiEmbedder

REACHABLE: set[int] = set()
FIXTURES = Path(__file__).parent / "fixtures" / "ollama"
URL = "http://127.0.0.1:11434/v1"
DIMENSIONS = 16
# Words of one concept mean the same to the tiny model; each concept has its own axis.
CONCEPTS = (
    ("rollback", "revert", "undo", "restore"),
    ("payout", "payouts", "seller", "sellers"),
    ("deploy", "deployment", "release", "rollout"),
    ("holiday", "holidays", "leave", "vacation"),
    ("canteen", "lunch", "cafeteria", "meal"),
    ("alpha",),
    ("beta",),
)
AXES = {word: axis for axis, concept in enumerate(CONCEPTS) for word in concept}
OTHER_AXIS = 14
DIGEST = "d1" * 32


def vector(text: str) -> list[float]:
    """Give the tiny model's vector of a text: the mean of its tokens' axes, not scaled."""
    tokens = re.findall(r"\w+|[^\w\s]+", text.lower()) or [""]
    rows = np.zeros(DIMENSIONS)
    for token in tokens:
        rows[AXES.get(token, OTHER_AXIS)] += 1
    return (rows / len(tokens)).tolist()


def listed(model: str) -> str:
    """Name a model as Ollama resolves it, from its documented behaviour.

    In lower case, with its tag (``latest`` when none is given), and without the default
    registry (``registry.ollama.ai`` or ``ollama.com``) and namespace (``library``).
    """
    name = model.lower() if ":" in model.lower().rpartition("/")[2] else f"{model.lower()}:latest"
    for default in ("registry.ollama.ai/", "ollama.com/", "library/"):
        name = name.removeprefix(default)
    return name


@dataclass
class Scripted:
    """An OpenAI-compatible endpoint with Ollama's list of models, answering as told."""

    models: dict[str, str] = field(default_factory=lambda: {"tiny:latest": DIGEST})  # each
    # model as Ollama lists it, and its digest
    statuses: list[int] = field(default_factory=list)  # the next embeddings answers' status
    refused: set[str] = field(default_factory=set)  # texts answered 400, alone or not
    tags: int = 200  # the status of the list of models
    asked: list[list[str]] = field(default_factory=list)  # the input of each embedding

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Answer one request as Ollama would, or as told."""
        routes = {("GET", "/api/tags"): self.list_models, ("POST", "/v1/embeddings"): self.embed}
        route = routes.get((request.method, request.url.path))
        return httpx.Response(404) if route is None else route(request)

    def list_models(self, _: httpx.Request) -> httpx.Response:
        """List the models with their digests, in rows shaped as Ollama's."""
        if self.tags != httpx.codes.OK:
            return httpx.Response(self.tags)
        template = json.loads((FIXTURES / "tags.json").read_text(encoding="utf-8"))
        rows = [
            template["models"][0] | {"name": name, "model": name, "digest": digest}
            for name, digest in self.models.items()
        ]
        return httpx.Response(200, json={"models": rows})

    def embed(self, request: httpx.Request) -> httpx.Response:
        """Embed with the tiny model, or fail as told, in an answer shaped as Ollama's."""
        asked = json.loads(request.content)
        self.asked.append(asked["input"])
        if self.statuses:
            return httpx.Response(self.statuses.pop(0))
        if listed(asked["model"]) not in {listed(name) for name in self.models}:
            message = f'model "{asked["model"]}" not found, try pulling it first'
            return httpx.Response(404, json={"error": {"message": message}})
        if self.refused & set(asked["input"]):
            return httpx.Response(400, json={"error": {"message": "refused"}})
        answer = json.loads((FIXTURES / "embeddings.json").read_text(encoding="utf-8"))
        answer["model"] = asked["model"]
        answer["data"] = [
            {"object": "embedding", "embedding": vector(text), "index": index}
            for index, text in enumerate(asked["input"])
        ]
        return httpx.Response(200, json=answer)


def scripted(answers: Scripted | None = None, *, remote_allowed: bool = False) -> Endpoint:
    """Open an endpoint at Ollama's address whose answers are scripted, not the network's."""
    return endpoint(
        URL,
        None,
        remote_allowed=remote_allowed,
        transport=httpx.MockTransport(answers or Scripted()),
    )


def tiny(answers: Scripted | None = None, model: str = "tiny") -> ApiEmbedder:
    """Connect to the tiny model, as scripted."""
    return connect(scripted(answers), model)


def connector(answers: Scripted | None = None) -> Callable[[str], ApiEmbedder]:
    """Give what connects a search by meaning to the models, as scripted."""
    return functools.partial(connect, scripted(answers))


class Quiet(WSGIRequestHandler):
    """A request handler that keeps the test's output clean."""

    @override
    def log_message(self, *_: object) -> None:
        """Say nothing of each request."""


class Threaded(ThreadingMixIn, WSGIServer):
    """A server that answers requests at once, each in a thread of its own."""

    daemon_threads = True


@contextmanager
def serving(answers: Scripted) -> Iterator[str]:
    """Serve the scripted answers on a port of this machine; give the API's address."""

    def application(environ: dict[str, Any], start_response: Callable[..., object]) -> list[bytes]:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        request = httpx.Request(
            environ["REQUEST_METHOD"],
            f"http://127.0.0.1{environ['PATH_INFO']}",
            content=environ["wsgi.input"].read(length),
        )
        response = answers(request)
        headers = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(response.content))),
        ]
        start_response(f"{response.status_code} {response.reason_phrase}", headers)
        return [response.content]

    server = make_server("127.0.0.1", 0, application, Threaded, Quiet)
    port = server.server_port
    REACHABLE.add(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        REACHABLE.discard(port)


@contextmanager
def nothing_listening() -> Iterator[str]:
    """Give the API's address at a port of this machine where nothing listens.

    The port is free when given, and reachable for the guard: a connection there is
    refused, as when Ollama is not started.
    """
    with socket.create_server(("127.0.0.1", 0)) as reserved:
        port = reserved.getsockname()[1]
    REACHABLE.add(port)
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        REACHABLE.discard(port)
