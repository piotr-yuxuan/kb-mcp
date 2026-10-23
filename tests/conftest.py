"""Every test runs without the network, the settings' own environment or the user's home.

An audit hook refuses any connection, and any name looked up, other than a loopback
address and a port in ``tests.endpoint.REACHABLE``, so that no test reaches the network,
or a real Ollama on this machine, by mistake. The settings' variables of the user's
environment, and OpenTelemetry's, are removed for each test, which sets those it needs.
Each test has a scratch home, so that a run's log file goes to a scratch log folder.
A test that reads what is traced and measured asks for ``telemetry``: the SDK's
providers, over in-memory exporters, put behind the API once a session.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider, _Gauge
from opentelemetry.sdk.metrics.export import AggregationTemporality, InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.endpoint import REACHABLE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from _pytest.tmpdir import TempPathFactory
    from opentelemetry.sdk.metrics.export import Metric

PREFIX = "ATLASSIAN_OFFLINE_MCP_"
# OpenTelemetry's variables, two of which the settings read, and its SDK others.
OTEL = "OTEL_"


def guard(event: str, arguments: tuple[object, ...]) -> None:
    """Refuse a connection or a look-up other than to a port that a test opened here."""
    if event == "socket.connect":
        place = arguments[1]
    elif event == "socket.getaddrinfo":
        place = arguments[:2]
    else:
        return
    if not isinstance(place, tuple):
        return  # a Unix socket's path: not the network
    try:
        here = ipaddress.ip_address(str(place[0])).is_loopback
    except ValueError:
        here = False
    if not here or place[1] not in REACHABLE:
        message = f"a test reached for the network: {event} {place!r}"
        raise RuntimeError(message)


sys.addaudithook(guard)


@pytest.fixture(autouse=True)
def settings_environment(monkeypatch: MonkeyPatch) -> None:
    """Remove the variables that the settings read, so that none of the user's reaches a test.

    pydantic-settings reads its own without regard to case; OpenTelemetry's are read as
    written.
    """
    for name in [
        name
        for name in os.environ
        if name.lower().startswith(PREFIX.lower()) or name.startswith(OTEL)
    ]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def scratch_home(tmp_path_factory: TempPathFactory, monkeypatch: MonkeyPatch) -> None:
    """Give each test a home of its own, so that no run writes the user's log folder.

    The platform's log folder is under the home: ``~/Library/Logs`` on macOS, and on
    Linux ``~/.local/state`` once ``XDG_STATE_HOME`` is removed.
    """
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


@dataclass(frozen=True)
class InMemory:
    """What the SDK's providers record in this process: the spans ended, and the metrics."""

    spans: InMemorySpanExporter
    reader: InMemoryMetricReader

    def measured(self) -> dict[str, Metric]:
        """Give each metric recorded since the last reading, by its name; this one included."""
        data = self.reader.get_metrics_data()
        return {
            metric.name: metric
            for resource in (data.resource_metrics if data else [])
            for scope in resource.scope_metrics
            for metric in scope.metrics
        }


@pytest.fixture(scope="session")
def providers() -> InMemory:
    """Put the SDK's providers behind the API, over in-memory exporters, once a session.

    The API takes a provider once a process. OpenTelemetry's variables are removed while
    the providers are made, as the SDK reads some then, such as ``OTEL_SDK_DISABLED``.
    Counters, histograms and gauges are read as deltas, so that a reading gives what was
    recorded since the one before.
    """
    spans = InMemorySpanExporter()
    delta = AggregationTemporality.DELTA
    deltas = dict.fromkeys((Counter, Histogram, _Gauge), delta)
    reader = InMemoryMetricReader(preferred_temporality=deltas)
    with pytest.MonkeyPatch.context() as patch:
        for name in [name for name in os.environ if name.startswith(OTEL)]:
            patch.delenv(name)
        tracers = TracerProvider(shutdown_on_exit=False)
        tracers.add_span_processor(SimpleSpanProcessor(spans))
        meters = MeterProvider([reader], shutdown_on_exit=False)
    trace.set_tracer_provider(tracers)
    metrics.set_meter_provider(meters)
    return InMemory(spans, reader)


@pytest.fixture
def telemetry(providers: InMemory) -> InMemory:
    """Give what the SDK records from this test on, the earlier tests' left out."""
    providers.spans.clear()
    providers.measured()
    return providers
