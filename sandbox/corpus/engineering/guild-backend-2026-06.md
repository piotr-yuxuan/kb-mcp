---
title: "Backend guild notes June 2026"
---

# Backend guild notes June 2026

- **Date:** Wednesday 2026-06-17, 15:00 to 16:00 UK time, Quill House floor 4 and video
- **Chair:** Kwabena (Ledger)
- **Notes:** Hamza (Platform)
- **Attendees:** Kwabena and Amara (Ledger), Yusuf and Léa (Payouts), Dara and Imogen (Payments Core), Bram and Hamza (Platform), Ciarán (Site Reliability), Sunniva (Data Platform), Noor (Merchant Experience)
- **Apologies:** Lukas (Site Reliability), Theo (Security)

## Agenda

1. Migration lint, a month on
2. Python 3.13 and Go 1.26 baselines
3. Event consumers after the move to the replicated log
4. Looking ahead: date-based API versioning

## 1. Migration lint, a month on

Bram recapped ENG-10, which closed with sprint 30 on 2026-06-07. The `migrations-lint` check has been required in every repository's CI since mid-May. It has stopped 14 migrations since then: 12 were real problems, and 2 were false positives, both in `settlement-batcher`, where the lint misread a view definition.

Amara asked for the lint to recognise the Ledger team's annotation marking the contract step of a migration, so that reviewers stop asking the same question on every Ledger change. Yusuf asked for the lint's message to link to [database migrations](../release/database-migrations.md) rather than restating the rule in a sentence that people then argue with. Both agreed.

## 2. Python 3.13 and Go 1.26 baselines

Hamza reported that the development container images for Python 3.13 and Go 1.26 are published, and the CI templates will default to them from sprint 32. Repositories on older versions get a warning in `lint` until sprint 35, and a failure after that.

Dara asked that `card-auth` move to Go 1.26 only after a load test in staging, given how tight its latency budget is. Nobody objected; the other Go services can move as soon as their owners like.

## 3. Event consumers after the move to the replicated log

Since ENG-29 finished in April, Sunniva and Léa have each found a consumer that committed its offset before the effect of the event was durable. In both cases a restart during a deploy to staging skipped events. Nothing reached production, but it would have.

The guild agreed one pattern for every consumer on the log ([ADR-019](../architecture/adr-019-replicated-event-log.md)):

```python
for event in consumer.poll(timeout=1.0):
    with db.transaction() as tx:
        if tx.processed_events.contains(event.id):
            continue  # a redelivery: already applied
        apply(tx, event)
        tx.processed_events.add(event.id)
    consumer.commit(event)  # only once the effect is durable
```

Ciarán offered a consumer lag panel for each team's Lantern dashboard, so that a stuck consumer shows up before anyone asks where their events went.

## 4. Looking ahead: date-based API versioning

Noor previewed ENG-30, planned to start in sprint 34. `merchant-api` will read the `Quillmoor-Version` header described in [ADR-023](../architecture/adr-023-api-versioning.md) at its edge. Imogen asked whether internal services need to know which version a merchant asked for. The view in the room was no: `merchant-api` translates, internal APIs stay unversioned and change only additively, and the contract tests in the [testing strategy](testing-strategy.md) keep them honest.

## Decisions

1. `migrations-lint` learns the Ledger contract-step annotation, and its messages link to the migrations page.
2. Python 3.13 and Go 1.26 are the baselines from sprint 32; older versions fail CI from sprint 35.
3. Event consumers commit their offset only once the effect is durable, and are idempotent on the event identifier. Kwabena adds this to the [coding standards](coding-standards.md).
4. Internal APIs are not versioned by date; only `merchant-api` handles the header.

## Actions

| Action | Owner | Due |
|---|---|---|
| Teach `migrations-lint` the contract-step annotation and add the link | Hamza | End of sprint 32 |
| Add the consumer rule to the coding standards | Kwabena | 2026-07-01 |
| Consumer lag panel template in Lantern | Ciarán | End of sprint 32 |
| Write "no internal versioning" into the description of ENG-30 | Noor | Before sprint 34 |
| Load test `card-auth` on Go 1.26 in staging | Dara | End of sprint 33 |

Next meeting: Wednesday 2026-07-15. Chair: Amara.
