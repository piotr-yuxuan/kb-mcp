"""A scripted collector of OTLP over HTTP, on a port of this machine, as LGTM's would be.

``Collector`` keeps each request that it is sent, by path and body, and answers it as
an OpenTelemetry collector does, or never, as told; it decodes what it kept with the
protobuf messages of ``opentelemetry-proto``. ``collecting`` serves it on a port of this
machine, which the guard of ``conftest`` lets a test reach.
"""

from __future__ import annotations

import functools
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, override

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from tests.endpoint import REACHABLE

if TYPE_CHECKING:
    import socket
    import socketserver
    from collections.abc import Iterable, Iterator

    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord
    from opentelemetry.proto.metrics.v1.metrics_pb2 import Metric
    from opentelemetry.proto.trace.v1.trace_pb2 import Span

# Where OTLP over HTTP sends each signal, under the endpoint.
TRACES, METRICS, LOGS = "/v1/traces", "/v1/metrics", "/v1/logs"


def plain(value: AnyValue) -> object:
    """Give an attribute's value as Python has it, a list's or a map's as protobuf's."""
    kind = value.WhichOneof("value")
    return None if kind is None else getattr(value, kind)


def attributes(pairs: Iterable[KeyValue]) -> dict[str, object]:
    """Give attributes by their keys, each value as ``plain`` gives it."""
    return {pair.key: plain(pair.value) for pair in pairs}


@dataclass
class Collector:
    """A collector that keeps what it is sent, and answers each export, unless ``silent``.

    A silent one reads each request whole, then holds its connection open, answering
    nothing, until it is stopped.
    """

    silent: bool = False
    sent: list[tuple[str, bytes]] = field(default_factory=list)  # each request's path, body
    stopped: threading.Event = field(default_factory=threading.Event)

    def bodies(self, path: str) -> list[bytes]:
        """Give the body of each request sent to ``path``, in order."""
        return [body for sent_to, body in self.sent if sent_to == path]

    def resources(self) -> list[dict[str, object]]:
        """Give the attributes of the resource of everything sent, signal by signal."""
        found = [
            *(
                spans.resource
                for body in self.bodies(TRACES)
                for spans in ExportTraceServiceRequest.FromString(body).resource_spans
            ),
            *(
                measured.resource
                for body in self.bodies(METRICS)
                for measured in ExportMetricsServiceRequest.FromString(body).resource_metrics
            ),
            *(
                logs.resource
                for body in self.bodies(LOGS)
                for logs in ExportLogsServiceRequest.FromString(body).resource_logs
            ),
        ]
        return [attributes(resource.attributes) for resource in found]

    def spans(self) -> list[Span]:
        """Give every span sent, in order."""
        return [
            span
            for body in self.bodies(TRACES)
            for spans in ExportTraceServiceRequest.FromString(body).resource_spans
            for scoped in spans.scope_spans
            for span in scoped.spans
        ]

    def metrics(self) -> list[Metric]:
        """Give every metric sent, in order."""
        return [
            metric
            for body in self.bodies(METRICS)
            for measured in ExportMetricsServiceRequest.FromString(body).resource_metrics
            for scoped in measured.scope_metrics
            for metric in scoped.metrics
        ]

    def records(self) -> list[tuple[str, LogRecord]]:
        """Give every log record sent, with the name of its scope, its logger's, in order."""
        return [
            (scoped.scope.name, record)
            for body in self.bodies(LOGS)
            for logs in ExportLogsServiceRequest.FromString(body).resource_logs
            for scoped in logs.scope_logs
            for record in scoped.log_records
        ]


class Receiving(BaseHTTPRequestHandler):
    """A request handler that hands each export to its collector, saying nothing itself."""

    def __init__(
        self,
        collector: Collector,
        request: socket.socket,
        address: tuple[str, int],
        server: socketserver.BaseServer,
    ) -> None:
        """Hand what is sent to ``collector``, then handle the request as the server's."""
        self.collector = collector
        super().__init__(request, address, server)

    def do_POST(self) -> None:
        """Keep the export, then answer it as a collector does, or never."""
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.collector.sent.append((self.path, body))
        if self.collector.silent:
            self.collector.stopped.wait()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    @override
    def log_message(self, *_: object) -> None:
        """Say nothing of each request."""


@contextmanager
def collecting(collector: Collector) -> Iterator[str]:
    """Serve ``collector`` on a port of this machine; give the endpoint, as the settings take it."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Receiving, collector))
    server.daemon_threads = True
    port = server.server_port
    REACHABLE.add(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        collector.stopped.set()
        server.shutdown()
        server.server_close()
        REACHABLE.discard(port)
