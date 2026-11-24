"""Telemetry: the OpenTelemetry SDK, exporting a run's traces, metrics and logs over OTLP.

This module alone knows the SDK, imported only for a run with an endpoint.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from contextlib import contextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING, cast, override
from urllib.parse import urlsplit

import requests
import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.attributes.service_attributes import (
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_VERSION,
)

from kb_mcp.kernel.names import PROGRAM
from kb_mcp.observability import SDK

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# How long a run waits, at its start, to connect to the endpoint, in seconds.
PROBE_S = 0.5
# How long an export waits for the endpoint's answer, in seconds.
TIMEOUT_S = 5.0
# How long the providers have, in all, to shut down at a run's end, in seconds: a
# refused export would retry until its own deadline, each signal's in turn.
LIMIT_S = 5.0
# How often metrics are exported while a run lasts, in milliseconds.
METRICS_EVERY_MS = 15_000
# The fields of an event that an exported record holds as fields of its own: its body,
# its severity, its scope and its time.
NATIVE = frozenset({"event", "level", "logger", "timestamp"})
# What structlog adds to the record it hands the standard library, for its formatter.
STRUCTLOG_EXTRA = frozenset({"_logger", "_name"})


class Direct(requests.Session):
    """A session that takes nothing from the environment: no proxy, netrc, nor bundle."""

    def __init__(self) -> None:
        """Make a session that trusts no variable of the environment."""
        super().__init__()
        self.trust_env = False


class Exported(LoggingHandler):
    """Export each record from INFO, but the SDK's own: its event or message, its fields beside.

    Its fields are redacted, but ``NATIVE`` and the standard library's; ``command`` is one.
    """

    def __init__(
        self, provider: LoggerProvider, command: str, redact: Callable[[object], object]
    ) -> None:
        """Export through ``provider`` the records of a run of ``command``, by ``redact``."""
        super().__init__(logging.INFO, provider)
        self.command, self.redact = command, redact
        self.addFilter(lambda record: record.name.partition(".")[0] != SDK)

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Export a copy of the record, its event as its message; the record stays as it is."""
        event = isinstance(record.msg, dict) and "event" in record.msg
        fields = record.msg if event else {"event": record.getMessage()}
        standard = {key: value for key, value in vars(record).items() if key not in STRUCTLOG_EXTRA}
        copied = {
            **{key: value for key, value in fields.items() if key not in NATIVE},
            **standard,
            "msg": fields["event"],
            "args": (),
            "command": self.command,
        }
        super().emit(logging.makeLogRecord(cast("dict[str, object]", self.redact(copied))))


class Stopping(threading.Thread):
    """A provider shutting down, in a thread that the interpreter does not wait for."""

    def __init__(self, provider: TracerProvider | MeterProvider | LoggerProvider) -> None:
        """Shut ``provider`` down once started."""
        super().__init__(daemon=True)
        self.provider = provider
        self.stopped = False

    @override
    def run(self) -> None:
        """Shut the provider down, noting in ``stopped`` that it did; what it raises, at DEBUG."""
        log = structlog.get_logger()
        try:
            self.provider.shutdown()
        except Exception:
            log.debug(
                "telemetry.shutdown_failed", provider=type(self.provider).__name__, exc_info=True
            )
        else:
            self.stopped = True


@contextmanager
def exporting(
    endpoint: str, run: str, command: str, redact: Callable[[object], object]
) -> Iterator[None]:
    """Export the traces, metrics and logs of a run of ``command``, id ``run``, to ``endpoint``.

    Each log record is exported as ``redact`` returns it.

    Raises OSError when the endpoint takes no connection, installing nothing. On leaving,
    ``LIMIT_S`` at most, then one ``telemetry.undelivered`` and the SDK silenced.
    """
    parts = urlsplit(endpoint)
    socket.create_connection((parts.hostname, parts.port), PROBE_S).close()
    resource = Resource(
        {SERVICE_NAME: PROGRAM, SERVICE_VERSION: version(PROGRAM), SERVICE_INSTANCE_ID: run}
    )
    tracers = TracerProvider(resource=resource, shutdown_on_exit=False)
    tracers.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(f"{endpoint}/v1/traces", timeout=TIMEOUT_S, session=Direct())
        )
    )
    meters = MeterProvider(
        [
            PeriodicExportingMetricReader(
                OTLPMetricExporter(f"{endpoint}/v1/metrics", timeout=TIMEOUT_S, session=Direct()),
                export_interval_millis=METRICS_EVERY_MS,
            )
        ],
        resource=resource,
        shutdown_on_exit=False,
    )
    loggers = LoggerProvider(resource=resource, shutdown_on_exit=False)
    loggers.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(f"{endpoint}/v1/logs", timeout=TIMEOUT_S, session=Direct())
        )
    )
    trace.set_tracer_provider(tracers)
    metrics.set_meter_provider(meters)
    root, sink = logging.getLogger(), Exported(loggers, command, redact)
    root.addHandler(sink)
    try:
        yield
    finally:
        root.removeHandler(sink)
        stopping = [Stopping(provider) for provider in (tracers, meters, loggers)]
        deadline = time.monotonic() + LIMIT_S
        reason = f"not all sent within {LIMIT_S:g} s"
        for thread in stopping:
            thread.start()
        try:
            for thread in stopping:
                thread.join(max(deadline - time.monotonic(), 0))
        except KeyboardInterrupt:
            reason = "interrupted"
        if not all(thread.stopped for thread in stopping):
            logging.getLogger(SDK).setLevel(logging.CRITICAL + 1)
            structlog.get_logger().warning(
                "telemetry.undelivered", endpoint=endpoint, reason=reason
            )
