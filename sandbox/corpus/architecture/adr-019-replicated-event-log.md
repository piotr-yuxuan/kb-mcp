---
title: "ADR-019: Move domain events to a replicated log"
---

- **Status:** Accepted, 2025-05-12. Supersedes [ADR-007](adr-007-message-broker.md).
- **Author:** Tomasz Wilde
- **Deciders:** Ottilie Marsh, Bram Oyelaran, Yusuf Achterberg, Kwabena Stroud,
  Nadia Ferreira, Lukas Brennand
- **Migration:** epic ENG-29, Event log migration (ADR-019)

## Context

Since 2018, our services have published domain events to RabbitMQ topic exchanges, as
ADR-007 decided. Each consumer reads from its own queue, and an event is kept only
until every queue that wants it has consumed it. ADR-007 said plainly that replay was
not a requirement, and that we would revisit Apache Kafka if replay or volume ever
became one. Both have.

### Volume

ADR-007 was written for about 40,000 events a day. We now publish about 9 million on
an ordinary day, with peaks of around 900 a second during marketplace sales. The
broker copes, but with little headroom, and every peak season starts with a capacity
review that ends in larger machines.

### No replay

Three times in the past twelve months, a consumer acknowledged events that it had
failed to process, because of a bug that swallowed an exception. The broker did what
it was asked and deleted them. Each time, the producing team had to write a one-off
script to republish the missing events from its own database, while the consuming team
worked out which ones were missing. The worst case was `notify`, which missed
`payout.failed` events for six hours: sellers were not told that their payouts had
been returned, and Merchant Support learnt about it from them.

### New consumers start from nothing

Any new consumer that needs the history of a fact has to arrange an export from the
producer before binding its queue. `risk-scorer` needed four months of authorisation
outcomes when it started using them as features, and the export took longer to agree
than to run.

### The data platform's queue endangers everyone

The data platform copies every event into the warehouse through a queue bound to every
exchange. In February, warehouse ingestion was paused for planned maintenance. The
queue grew to 30 million messages in the broker, the broker raised its memory alarm,
and flow control slowed every producer, `payout-gateway` among them. Nothing was lost,
but for forty minutes the payments platform ran slower because the warehouse was
asleep.

### Order

Several instances of a consumer reading one queue process events about the same payout
in any order. Every consuming team has written its own version checks to cope, and
they do not all agree.

### Requirements

We listed what a replacement must do before choosing one:

1. Keep events for a fixed period, whether or not anyone has read them.
2. Let each consumer read at its own pace, and go back in time when it needs to.
3. Keep events about the same thing in order.
4. Absorb ten times today's peak without a redesign.
5. Be operable by Platform on our Kubernetes clusters ([ADR-010](adr-010-kubernetes.md)),
   in more than one region if we later need it.
6. Keep what ADR-007 got right: producers that do not know their consumers, one
   envelope, and the outbox.

## Decision

Domain events move to Apache Kafka, a replicated log, run by Platform. Events are kept
7 days, and consumers track their offsets.

### Topics

- **One topic per producer and event family**, named `<service>.<family>.v<major>`:
  `payout-gateway.payout.v1`, `ledger.journal.v1`, `card-auth.authorisation.v1`. Only
  the owning service publishes to a topic, and its team owns the topic's schema.
- **Partition key.** Events are keyed by the identifier of the thing they describe:
  the payout, the journal, the authorisation. Every event about one payout lands in
  the same partition and is read in the order it was written. A topic's owner may
  choose another key, such as the merchant, when consumers need that order instead,
  and documents the choice.
- **Partitions.** Twelve per topic by default; more on request to Platform.
- **Replication.** Every topic has three replicas, with at least two in sync before a
  write is acknowledged. Producers write with `acks=all` and idempotence switched on.
- **Retention.** Events are kept 7 days, whether they have been read or not, and are
  then deleted. We do not use compacted topics for domain events.

Topic definitions live in the `platform` repository and are applied by Platform's
tooling, not created by hand:

```yaml
# topics/payout-gateway.payout.v1.yaml
name: payout-gateway.payout.v1
owner: payouts
partitions: 12
replication_factor: 3
config:
  retention.ms: 604800000      # 7 days
  min.insync.replicas: 2
  cleanup.policy: delete
schema: schemas/payout-gateway/payout.v1.json
```

### Producers

- The **outbox** stays. A service writes its event to its outbox table in the same
  transaction as the change it describes, and a relay publishes it to the topic. Only
  the relay's destination changes.
- The **envelope** stays: `event_id`, `type`, `occurred_at`, `producer`,
  `schema_version` and `data`, as defined in ADR-007. Trace context travels in record
  headers ([ADR-011](adr-011-opentelemetry.md)).
- **Schemas** are JSON Schema files kept in the owning team's repository. Continuous
  integration checks every change against the previous version: within a major
  version, only optional fields may be added. A breaking change is a new topic, `v2`,
  published alongside `v1` until every consumer has moved.

### Consumers

- Each consumer is a **consumer group**, named `<service>.<purpose>`, such as
  `ledger.payout-postings`.
- Consumers **track their offsets** in Kafka. A consumer commits an offset only after
  it has processed the events before it and committed its own database transaction,
  never before.
- Processing is **at least once**. After a crash, a consumer reads again from its last
  committed offset, so it will see some events twice. Consumers deduplicate by
  `event_id`, as they already must under [ADR-008](adr-008-idempotency-keys.md).
- **Lag** for every group is on its team's Lantern dashboard. Each team sets its own
  alert on its own groups.

The shape of a consumer loop, in Go:

```go
for {
	rec, err := consumer.Poll(ctx)
	if err != nil {
		return err
	}
	err = store.WithTx(ctx, func(tx *sql.Tx) error {
		seen, err := dedup.Seen(tx, rec.EventID)
		if err != nil || seen {
			return err
		}
		return postJournal(tx, rec)
	})
	if err != nil {
		return err // offset not committed: the record is read again after restart
	}
	if err := consumer.Commit(ctx, rec); err != nil {
		return err
	}
}
```

### Replay

Replay becomes an ordinary operation. A team that needs to reprocess events rewinds its
own consumer group to a point in time within the last 7 days, from Platform's toolbox
pod, after stopping the consumer:

```bash
kafka-consumer-groups.sh \
  --bootstrap-server events.internal.quillmoor.example:9092 \
  --group ledger.payout-postings \
  --topic payout-gateway.payout.v1 \
  --reset-offsets --to-datetime 2025-05-06T09:00:00.000 \
  --execute
```

A team never rewinds a group it does not own. For anything older than 7 days, the
history lives in the data platform's tables, which keep events far longer; a consumer that
needs more than a week rebuilds from there, with help from Data Platform. See
[Data platform overview](../data/platform-overview.md).

### Why 7 days

Seven days covers a long weekend with a bank holiday, plus the working days it can take
to notice that a consumer has been quietly wrong. Beyond that, the data platform is the
better source: it is queryable, and it is already the record of history. A longer
retention would multiply disk for little gain, and would keep events that may hold
personal data for longer than we need them. How personal data is handled in the
warehouse is covered in [Erasure requests in the warehouse](../data/erasure-requests.md).

## Migration

The migration is epic ENG-29, planned for ENG Sprint 14 to ENG Sprint 26. It must move
every producer and every consumer without losing an event or stopping a service.

1. **Clusters.** Platform builds Kafka in staging and production, with the topic
   tooling and the dashboards.
2. **Dual-publish.** Each producer's outbox relay publishes every event to both the
   RabbitMQ exchange and the Kafka topic, with the same `event_id`. Nothing reads from
   Kafka yet, but its contents can be compared with the broker's.
3. **Move consumers one by one.** A consumer starts its Kafka group from a point a few
   minutes before the moment it stops reading its RabbitMQ queue. The overlap is
   harmless, because the consumer deduplicates by `event_id`.
4. **Stop publishing to RabbitMQ** for a producer once its last RabbitMQ consumer has
   moved.
5. **Retire the broker** once no producer publishes to it.

The planned order puts the riskiest consumer first, because it gains the most:

| Order | Consumer | Why there |
|---|---|---|
| 1 | Data platform ingestion | Its queue is the one that endangers the broker |
| 2 | `notify` | Gains replay where it hurt most |
| 3 | `merchant-api` status copies | Many topics, simple processing |
| 4 | `risk-scorer` features | Wants history, can wait for it |
| 5 | `ledger` | Most critical; moves once the pattern is proven |
| 6 | `settlement-batcher` | Last, with Payouts and Ledger together |

## Consequences

### What gets better

- **Replay** within 7 days, by the consuming team, without the producer's help.
- **Order** per partition key, so consumers can drop most of their version checks.
- **Isolation between consumers.** A slow or stopped consumer only falls behind. It no
  longer fills a queue in a broker that everyone shares.
- **New consumers** can start from 7 days ago, and from the data platform for
  anything older.
- **Headroom.** Partitions spread load across brokers, and adding partitions or brokers
  does not change how anyone publishes or consumes.

### What gets harder

- **Platform runs Kafka.** Brokers with persistent volumes on Kubernetes, upgrades,
  rebalancing, and 7 days of every event on disk, three times over. It is a larger
  operation than the RabbitMQ cluster, and Platform is adding one engineer for it.
- **Offsets are the consumer's responsibility.** A consumer that commits before
  processing can still lose events, exactly as one that acknowledged too early could
  under ADR-007. The difference is that it can now rewind and recover.
- **Order is per partition only.** Two events about different payouts have no order
  between them, and a consumer must not assume one.
- **Seven days is a hard edge.** A consumer that is broken for longer than that loses
  its place in the log and must rebuild from the data platform.
- **Two systems for a while.** During the migration, producers publish twice, and
  on-call engineers must know which consumers have moved.

## Alternatives considered

### RabbitMQ streams

Recent RabbitMQ versions add streams, an append-only log with retention and replay.
Staying on the broker we know was tempting. We decided against it because every
consumer would have to be rewritten for streams anyway, and our data platform's
ingestion and the replication between regions we expect to need are both better
supported, and better understood by the people we hire, on Kafka.

### Apache Pulsar

It separates storage from serving and offers tiered storage for long retention. It is
also a larger system to run, with a separate storage layer, and nobody at Quillmoor
has operated it.

### NATS with JetStream

Light and simple to run, with persistence and replay. Its ecosystem for warehouse
ingestion is thinner, and we would be early adopters at our volume.

### A hosted streaming service from our cloud provider

Less to run, but it ties the event backbone to one provider, and connecting it to the
card data environment's clusters raised questions we could not answer quickly. We may
revisit this once the migration is done.

### Let consumers read the producers' outbox tables

It would give replay for free, but it puts every consumer inside the producer's
database, which [ADR-012](adr-012-database-per-service.md) forbids for good reasons.

## Related ADRs

- [ADR-007](adr-007-message-broker.md): the decision this record supersedes.
- [ADR-008](adr-008-idempotency-keys.md): consumers still deduplicate.
- [ADR-010](adr-010-kubernetes.md): where the brokers run.
- [ADR-011](adr-011-opentelemetry.md): trace context on events.
- [ADR-012](adr-012-database-per-service.md): why events, not shared tables.
- [ADR-021](adr-021-active-passive-regions.md): topics mirrored to the standby region.

## Update, 2026-04-13

ENG-29 is done. The last consumer, `settlement-batcher`, moved in March, the
producers stopped publishing to RabbitMQ at the end of that month, and the broker was
shut down on 2026-04-09.
