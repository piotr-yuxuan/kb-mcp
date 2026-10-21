---
title: "ADR-007: Publish domain events through a message broker"
---

> [!WARNING]
> This ADR was superseded by [ADR-019](adr-019-replicated-event-log.md) on 2025-05-12,
> and the broker it describes was retired at the end of the migration epic ENG-29.
> The page is kept unchanged as the record of the original decision. Do not build
> anything new against it: read ADR-019 for how domain events work today.

- **Status:** Superseded by ADR-019 on 2025-05-12. Accepted on 2018-03-12.
- **Author:** Yusuf Achterberg
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Kwabena Stroud, Bram Oyelaran

## Context

At the start of 2018, when something happens in one of our services that another
service cares about, the first service calls the second over HTTP. When
`payout-gateway` learns that our settlement bank has accepted a batch, for example, it
calls `ledger` to post the journal, `notify` to email the marketplace, and
`merchant-api` to update the payouts' status. Every new interest in that fact means a
new call added to `payout-gateway`.

This has gone wrong in four ways over the past six months.

1. **Availability is coupled.** On 23 January the `ledger` database was slow for forty
   minutes during maintenance. The acknowledgement handler in `payout-gateway` timed
   out on its call to `ledger`, retried, and timed out again. Three hundred and twelve
   payouts were left in an unknown state on our side, although the bank had accepted
   them, and two of us spent an evening matching them by hand.
2. **Producers know their consumers.** Adding a consumer means changing, testing and
   deploying the producer, owned by a different team, which has its own priorities.
3. **Retries are reinvented.** Each caller has its own retry loop, with its own idea of
   back-off and of when to give up. Some give up silently.
4. **Every call has its own shape.** There is no shared vocabulary for "this happened".
   The payload `payout-gateway` sends to `notify` differs from the one it sends to
   `ledger`, for the same fact.

We wrote down what we need before looking at tools:

- A producer publishes a fact once, and does not know or care who listens.
- A consumer that is down receives what it missed when it comes back.
- Delivery is at least once. Consumers can cope with duplicates.
- A team of fourteen engineers, with no dedicated operations staff, can run it.
- It runs on the virtual machines we already have.

We were just as explicit about what we do not need. We do not need to replay old
events: each consumer keeps the state it cares about in its own tables. We do not need
long retention, and we do not need a strict order across all events.

## Decision

Services publish domain events to RabbitMQ topic exchanges, one exchange per producing
service. Consumers receive them on their own durable queues. Events are kept only
until consumed.

### Exchanges, routing keys and queues

- Each producing service has one durable topic exchange, named `events.<service>`:
  `events.payout-gateway`, `events.ledger`, `events.card-auth` and so on. Only that
  service publishes to it.
- The routing key names the entity and what happened to it, in the past tense:
  `batch.acknowledged`, `payout.failed`, `journal.posted`.
- Each consumer declares its own durable queue, named `<consumer>.<purpose>`, and binds
  it to the exchanges it needs with routing patterns. A consumer never reads from
  another consumer's queue.

A typical topology, as it looked when this ADR was accepted:

```text
exchange events.payout-gateway   (topic, durable)
  queue ledger.payout-postings        binding: batch.acknowledged
  queue notify.payout-emails          binding: payout.*
  queue merchant-api.payout-status    binding: payout.*

exchange events.ledger           (topic, durable)
  queue settlement.journal-feed       binding: journal.posted
```

### The event envelope

Every event is a JSON document with the same envelope, whatever its type:

```json
{
  "event_id": "evt_2c9d1f0a7b3e4d51",
  "type": "payout-gateway.batch.acknowledged",
  "occurred_at": "2018-03-09T14:02:11Z",
  "producer": "payout-gateway",
  "schema_version": 1,
  "data": {
    "batch_id": "bat_7f41c2",
    "payout_count": 118
  }
}
```

- `event_id` is unique and stable. A retry or a republication of the same fact keeps
  the same `event_id`, which is how consumers spot duplicates.
- `data` holds the facts a consumer needs, not a copy of the producer's whole record.
  If a consumer needs more, it asks the producer's API.
- No card data is ever published as an event. The boundary for card data is set in
  [Payments platform architecture](../payments/platform-architecture.md), and the
  broker sits outside it.

### Changing an event

An event type is a contract with consumers that its producer does not know about, so
it changes in one direction only:

- **Adding** an optional field to `data` is always allowed and needs no announcement.
  Consumers ignore fields they do not recognise.
- **Removing, renaming or retyping** a field is a new version of the event. The
  producer raises `schema_version`, publishes both versions side by side, and stops
  publishing the old one only when every consumer's owner has confirmed the move in
  `#team-platform`.
- **Changing the meaning** of an event without changing its shape is not allowed.
  A fact that means something new gets a new routing key.

The events published on the day this ADR was accepted:

| Producer | Routing key | Published when |
|---|---|---|
| `payout-gateway` | `batch.submitted` | a payout batch is sent to the settlement bank |
| `payout-gateway` | `batch.acknowledged` | the bank has accepted the batch |
| `payout-gateway` | `payout.failed` | the bank has returned a single payout |
| `ledger` | `journal.posted` | a journal has been posted |
| `card-auth` | `authorisation.decided` | an authorisation has been approved or declined |
| `merchant-api` | `merchant.updated` | a merchant's settings or contacts have changed |

### Publishing

A producer must never lose an event after committing the change it describes, and must
never publish an event for a change that was rolled back. We use an outbox table in
the producer's own PostgreSQL database ([ADR-004](adr-004-postgresql.md)):

```sql
CREATE TABLE event_outbox (
    event_id     text        PRIMARY KEY,
    exchange     text        NOT NULL,
    routing_key  text        NOT NULL,
    payload      jsonb       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
```

The service writes its row in the outbox in the same transaction as the state change.
A relay process reads unpublished rows in order, publishes them with publisher
confirms switched on, and sets `published_at` only once the broker has confirmed. If
the relay dies between publishing and marking, the event is published twice, which
consumers already have to tolerate.

### Consuming

- A consumer acknowledges a message only after it has processed it and committed the
  result. A consumer that acknowledges first and processes second can lose events, and
  the broker will not be able to give them back.
- On a failure, the consumer rejects the message and the broker redelivers it. After
  five attempts, the message goes to the dead-letter exchange `events.dead-letter` and
  lands in the queue `<consumer>.dead-letter`, where the owning team investigates.
- Consumers are idempotent: processing the same `event_id` twice has the same effect
  as processing it once.

### Retention: until consumed, and no longer

Events are kept only until consumed. Once every queue bound to a message's routing key
has acknowledged it, the broker deletes it. There is no history to go back to:

- a consumer that binds a new queue today receives only events published from today;
- an event whose routing key matches no binding is discarded, and the producer is not
  told;
- a consumer that acknowledged an event by mistake cannot ask for it again. The
  producer has to publish it anew from its own records.

We accepted this deliberately. It keeps the broker small, and our consumers do not
need the past.

### Running the broker

Platform runs a cluster of three RabbitMQ nodes on our virtual machines. Queues are
mirrored across all three nodes, messages are persistent, and exchanges and queues are
declared durable, so that the loss of one node loses nothing. Queue depth per consumer
is on the shared dashboards, with an alert when a queue has been growing for more than
fifteen minutes.

## Consequences

### What gets better

- Producers no longer call consumers. A slow `ledger` no longer stops `payout-gateway`
  from recording that the bank accepted a batch; `ledger` catches up when it recovers.
- Adding a consumer is a queue and a binding, with no change to the producer.
- One envelope, one set of naming rules, one retry policy.
- The dead-letter queues make failed events visible instead of silently lost.

### What gets harder, accepted at the time

- **No replay.** An event lives only until consumed. A bug that acknowledges and
  discards events cannot be undone from the broker. The producer must republish from
  its own database, which means a one-off script every time.
- **New consumers start empty.** A service that needs the history of a fact must load
  it from the producer by some other means, such as an export, before binding its
  queue.
- **Queues live in the broker's memory and disk.** A consumer that is down for hours
  makes its queue grow, and a very large queue slows the whole broker down for
  everyone.
- **Duplicates.** Delivery is at least once. Every consumer has to deduplicate.
  [ADR-008](adr-008-idempotency-keys.md) followed four months later and made
  idempotency a rule for every write, not only for event consumers.
- **Order is not guaranteed.** Several instances of a consumer reading the same queue
  can process two events about the same payout in either order. Consumers must compare
  versions or timestamps rather than trust arrival order.
- **Topology by hand.** Exchanges, queues and bindings are declared by each service at
  start-up. A mistyped binding fails quietly.

### Not to be confused with merchant webhooks

Domain events are internal and never leave our infrastructure. The webhooks that tell
merchants about their payments and payouts are sent by `notify`, which consumes domain
events and calls the merchant's endpoint. Replaying a merchant webhook is a different
operation, described in
[How to replay a merchant webhook](../payments/replay-webhook.md).

## Alternatives considered

### Apache Kafka

A replicated log keeps events for a configured period, whether or not anyone has read
them, and lets each consumer read from where it chooses. We liked the model. We turned
it down in 2018 because:

- running it needed an Apache ZooKeeper ensemble beside the brokers, at least six
  machines in all for a resilient set-up;
- nobody on the team had run it in production;
- our volume, about 40,000 events a day, did not call for it;
- replay was not one of our requirements.

We noted that we would revisit this choice if replay or volume ever became a
requirement. Both did, and ADR-019 is the result.

### Keep direct HTTP calls, with a shared retry library

This fixes the reinvented retries, and nothing else. Producers would still know their
consumers, and a slow consumer would still slow the producer.

### Consumers poll a table in the producer's database

Simple and transactional, but it puts every consumer inside the producer's database,
reading its tables, which we already find hard to change safely. It also turns every
consumer into a source of load on the producer's database.

### PostgreSQL `LISTEN` and `NOTIFY`

Built in and cheap, but a notification sent while no one is listening is lost, which
fails our second requirement outright.

## Related ADRs

- [ADR-004](adr-004-postgresql.md): the outbox lives in the producer's PostgreSQL
  database.
- [ADR-008](adr-008-idempotency-keys.md): idempotency for every write, which consumers
  of these events depend on.
- [ADR-012](adr-012-database-per-service.md): one database per service, which made
  events the main way to share facts between services.
- [ADR-019](adr-019-replicated-event-log.md): supersedes this record.
