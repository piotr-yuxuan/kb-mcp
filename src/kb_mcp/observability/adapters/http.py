"""Requests to other programs, observed by OpenTelemetry's semantic conventions.

``ObservedTransport`` is the transport of the clients that reach the site and the embeddings
endpoint: each request that it sends is a span, a duration and an event, by the HTTP
conventions. ``client_span`` traces and measures any operation of a client, such as an
embedding, made of such requests. Both use the OpenTelemetry API alone, which does
nothing until the SDK is behind it.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, override

import httpx
import structlog
from opentelemetry import metrics, trace
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
)
from opentelemetry.semconv.attributes.server_attributes import SERVER_ADDRESS, SERVER_PORT
from opentelemetry.semconv.attributes.url_attributes import URL_FULL
from opentelemetry.semconv.metrics.http_metrics import HTTP_CLIENT_REQUEST_DURATION
from opentelemetry.trace import SpanKind, StatusCode

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from opentelemetry.metrics import Histogram
    from opentelemetry.util.types import AttributeValue

HTTP_PORT, HTTPS_PORT = 80, 443
TRACER = trace.get_tracer(__name__)
# The buckets of a request's duration, in seconds, that the HTTP conventions advise.
BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10)
# How long each request took, to its answer's headers, as the HTTP conventions measure it.
REQUEST_DURATION = metrics.get_meter(__name__).create_histogram(
    HTTP_CLIENT_REQUEST_DURATION,
    unit="s",
    description="Duration of HTTP client requests.",
    explicit_bucket_boundaries_advisory=BUCKETS_S,
)


def server(url: httpx.URL) -> dict[str, AttributeValue]:
    """Give the conventions' ``server.address`` and ``server.port`` of a URL.

    A URL that names no port has its scheme's: http's, or else https's.
    """
    return {
        SERVER_ADDRESS: url.host,
        SERVER_PORT: url.port or (HTTP_PORT if url.scheme == "http" else HTTPS_PORT),
    }


@contextmanager
def client_span(
    name: str,
    duration: Histogram,
    measured: dict[str, AttributeValue],
    traced: Mapping[str, AttributeValue],
) -> Iterator[None]:
    """Trace an operation of a client as a span ``name``, and record its seconds in ``duration``.

    The span holds ``measured`` and ``traced``; the duration ``measured`` alone, whose
    values must be few. Both take ``measured`` as the operation leaves it, since it may
    add to it, such as the status of an answer. An exception that the operation raises
    sets ``error.type`` to its class, qualified by its module, as the conventions have
    it; with ``error.type`` set either way, the span's status is an error. The
    exception itself is not recorded: its message may hold what a span must not, such
    as a token in a URL's query.
    """
    began = time.perf_counter()
    with TRACER.start_as_current_span(
        name,
        kind=SpanKind.CLIENT,
        attributes={**measured, **traced},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield
        except Exception as error:
            measured[ERROR_TYPE] = f"{type(error).__module__}.{type(error).__qualname__}"
            raise
        finally:
            span.set_attributes(measured)
            if ERROR_TYPE in measured:
                span.set_status(StatusCode.ERROR)
            duration.record(time.perf_counter() - began, measured)


class ObservedTransport(httpx.BaseTransport):
    """A transport that observes each request it sends, a redirect's included.

    Each is a span named after its method, by the HTTP conventions, until its answer's
    headers; its duration, in ``http.client.request.duration``; and the event
    ``http.<method>``, such as ``http.get``, at DEBUG, with its URL, its status or its
    error, and its seconds. An answer of status 400 or above is an error, its status its
    ``error.type``. A URL is shown without a user or a password, and with its query on
    ``host`` alone: elsewhere, such as on the media host that a file redirects to, the
    query may hold a token. No header is shown, and no trace context sent.

    The requests go through ``network``, a client of its own, so that httpx chooses
    their transport as it would, the environment's proxies included, which it ignores
    for a client given a transport.
    """

    def __init__(self, network: httpx.Client, host: str) -> None:
        """Send through ``network``; show the query of a request to ``host`` alone."""
        self.network = network
        self.host = host

    @override
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Send one request, observed; give its answer, whose body is not read yet."""
        url = request.url
        query = url.query if url.host == self.host else b""
        shown = str(url.copy_with(userinfo=b"", query=query or None))
        measured = {HTTP_REQUEST_METHOD: request.method, **server(url)}
        began = time.perf_counter()
        try:
            with client_span(request.method, REQUEST_DURATION, measured, {URL_FULL: shown}):
                response = self.network.send(request, stream=True)
                measured[HTTP_RESPONSE_STATUS_CODE] = response.status_code
                if response.is_error:
                    measured[ERROR_TYPE] = str(response.status_code)
        finally:
            structlog.get_logger().debug(
                f"http.{request.method.lower()}",
                url=shown,
                status=measured.get(HTTP_RESPONSE_STATUS_CODE),
                error=measured.get(ERROR_TYPE),
                seconds=round(time.perf_counter() - began, 3),
            )
        return response

    @override
    def close(self) -> None:
        """Close the client of the network."""
        self.network.close()
