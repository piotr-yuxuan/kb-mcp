---
title: "Incident report 2026-05-20: merchant_orders_daily late"
---

# Incident report 2026-05-20: merchant_orders_daily late

- **Severity:** SEV3, under the standing rule that a late finance mart is a SEV3
- **Alert:** `DQ-017 FRESHNESS_BREACH` on `marts.merchant_orders_daily`
- **Channel:** `#inc-orders-late`
- **IC and author:** Signe Abernethy, data on-call that night
- **Reviewed:** 2026-05-22, short form, with Tomasz Wilde, Rafael Quist and Platform
- **Status:** Final; two actions still open

## Summary

The partition of `marts.merchant_orders_daily` for 19 May was published at 08:24 UTC
on 20 May, 2 hours 24 minutes after its 06:00 UTC deadline. Late on 19 May, during a
planned rolling restart of the Apache Kafka brokers, the `dw-ingest` consumer group
that loads payment events into `raw` stalled and stopped committing. Its only alert
still watched the old RabbitMQ queue, which has been empty since the migration to the
event log. The pipeline's `wait_for_ingestion` task did what it should: it refused to
build on incomplete data and paged at 04:30. We restarted the consumers, which caught
up from their committed offsets without losing an event, and re-ran the pipeline.

## Impact

- Finance's daily revenue report, normally sent at 08:00 UK time, went out at 09:40 UK
  time. Finance used the previous day's report, marked provisional, for the morning
  cash call.
- The merchant health dashboard and Support's "top merchants by volume" view showed
  18 May's figures until 08:24 UTC.
- No merchant impact. No data lost, no wrong numbers published, no backfill needed.

## Timeline (UTC)

```text
05-19 21:30  Platform starts a planned rolling restart of the Kafka brokers
05-19 22:39  dw-ingest consumers stall during a rebalance: partitions held, nothing
             written, no offsets committed. Raw payment events stop at 22:39
05-20 01:30  merchant_orders_daily starts; wait_for_ingestion waits for the
             payment events watermark to pass 00:45
05-20 04:30  wait_for_ingestion gives up; Klaxon pages data-primary
05-20 04:41  Signe Abernethy acknowledges
05-20 05:02  Cause located: watermark stuck at 22:39; consumer lag 2.3 million events
05-20 05:15  platform-primary paged; joins at 05:24
05-20 05:38  dw-ingest consumers restarted; consumption resumes from committed offsets
05-20 06:00  DQ-017 FRESHNESS_BREACH on marts.merchant_orders_daily
05-20 06:04  SEV3 declared; Finance told in the channel and in #team-data, with an
             estimate of 08:30
05-20 07:26  Consumers caught up; watermark past 00:45
05-20 07:31  Run restarted for the partition
05-20 08:24  Run complete, quality checks passed, partition published
05-20 08:40  Finance sends the revenue report
05-20 08:55  Resolved
```

The restart at 07:31 was the ordinary command from the
[pipeline's page](../data/merchant-orders-daily.md):

```bash
conveyor run merchant_orders_daily --partition 2026-05-19
```

## Root cause

During the rolling restart, a rebalance left the `dw-ingest` consumers holding their
partitions without reading from them. The consumers' health check reported them
alive, because the process was up, and nothing measured whether they were making
progress.

The real gap was in alerting. Before ENG-29 moved domain events from RabbitMQ to the
replicated event log ([ADR-019](../architecture/adr-019-replicated-event-log.md)),
ingestion was watched by a queue-depth alert on the RabbitMQ side. The migration added
consumer lag panels to Lantern but kept the old alert, and since April that alert had
been watching a queue that nothing writes to. A stall of six hours raised nothing until
the pipeline downstream noticed.

## What went well

- `wait_for_ingestion` refused to build the mart on a partial night. A partial
  partition would have passed the freshness check and given Finance numbers that were
  low by several hours of payments.
- The event log keeps events for 7 days and the consumers commit only after writing,
  so the catch-up was complete and needed no backfill.
- Finance knew before 07:00 UTC, an hour before the report was due.

## Where we got lucky

It was an ordinary Tuesday night. On the last night of a month, the same stall would
have held up the revenue figures Finance needs on the first working days for the
month-end close.

## Actions

| Action | Type | Owner | Status |
|---|---|---|---|
| Alert on `dw-ingest` consumer lag, paging the data on-call when lag exceeds 15 minutes | Detect | Signe Abernethy | Done |
| Remove the RabbitMQ-era ingestion alerts left over from ENG-29 | Process | Signe Abernethy | Done |
| Platform to announce broker maintenance in `#team-data` and finish it before 23:00 UTC | Process | Teodor Halloran | Done |
| Restart procedure for stalled consumers in [data platform on-call](../data/data-on-call.md) | Mitigate | Hana Ostrowska | In Progress |
| Consumers detect their own lack of progress and restart | Prevent | Signe Abernethy | To Do |

All five are ENG tickets labelled `pir-action`. How this incident was graded is set out
in [data quality alerts](../data/quality-alerts.md) and
[production incident management](incident-management.md).
