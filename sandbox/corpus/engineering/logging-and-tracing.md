---
title: "Logging and tracing"
---

# Logging and tracing

Owner: Site Reliability, with Platform for the shared libraries. Last reviewed: 2026-09-09.

When something goes wrong at three in the morning, the on-call engineer has the logs, the traces and the Lantern dashboards, and nothing else. Write them for that person.

## Logs

Every service writes JSON lines to standard output, and the platform ships them to Lantern. Use the shared libraries, which add the common fields for you: `qm_logging` in Python, and in Go the `log/slog` handler from `qm-go/logging`.

| Field | Set by | Example |
|---|---|---|
| `ts` | the library | `2026-09-09T08:14:03.512Z` |
| `level` | you | `info` |
| `service`, `version` | the library | `settlement-batcher`, `2.8.1` |
| `msg` | you | `settlement file sent` |
| `trace_id`, `span_id` | the library, from the current span | |
| `error_code` | you, on every error | `PGW-5021` |

Keep the message a short, fixed phrase and put the values in fields, so that searching and counting work:

```python
log.info(
    "settlement file sent",
    extra={"file_id": file.id, "currency": "EUR", "line_count": len(file.lines)},
)
```

```go
logger.InfoContext(ctx, "quote issued",
	slog.String("quote_id", q.ID),
	slog.String("pair", q.Pair),
	slog.Int64("rate_age_ms", q.RateAge.Milliseconds()),
)
```

### Levels

- `error`: someone should look, now or in the morning. Every `error` line carries an `error_code` from the service's catalogue.
- `warn`: unexpected but handled. A pattern of warnings is worth a ticket.
- `info`: one line per meaningful business event, not one per function call.
- `debug`: off in production. Switch it on for one service with a Switchboard flag, for a limited time, and switch it off again.

### What never goes in a log

- PANs, card security codes or track data. The shared libraries mask anything shaped like a PAN, but that is a safety net, not permission.
- Secrets, tokens, API keys and session cookies.
- Personal data beyond an identifier: no names, email addresses, postal addresses or bank account numbers. Log `merchant_id` or `seller_id`, and look the person up in the system that owns the record.
- Whole request or response bodies.

How long logs are kept is set by the [data retention schedule](../data/retention-schedule.md).

## Tracing

We trace with OpenTelemetry ([ADR-011](../architecture/adr-011-opentelemetry.md)). The shared libraries open a span for every inbound request and every outbound call, and propagate the context:

- over HTTP, in the standard Trace Context `traceparent` header;
- over Apache Kafka, in the message headers, so that a consumer's span joins the producer's trace even when the event is consumed hours later.

Add your own spans around work that takes time or can fail on its own: a database transaction, a call to the bank, the building of a batch. Name spans after the operation, not the function: `ledger.post_journal`, not `PostJournalHandler.handle`.

```go
ctx, span := tracer.Start(ctx, "fx_quote.fetch_rate")
defer span.End()
span.SetAttributes(attribute.String("pair", pair))
```

Every trace that contains an error is kept. Of the rest, the collectors keep a fixed share per service, set in the collector configuration that Site Reliability owns; ask in `#team-sre` if your service needs more.

## Metrics

Metrics come from the same libraries and follow the naming in the [coding standards](coding-standards.md). Request rate, errors and duration are recorded automatically. Add counters for business events, such as `payouts_submitted_total`, and histograms for anything with a latency budget. Lantern builds dashboards and alerts from them; each service's SLO dashboards follow the [SLO catalogue](../incidents/slo-catalogue.md).

## Checklist for a new code path

- [ ] One `info` line per business event, with identifiers in fields.
- [ ] Every error logged once, where it is handled, with its `error_code`.
- [ ] A span around each external call.
- [ ] No personal or cardholder data in messages or fields.
- [ ] A metric, if anyone will ever want a graph of it.
