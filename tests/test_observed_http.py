"""Requests observed: a span, a duration and an event each, by OpenTelemetry's conventions.

Plan 016: the site's client, over the scripted site, reports every request it sends,
a redirect's included, and never a header nor another host's query; so does the
embeddings endpoint's, over the scripted endpoint, whose every embedding is a span of
its own, by the GenAI conventions. What is traced and measured is read from the SDK's
in-memory exporters.
"""

from __future__ import annotations

import socket
import threading
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
import pytest
from opentelemetry.trace import SpanKind, StatusCode
from structlog.testing import capture_logs

from kb_mcp.kernel.endpoint import EMBEDDINGS
from kb_mcp.search.adapters.embedding import (
    DOCUMENTS,
    SINGLE,
    RefusedError,
    connect,
    embed,
)
from kb_mcp.search.adapters.model_api import endpoint
from kb_mcp.sources.atlassian.adapters import http
from kb_mcp.sources.atlassian.adapters.http import (
    RETRIES,
    Request,
    Site,
    SiteError,
)
from tests.endpoint import REACHABLE, URL, Scripted, scripted
from tests.test_download import PICTURE, SITE, FakeSite

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from _pytest.monkeypatch import MonkeyPatch

    from tests.conftest import InMemory

HOST = httpx.URL(SITE).host
# The buckets that the HTTP conventions advise for a request's duration, in seconds.
BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10)
DOWNLOAD = "/wiki/rest/api/content/1001/child/attachment/att1/download"
MEDIA = "https://api.media.atlassian.com/file/abc/binary"
# What a media redirect's query carries: a token, which grants the file.
GRANT = "media-grant-sentinel-51f0"
COOKIE = "cookie-sentinel-8c2d"
CREDENTIAL = "credential-sentinel-07b9"
KEY = "key-sentinel-3e6a"
# The buckets that the GenAI conventions advise for an operation's duration, in seconds.
OPERATION_BUCKETS_S = (
    *(0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64),
    *(1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92),
)
# What the GenAI conventions have an embedding by the tiny model at the scripted
# endpoint say: an OpenAI-compatible API, as the client knows it, on this machine.
EMBEDDING = {
    "gen_ai.operation.name": "embeddings",
    "gen_ai.provider.name": "openai",
    "gen_ai.request.model": "tiny",
    "server.address": "127.0.0.1",
    "server.port": 11434,
}
LISTENED_S = 10


def site(
    handle: Callable[[httpx.Request], httpx.Response],
    cookies: Iterable[Mapping[str, str]] = (),
    hooks: Iterable[Callable[[httpx.Request], None]] = (),
) -> Site:
    """Give the site, through its own client, answered by ``handle``, never waiting."""
    client = http.client(SITE, cookies, hooks, transport=httpx.MockTransport(handle))
    return Site(client, sleep=lambda _: None)


def test_a_request_is_a_client_span_named_after_its_method_by_the_http_conventions(
    telemetry: InMemory,
) -> None:
    """Its method, server, full URL with its query on the site, status; no trace context."""
    sent: list[httpx.Request] = []
    fake = FakeSite()
    reader = site(lambda request: sent.append(request) or fake.handle(request))
    reader.json(Request(path="/wiki/api/v2/spaces", params={"keys": "MFS"}))
    (span,) = telemetry.spans.get_finished_spans()
    assert (span.name, span.kind) == ("GET", SpanKind.CLIENT)
    assert dict(span.attributes or {}) == {
        "http.request.method": "GET",
        "server.address": HOST,
        "server.port": 443,
        "url.full": f"{SITE}/wiki/api/v2/spaces?keys=MFS",
        "http.response.status_code": 200,
    }
    assert span.status.status_code == StatusCode.UNSET
    assert not any(name.lower() in {"traceparent", "tracestate"} for name in sent[0].headers)


def test_a_request_s_duration_is_measured_by_its_bounded_attributes_alone(
    telemetry: InMemory,
) -> None:
    """In seconds, in the buckets that the conventions advise, without the URL."""
    reader = site(FakeSite().handle)
    reader.json(Request(path="/wiki/api/v2/spaces", params={"keys": "MFS"}))
    duration = telemetry.measured()["http.client.request.duration"]
    assert duration.unit == "s"
    (point,) = duration.data.data_points
    assert dict(point.attributes or {}) == {
        "http.request.method": "GET",
        "server.address": HOST,
        "server.port": 443,
        "http.response.status_code": 200,
    }
    assert point.count == 1
    assert tuple(point.explicit_bounds) == BUCKETS_S


def test_a_file_s_redirect_is_a_request_of_its_own_whose_query_elsewhere_is_never_shown(
    telemetry: InMemory,
) -> None:
    """The media host's query holds a token; no header is shown, cookie nor credential.

    Each request writes ``http.get`` at DEBUG: its URL as its span shows it, its status,
    no error, and its seconds.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == HOST:
            return httpx.Response(302, headers={"location": f"{MEDIA}?token={GRANT}"})
        return httpx.Response(200, content=PICTURE, headers={"set-cookie": f"media={COOKIE}"})

    cookie = {"name": "tenant.session.token", "value": COOKIE, "domain": HOST, "path": "/"}

    def authorise(request: httpx.Request) -> None:
        request.headers["Authorization"] = f"Basic {CREDENTIAL}"

    reader = site(handle, [cookie], [authorise])
    with capture_logs() as events:
        assert reader.file(f"{DOWNLOAD}?version=2", len(PICTURE)) == PICTURE
    redirect, media = telemetry.spans.get_finished_spans()
    assert dict(redirect.attributes or {})["url.full"] == f"{SITE}{DOWNLOAD}?version=2"
    assert dict(redirect.attributes or {})["http.response.status_code"] == httpx.codes.FOUND
    assert redirect.status.status_code == StatusCode.UNSET
    assert dict(media.attributes or {}) == {
        "http.request.method": "GET",
        "server.address": "api.media.atlassian.com",
        "server.port": 443,
        "url.full": MEDIA,
        "http.response.status_code": 200,
    }
    gets = [event for event in events if event["event"] == "http.get"]
    assert [(event["log_level"], event["url"], event["status"]) for event in gets] == [
        ("debug", f"{SITE}{DOWNLOAD}?version=2", 302),
        ("debug", MEDIA, 200),
    ]
    assert all(event["error"] is None and event["seconds"] >= 0 for event in gets)
    shown = f"{events} {[dict(span.attributes or {}) for span in (redirect, media)]}"
    for secret in (GRANT, COOKIE, CREDENTIAL):
        assert secret not in shown


def test_each_attempt_is_a_span_of_its_own_an_answer_of_400_or_more_an_error(
    telemetry: InMemory,
) -> None:
    """Throttled then answered: the 429 is an error whose type is its status; then a 200."""
    answers = iter([httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(200)])
    reader = site(lambda _: next(answers))
    with capture_logs() as events:
        reader.get(Request(path="/wiki/api/v2/spaces"), 10)
    throttled, answered = telemetry.spans.get_finished_spans()
    status = dict(throttled.attributes or {})["http.response.status_code"]
    assert status == httpx.codes.TOO_MANY_REQUESTS
    assert dict(throttled.attributes or {})["error.type"] == "429"
    assert throttled.status.status_code == StatusCode.ERROR
    assert "error.type" not in dict(answered.attributes or {})
    assert answered.status.status_code == StatusCode.UNSET
    gets = [event for event in events if event["event"] == "http.get"]
    assert [(event["status"], event["error"]) for event in gets] == [(429, "429"), (200, None)]
    points = telemetry.measured()["http.client.request.duration"].data.data_points
    assert sorted(dict(point.attributes or {}).get("error.type", "") for point in points) == [
        "",
        "429",
    ]


def test_a_lost_connection_is_an_error_named_by_its_class_never_its_message(
    telemetry: InMemory,
) -> None:
    """Every attempt is an error span of no status, typed as the exception's class.

    The message, which may name what a span must not, is recorded nowhere.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        message = "connection to secret.example refused"
        raise httpx.ConnectError(message, request=request)

    reader = site(handle)
    with capture_logs() as events, pytest.raises(SiteError, match=r"^ConnectError$"):
        reader.json(Request(path="/wiki/api/v2/spaces"))
    spans = telemetry.spans.get_finished_spans()
    assert len(spans) == RETRIES + 1
    for span in spans:
        attributes = dict(span.attributes or {})
        assert attributes["error.type"] == "httpx.ConnectError"
        assert "http.response.status_code" not in attributes
        assert span.status.status_code == StatusCode.ERROR
        assert span.events == ()
        assert "secret.example" not in f"{attributes} {span.status.description}"
    gets = [event for event in events if event["event"] == "http.get"]
    assert [(event["status"], event["error"]) for event in gets] == [
        (None, "httpx.ConnectError")
    ] * (RETRIES + 1)
    points = telemetry.measured()["http.client.request.duration"].data.data_points
    (point,) = points
    assert dict(point.attributes or {})["error.type"] == "httpx.ConnectError"
    assert point.count == RETRIES + 1


def test_the_site_s_client_still_goes_through_the_environment_s_proxy(
    monkeypatch: MonkeyPatch,
) -> None:
    """Observed, the requests take the way out that httpx would: on a managed network, a proxy.

    httpx takes no proxy from the environment for a client given a transport; a
    listener here stands for the proxy, never reaching out.
    """
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
            with http.client(SITE, ()) as client, pytest.raises(httpx.HTTPError):
                client.get("/wiki/api/v2/spaces")
            thread.join(timeout=LISTENED_S)
        finally:
            REACHABLE.discard(port)
    assert asked
    assert asked[0].startswith(f"CONNECT {HOST}:443".encode())


def test_the_embeddings_endpoint_s_requests_are_observed_alike_its_key_never_shown(
    telemetry: InMemory,
) -> None:
    """Connecting lists the models, then embeds a probe: a GET, then a POST, each a span.

    The POST writes ``http.post``; the key, a bearer token, is in no span nor event.
    """
    opened = endpoint(
        URL, KEY, EMBEDDINGS, remote_allowed=False, transport=httpx.MockTransport(Scripted())
    )
    with opened, capture_logs() as events:
        connect(opened, "tiny")
    spans = telemetry.spans.get_finished_spans()
    requests = [span for span in spans if "http.request.method" in dict(span.attributes or {})]
    assert [(span.name, span.kind) for span in requests] == [
        ("GET", SpanKind.CLIENT),
        ("POST", SpanKind.CLIENT),
    ]
    listed, embedded = (dict(span.attributes or {}) for span in requests)
    here = {"server.address": "127.0.0.1", "server.port": 11434, "http.response.status_code": 200}
    assert listed == {
        "http.request.method": "GET",
        "url.full": "http://127.0.0.1:11434/api/tags",
        **here,
    }
    assert embedded == {
        "http.request.method": "POST",
        "url.full": "http://127.0.0.1:11434/v1/embeddings",
        **here,
    }
    said = [(event["event"], event["url"]) for event in events if "url" in event]
    assert said == [
        ("http.get", "http://127.0.0.1:11434/api/tags"),
        ("http.post", "http://127.0.0.1:11434/v1/embeddings"),
    ]
    assert KEY not in f"{events} {[dict(span.attributes or {}) for span in spans]}"


def test_an_embedding_is_a_client_span_by_the_genai_conventions_holding_its_attempts(
    telemetry: InMemory,
) -> None:
    """Named after the operation and the model; a busy endpoint's 503, then the answer.

    Its duration is measured by the same attributes, in the buckets that they advise.
    """
    opened = replace(scripted(Scripted(statuses=[503])), sleep=lambda _: None)
    with opened:
        embed(opened, "tiny", ["undo"], DOCUMENTS)
    busy, answered, embedding = telemetry.spans.get_finished_spans()
    assert (embedding.name, embedding.kind) == ("embeddings tiny", SpanKind.CLIENT)
    assert dict(embedding.attributes or {}) == {**EMBEDDING, "gen_ai.usage.input_tokens": 21}
    assert embedding.status.status_code == StatusCode.UNSET
    statuses = [
        dict(span.attributes or {})["http.response.status_code"] for span in (busy, answered)
    ]
    assert statuses == [503, 200]
    for attempt in (busy, answered):
        assert attempt.parent is not None
        assert attempt.parent.span_id == embedding.context.span_id
    duration = telemetry.measured()["gen_ai.client.operation.duration"]
    assert duration.unit == "s"
    (point,) = duration.data.data_points
    assert dict(point.attributes or {}) == EMBEDDING
    assert point.count == 1
    assert tuple(point.explicit_bounds) == OPERATION_BUCKETS_S


def test_an_embedding_that_fails_is_an_error_typed_as_its_exception(telemetry: InMemory) -> None:
    """Refused, its text sent back with 400: the class qualified by its module; its POST's, 400."""
    opened = scripted(Scripted(statuses=[400]))
    with opened, pytest.raises(RefusedError):
        embed(opened, "tiny", ["undo"], SINGLE)
    refused, embedding = telemetry.spans.get_finished_spans()
    failed = "kb_mcp.search.adapters.embedding.RefusedError"
    assert dict(embedding.attributes or {}) == {**EMBEDDING, "error.type": failed}
    assert embedding.status.status_code == StatusCode.ERROR
    assert dict(refused.attributes or {})["error.type"] == "400"
    (point,) = telemetry.measured()["gen_ai.client.operation.duration"].data.data_points
    assert dict(point.attributes or {}) == {**EMBEDDING, "error.type": failed}
