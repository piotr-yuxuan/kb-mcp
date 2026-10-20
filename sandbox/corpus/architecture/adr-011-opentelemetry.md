---
title: "ADR-011: OpenTelemetry for tracing"
---

- **Status:** Accepted, 2020-11-02
- **Author:** Bram Oyelaran
- **Deciders:** Ottilie Marsh, Lukas Brennand, Nadia Ferreira, Yusuf Achterberg

## Context

A payment that goes wrong usually crosses several services before anyone notices:
`merchant-api` receives it, `card-auth` authorises it, `risk-scorer` scores it, and
events about it flow on to `ledger` and `notify`. When something is slow or fails, the
first hour of an incident is spent working out where.

Today we have three partial answers:

- Some Go services emit traces through the OpenTracing interfaces, to a tracing
  back end that only those services use.
- Python services emit no traces at all.
- Log lines carry a `request_id` when the developer remembered to add it, and it is
  not passed across the message broker ([ADR-007](adr-007-message-broker.md)).

OpenTracing and OpenCensus have merged into OpenTelemetry, which now has a stable
tracing specification in sight, libraries for both Go and Python, and a vendor-neutral
collector. The older projects are winding down, so standing still is not an option for
the services that already use them.

## Decision

Every service, in Go and in Python, emits traces with OpenTelemetry.

- **Propagation.** Trace context travels in the standard Trace Context headers
  (`traceparent`, `tracestate`) on every HTTP call, and in message headers on every domain event.
- **Collection.** Each cluster ([ADR-010](adr-010-kubernetes.md)) runs an OpenTelemetry
  Collector, operated by Platform. Services send spans to the collector in their own
  cluster, never straight to a back end.
- **Sampling.** Services sample 10% of traces at the start of a request. The collector
  also keeps every trace that contains an error, whatever the first decision was.
- **Viewing.** Traces are viewed in Lantern, next to the metrics and dashboards
  engineers already use, so that a spike on a graph links to example traces.
- **Logs.** Every log line written during a traced request carries `trace_id` and
  `span_id`. The shared logging libraries add them; nobody does it by hand.
- **Naming.** Span names describe the operation (`settlement.build_file`), not the
  value (`build file 2020-11-02`). Our own attributes are prefixed `quillmoor.`.

```python
from opentelemetry import trace

tracer = trace.get_tracer("settlement-batcher")


def build_file(batch):
    with tracer.start_as_current_span("settlement.build_file") as span:
        span.set_attribute("quillmoor.batch_id", batch.id)
        span.set_attribute("quillmoor.line_count", len(batch.lines))
        return render(batch)
```

Metrics stay as they are for now. We will look at OpenTelemetry metrics once that part
of the specification is stable, in a separate ADR if it changes anything.

## Consequences

- One trace follows a payment from `merchant-api` through every service it touches,
  including across the broker.
- The Go services on OpenTracing must be moved over. Platform does the shared
  libraries; each team updates its own services.
- The collector is one more thing to run in every cluster, and its availability
  matters during incidents, exactly when we need traces most.
- Sampling means a given healthy request may have no trace. Engineers investigating a
  single merchant's complaint should start from logs, which always carry the trace
  identifier when one exists.
- What to log, at which level, and how to read a trace are covered in
  [Logging and tracing](../engineering/logging-and-tracing.md).

## Alternatives considered

- **Stay on OpenTracing.** Its interfaces are frozen and its successor is OpenTelemetry.
  We would be moving later, with more services to move.
- **A commercial monitoring vendor's own agent.** Fast to start, but it ties our
  instrumentation to one vendor's format and pricing, and its agent would need to run
  inside the card data environment.
- **Build our own context propagation.** We would be writing, badly, what an open
  standard already gives us.

## Related ADRs

- [ADR-003](adr-003-go-latency-critical.md) and
  [ADR-002](adr-002-python-back-office.md): the two languages to instrument.
- [ADR-019](adr-019-replicated-event-log.md): trace context carried on events in the
  replicated log.
