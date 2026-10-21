"""Embeddings from an OpenAI-compatible endpoint (plan 018).

The adapter runs against a scripted endpoint (``tests.endpoint``); a real Ollama is
reached only by the opt-in test at the end.
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
import numpy as np
import pytest

from atlassian_offline_mcp.adapters import embedding
from atlassian_offline_mcp.adapters.embedding import (
    BATCH,
    DOCUMENTS,
    MAX_ANSWER_BYTES,
    SINGLE,
    ApiEmbedder,
    Bounds,
    ModelError,
    Prefixes,
    RefusedError,
    connect,
    digest,
    embed,
    endpoint,
)
from atlassian_offline_mcp.cli import main
from atlassian_offline_mcp.domain.settings import DEFAULT_EMBEDDING_URL, SettingsError
from tests.endpoint import (
    DIGEST,
    DIMENSIONS,
    FIXTURES,
    REACHABLE,
    URL,
    Scripted,
    nothing_listening,
    scripted,
    serving,
    tiny,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

QWEN = "qwen3-embedding:0.6b"
NOT_READY = 1
REFUSED = 2
GEMMA = "embeddinggemma:300m"
LISTENED_S = 10
# Seconds that the injected clock moves at each look: three looks pass a deadline of 30.
TICK_S = 11.0
# Reads of a trickled answer before its deadline of 30 seconds is passed, at most.
READS = 4
# Embeddings asked by one query and two probes, each in a single attempt.
ATTEMPTED = 3
# A model pulled in a local Ollama, for the opt-in test.
LIVE = os.environ.get("ATLASSIAN_OFFLINE_MCP_LIVE_MODEL")


def answering(embeddings: Callable[[httpx.Request], httpx.Response]) -> embedding.Endpoint:
    """Open an endpoint whose list of models is the scripted one, and whose embeddings are these."""
    models = Scripted()

    def handle(request: httpx.Request) -> httpx.Response:
        return models(request) if request.url.path == "/api/tags" else embeddings(request)

    return over(handle)


def over(handle: Callable[[httpx.Request], httpx.Response]) -> embedding.Endpoint:
    """Open an endpoint at Ollama's address that answers every request with ``handle``."""
    return endpoint(URL, None, remote_allowed=False, transport=httpx.MockTransport(handle))


def data(*rows: object) -> httpx.Response:
    """Answer embeddings with these items, as Ollama shapes them."""
    return httpx.Response(200, json={"object": "list", "data": list(rows), "model": "tiny"})


def recorded() -> tuple[embedding.Endpoint, list[float]]:
    """Give a scripted endpoint whose waits are recorded, not slept."""
    waits: list[float] = []
    return replace(scripted(), sleep=waits.append), waits


def test_known_prefixes_are_sent_and_none_for_an_unknown_model() -> None:
    """Qwen3's instruction before a query alone; EmbeddingGemma's before both; tiny's none."""
    answers = Scripted({f"{QWEN}": DIGEST, GEMMA: DIGEST, "tiny:latest": DIGEST})
    for model in (QWEN, GEMMA, "tiny"):
        embedder = tiny(answers, model)
        embedder.documents(["undo the payout"])
        embedder.query("revert")
    instruction = (
        "Instruct: Given a web search query, retrieve relevant passages that answer the query"
        "\nQuery:"
    )
    assert answers.asked == [
        [f"{instruction}probe"],
        ["undo the payout"],
        [f"{instruction}revert"],
        ["task: search result | query: probe"],
        ["title: none | text: undo the payout"],
        ["task: search result | query: revert"],
        ["probe"],
        ["undo the payout"],
        ["revert"],
    ]


def test_texts_go_a_batch_at_a_time_and_come_back_in_order() -> None:
    """70 texts make 3 requests; an answer listing its items shuffled is put in order."""
    answers = Scripted()

    def shuffled(request: httpx.Request) -> httpx.Response:
        answer = answers(request)
        if request.url.path != "/v1/embeddings":
            return answer
        content = answer.json()
        content["data"].reverse()
        return httpx.Response(200, json=content)

    embedder = connect(over(shuffled), "tiny")
    texts = [("undo " if number % 2 else "lunch ") + str(number) for number in range(70)]
    vectors = embedder.documents(texts)
    assert [len(asked) for asked in answers.asked] == [1, BATCH, BATCH, 70 - 2 * BATCH]
    alone = [embedder.documents([text])[0] for text in texts]
    assert all(np.allclose(each, one) for each, one in zip(vectors, alone, strict=True))
    assert np.allclose(np.linalg.norm(np.array(vectors), axis=1), 1)


@pytest.mark.parametrize(
    ("answer", "named"),
    [
        (data({"embedding": [1.0, 0.0], "index": 0}), "not one vector of 2 per text"),
        (
            data({"embedding": [1.0, 0.0], "index": 0}, {"embedding": [0.0, 1.0], "index": 0}),
            "not one vector",
        ),
        (
            data({"embedding": [1.0, 0.0], "index": 0}, {"embedding": [1.0], "index": 1}),
            "not embeddings (ValueError)",
        ),
        (
            data({"embedding": ["1.0", "0"], "index": 0}, {"embedding": ["0", "1"], "index": 1}),
            "not one vector",
        ),
        (
            data({"embedding": [0.0, 0.0], "index": 0}, {"embedding": [0.0, 1.0], "index": 1}),
            "of no length",
        ),
        (
            httpx.Response(
                200,
                content=b'{"data": [{"embedding": [NaN, 1], "index": 0},'
                b' {"embedding": [0, 1], "index": 1}]}',
            ),
            "of no length, or not of numbers",
        ),
        (httpx.Response(200, content=b"<html>"), "not embeddings (JSONDecodeError)"),
        (httpx.Response(200, json={"data": "none"}), "not embeddings (TypeError)"),
    ],
)
def test_an_answer_that_is_not_one_vector_per_text_is_refused(
    answer: httpx.Response, named: str
) -> None:
    """Too few items, a repeated index, ragged or non-numeric rows, a zero or NaN vector."""
    opened = answering(lambda _: answer)
    with pytest.raises(ModelError, match=re.escape(named)):
        embed(opened, "tiny", ["one", "two"], SINGLE)


def test_a_row_of_another_length_than_the_probe_s_is_refused() -> None:
    """Every vector of a model has the length its probe had."""
    opened = answering(lambda _: data({"embedding": [1.0, 0.0, 0.0], "index": 0}))
    embedder = ApiEmbedder(opened, "tiny", DIGEST, 2, Prefixes("", ""))
    with pytest.raises(ModelError, match="not one vector of 2 per text"):
        embedder.query("undo")


def test_a_model_of_more_than_8192_dimensions_is_refused() -> None:
    """The probe sets the length, within a bound."""
    opened = answering(lambda _: data({"embedding": [1.0] * 8193, "index": 0}))
    with pytest.raises(ModelError, match="not one vector of 8193"):
        connect(opened, "tiny")


def test_an_answer_past_its_size_is_refused() -> None:
    """Read a mebibyte at a time, given up past MAX_ANSWER_BYTES, never kept whole."""
    reads: list[int] = []

    def endless() -> Iterator[bytes]:
        while True:
            reads.append(1)
            yield b" " * 2**20

    opened = answering(lambda _: httpx.Response(200, content=endless()))
    with pytest.raises(ModelError, match="too large or too slow"):
        embed(opened, "tiny", ["one"], SINGLE)
    assert len(reads) == MAX_ANSWER_BYTES // 2**20 + 1


def test_an_answer_trickled_past_its_deadline_is_given_up() -> None:
    """Each read is checked against the deadline, not each request's timeout alone."""
    reads: list[int] = []

    def trickle() -> Iterator[bytes]:
        while True:
            reads.append(1)
            yield b" "

    opened = answering(lambda _: httpx.Response(200, content=trickle()))
    ticks = iter(range(0, 10**6, int(TICK_S)))
    opened = replace(opened, clock=lambda: float(next(ticks)))
    with pytest.raises(ModelError, match="too large or too slow"):
        embed(opened, "tiny", ["one"], SINGLE)
    assert len(reads) < READS


def test_a_busy_endpoint_is_tried_again_after_waits() -> None:
    """503 then 200: the second attempt answers, after the first wait."""
    opened, waits = recorded()
    answers = Scripted(statuses=[503])
    opened = replace(opened, http=scripted(answers).http)
    assert embed(opened, "tiny", ["undo"], DOCUMENTS).shape == (1, DIMENSIONS)
    assert waits == [1.0]


def test_three_failures_give_up_and_a_refusal_is_not_retried() -> None:
    """Three 503s: refused after waiting 1 then 4 seconds. A 400: refused at once."""
    answers = Scripted(statuses=[503, 503, 503, 400])
    opened, waits = recorded()
    opened = replace(opened, http=scripted(answers).http)
    with pytest.raises(RefusedError, match="answered 503"):
        embed(opened, "tiny", ["undo"], DOCUMENTS)
    assert (len(answers.asked), waits) == (DOCUMENTS.attempts, [1.0, 4.0])
    with pytest.raises(RefusedError, match="answered 400"):
        embed(opened, "tiny", ["undo"], DOCUMENTS)
    assert len(answers.asked) == DOCUMENTS.attempts + 1


def test_a_query_the_probe_and_the_list_of_models_make_one_attempt() -> None:
    """A search falls back to words at once: nothing waits on retries."""
    answers = Scripted()
    embedder = tiny(answers)
    answers.statuses = [503]
    answers.tags = 503
    with pytest.raises(RefusedError):
        embedder.query("undo")
    with pytest.raises(ModelError, match="list of models answered 503"):
        connect(embedder.endpoint, "tiny")
    answers.tags = 200
    answers.statuses = [503]
    with pytest.raises(RefusedError):
        connect(embedder.endpoint, "tiny")
    assert len(answers.asked) == ATTEMPTED


def test_a_redirect_is_not_followed() -> None:
    """A redirect could lead off the machine: it is a failure, and the only request."""
    asked: list[str] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://elsewhere.example/v1/embeddings"})

    with pytest.raises(ModelError, match="answered 307"):
        embed(answering(redirect), "tiny", ["undo"], SINGLE)
    assert asked == [f"{URL}/embeddings"]


def test_the_key_is_sent_only_when_set_and_never_said() -> None:
    """A bearer token from the environment; a refusal names the variable, not the key."""
    headers: list[str | None] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers.get("Authorization"))
        return httpx.Response(401)

    for key in ("a-secret-key", None):
        opened = endpoint(URL, key, remote_allowed=False, transport=httpx.MockTransport(refuse))
        with pytest.raises(ModelError, match=embedding.KEY_VARIABLE) as refused:
            embed(opened, "tiny", ["undo"], SINGLE)
        assert "a-secret-key" not in str(refused.value)
    assert headers == ["Bearer a-secret-key", None]


def test_a_missing_model_and_no_answer_say_what_to_run() -> None:
    """A 404: pull the model, or mind the address. No answer: start Ollama."""
    with pytest.raises(ModelError, match=r"ends in /v1\); with Ollama: ollama pull other"):
        tiny(model="other")

    def down(request: httpx.Request) -> httpx.Response:
        message = "refused"
        raise httpx.ConnectError(message, request=request)

    with pytest.raises(ModelError, match=r"no answer .*\(ConnectError\).*ollama serve"):
        digest(over(down), "tiny")


def test_the_captured_answers_of_ollama_parse() -> None:
    """Ollama's own list of models and embeddings, as captured, read as the adapter reads them."""
    tags = (FIXTURES / "tags.json").read_bytes()
    answer = (FIXTURES / "embeddings.json").read_bytes()
    row = json.loads(tags)["models"][0]

    def captured(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, content=tags)
        return httpx.Response(200, content=answer)

    embedder = connect(over(captured), row["name"])
    assert embedder.digest == row["digest"]
    assert embedder.dimensions == len(json.loads(answer)["data"][0]["embedding"])
    assert np.isclose(np.linalg.norm(embedder.query("undo")), 1)


def test_the_fingerprint_changes_with_anything_that_makes_vectors(
    monkeypatch: MonkeyPatch,
) -> None:
    """The model, its digest, its dimensions, either prefix, the format; not the address."""
    first = tiny()
    changed = [
        replace(first, name="other"),
        replace(first, digest="d2" * 32),
        replace(first, dimensions=8),
        replace(first, prefixes=Prefixes("query: ", "")),
        replace(first, prefixes=Prefixes("", "passage: ")),
    ]
    prints = {each.fingerprint for each in changed}
    assert len(prints) == len(changed)
    assert first.fingerprint not in prints
    elsewhere = endpoint(
        "http://127.0.0.2:8080/v1",
        None,
        remote_allowed=False,
        transport=httpx.MockTransport(Scripted()),
    )
    assert connect(elsewhere, "tiny").fingerprint == first.fingerprint
    before = first.fingerprint
    monkeypatch.setattr(embedding, "FORMAT", embedding.FORMAT + 1)
    assert first.fingerprint != before


def test_the_digest_is_the_model_s_row_s() -> None:
    """Among several models; a name without a tag as ``:latest``; two rows of one name."""
    answers = Scripted({"tiny:latest": "aa", "tiny:small": "bb", "other:latest": "cc"})
    assert digest(scripted(answers), "tiny") == "aa"
    assert digest(scripted(answers), "tiny:small") == "bb"
    assert digest(scripted(answers), "missing") == ""

    def twice(_: httpx.Request) -> httpx.Response:
        row = {"name": "tiny:latest", "model": "tiny:latest", "details": {}}
        rows = [row | {"digest": "bb"}, row | {"digest": "aa"}]
        return httpx.Response(200, json={"models": rows})

    assert digest(over(twice), "tiny") == "aa+bb"


@pytest.mark.parametrize(("status", "found"), [(404, ""), (405, "")])
def test_a_server_without_ollama_s_list_reports_no_digest(status: int, found: str) -> None:
    """Another OpenAI-compatible server: no digest, and the vectors follow the name alone."""
    assert digest(scripted(Scripted(tags=status)), "tiny") == found


def test_an_answer_not_shaped_as_ollama_s_reports_no_digest() -> None:
    """A list of another shape is a server that reports none."""
    assert digest(over(lambda _: httpx.Response(200, json={"data": []})), "tiny") == ""


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_a_list_of_models_that_fails_is_no_empty_digest(status: int) -> None:
    """A passing failure must not change the fingerprint and throw every vector away."""
    with pytest.raises(ModelError, match=f"answered {status}"):
        digest(scripted(Scripted(tags=status)), "tiny")


def test_a_model_that_ollama_serves_from_elsewhere_is_refused_unless_allowed() -> None:
    """A cloud model behind this machine's Ollama sends the text to ollama.com."""

    def cloud(_: httpx.Request) -> httpx.Response:
        row = {"name": "tiny:cloud", "digest": "ee", "remote_host": "https://ollama.com:443"}
        return httpx.Response(200, json={"models": [row]})

    with pytest.raises(ModelError, match="from elsewhere"):
        digest(over(cloud), "tiny:cloud")
    allowed = endpoint(URL, None, remote_allowed=True, transport=httpx.MockTransport(cloud))
    assert digest(allowed, "tiny:cloud") == "ee"


def test_a_digest_that_changes_during_documents_gives_no_vector() -> None:
    """An ``ollama pull`` during a build: no vector of the new weights under the old print."""
    answers = Scripted()
    embedder = tiny(answers)

    def pulled(request: httpx.Request) -> httpx.Response:
        answer = answers(request)
        if request.url.path == "/v1/embeddings":
            answers.models["tiny:latest"] = "d2" * 32
        return answer

    changing = replace(embedder, endpoint=over(pulled))
    with pytest.raises(ModelError, match="changed during this run"):
        changing.documents(["undo"])


def test_a_text_refused_alone_gets_no_vector_and_the_others_theirs() -> None:
    """One text of 32 refused: 31 vectors and None; the batch of one alike."""
    texts = [f"undo {number}" for number in range(BATCH)]
    answers = Scripted(refused={texts[5]})
    vectors = tiny(answers).documents(texts)
    assert [index for index, vector in enumerate(vectors) if vector is None] == [5]
    assert tiny(answers).documents([texts[5]]) == [None]


def test_a_batch_whose_every_text_is_refused_alone_is_the_endpoint_s_fault() -> None:
    """Every text refused, each alone: the endpoint is at fault, not the texts."""
    texts = ["one", "two", "three"]
    with pytest.raises(ModelError, match="for every text of a batch, each alone"):
        tiny(Scripted(refused=set(texts))).documents(texts)


def test_a_remote_endpoint_needs_the_flag_and_https() -> None:
    """Off this machine: refused without the run's word, and over plain http even with it."""
    with pytest.raises(SettingsError, match="not an address of this machine"):
        endpoint("https://embeddings.example/v1", None, remote_allowed=False)
    with pytest.raises(SettingsError, match="https only"):
        endpoint("http://embeddings.example/v1", None, remote_allowed=True)
    with endpoint("https://embeddings.example/v1", None, remote_allowed=True) as opened:
        assert opened.remote_allowed


def test_an_allowed_remote_endpoint_goes_through_the_environment_s_proxy(
    monkeypatch: MonkeyPatch,
) -> None:
    """On a managed network, a proxy may be the way out: a listener here stands for it, never reaching out."""
    asked: list[bytes] = []
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(LISTENED_S)
        port = server.getsockname()[1]
        REACHABLE.add(port)

        def listen() -> None:
            with suppress(TimeoutError), server.accept()[0] as connection:
                asked.append(connection.recv(1024))

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{port}")
        try:
            with (
                endpoint("https://embeddings.example/v1", None, remote_allowed=True) as opened,
                pytest.raises(ModelError),
            ):
                embed(opened, "tiny", ["undo"], Bounds(LISTENED_S, 1))
            thread.join(timeout=LISTENED_S)
        finally:
            REACHABLE.discard(port)
    assert asked
    assert asked[0].startswith(b"CONNECT embeddings.example:443")


def test_the_guard_stops_a_test_reaching_for_the_network() -> None:
    """A port of this machine that no test opened, and a name, are both refused."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with pytest.raises(RuntimeError, match="reached for the network"):
            socket.create_connection(("127.0.0.1", port))
    with pytest.raises(RuntimeError, match="reached for the network"):
        socket.getaddrinfo("example.com", 443)


def check(home: Path, url: str, *arguments: str) -> int:
    """Run ``model check`` with settings naming Qwen3 and an endpoint, from a scratch home."""
    config = home / "config.toml"
    config.write_text(f'model = "{QWEN}"\nembedding_url = "{url}"\n', encoding="utf-8")
    return main(
        ["model", "check", *arguments, "--config", str(config), "--data-dir", str(home / "data")]
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Give a scratch home, for the settings' checks."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_model_check_says_the_dimensions_and_whether_the_prefixes_are_known(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Qwen3's prefixes are known; tiny's are not, and its texts go as they are."""
    with serving(Scripted({QWEN: DIGEST, "tiny:latest": DIGEST})) as url:
        assert check(home, url) == 0
        assert check(home, url, "tiny") == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        f"{QWEN}: {DIMENSIONS} dimensions, from {url}; digest {DIGEST[:12]}; its prefixes known",
        (
            f"tiny: {DIMENSIONS} dimensions, from {url}; digest {DIGEST[:12]};"
            " no prefixes known: texts embedded as they are"
        ),
    ]


def test_model_check_says_what_to_run(home: Path, capsys: CaptureFixture[str]) -> None:
    """A model not pulled: ``ollama pull``. Nothing answering: ``ollama serve``. Exit 1."""
    with serving(Scripted()) as url:
        assert check(home, url) == NOT_READY
    assert f"not ready: {QWEN}: not there" in capsys.readouterr().err
    with nothing_listening() as url:
        assert check(home, url) == NOT_READY
    assert "ollama serve" in capsys.readouterr().err


def test_model_check_refuses_an_endpoint_elsewhere_without_the_flag(
    home: Path, capsys: CaptureFixture[str]
) -> None:
    """Even a probe is text sent away: exit 2, before any connection."""
    assert check(home, "https://embeddings.example/v1") == REFUSED
    assert "refused: embedding_url: not an address of this machine" in capsys.readouterr().err
    assert check(home, "http://embeddings.example/v1", "--allow-remote-embeddings") == REFUSED
    assert "over https only" in capsys.readouterr().err


def test_proxies_are_ignored_on_this_machine(
    home: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """Every proxy set to a port where nothing listens: the endpoint here is still reached."""
    with nothing_listening() as dead:
        proxy = dead.removesuffix("/v1")
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.setenv(name, proxy)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        with serving(Scripted({QWEN: DIGEST})) as url:
            assert check(home, url) == 0
    assert "its prefixes known" in capsys.readouterr().out


@pytest.mark.skipif(LIVE is None, reason="set ATLASSIAN_OFFLINE_MCP_LIVE_MODEL to a pulled model")
def test_a_model_in_a_local_ollama_embeds_by_meaning() -> None:
    """Unit vectors; a paraphrase nearer than another topic; a digest, the same twice."""
    model = str(LIVE)
    REACHABLE.add(httpx.URL(DEFAULT_EMBEDDING_URL).port or 0)
    try:
        with endpoint(DEFAULT_EMBEDDING_URL, None, remote_allowed=False) as opened:
            embedder = connect(opened, model)
            documents = embedder.documents(
                [
                    "To undo a bad release of the payout service, roll back to the previous image.",
                    "The Paris office canteen opens at noon and closes at two.",
                ]
            )
            query = embedder.query("how do I revert a broken deployment of the payments service?")
            again = connect(opened, model).fingerprint
    finally:
        REACHABLE.discard(httpx.URL(DEFAULT_EMBEDDING_URL).port or 0)
    matrix = np.array(documents)
    assert matrix.shape == (2, embedder.dimensions)
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-5)
    near, far = (query @ matrix.T)[0]
    assert near > far
    assert embedder.digest
    assert again == embedder.fingerprint
