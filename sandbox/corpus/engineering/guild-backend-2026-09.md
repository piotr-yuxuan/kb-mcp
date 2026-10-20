---
title: "Backend guild notes September 2026"
---

# Backend guild notes September 2026

**Wednesday 2026-09-16**, 15:00 to 16:10 UK time, video only. Chair: Yusuf (Payouts). Notes: Imogen (Payments Core).

Present: Kwabena (Ledger), Yusuf and Léa (Payouts), Imogen and Dara (Payments Core), Hamza (Platform), Lukas (Site Reliability), Sunniva (Data Platform), Noor and Felix (Merchant Experience), Theo (Security).

## Actions carried from June

All five June actions are closed. The `migrations-lint` change shipped in sprint 32, and the consumer rule is in the [coding standards](coding-standards.md). Every service that consumes events now has a lag panel in Lantern. `card-auth` passed its load test on Go 1.26 in sprint 33 and moved over the following week. The description of ENG-30 records that internal APIs stay unversioned.

## `log/slog` as the standard for Go

Hamza proposed that every Go service log with the standard library's `log/slog`, through a shared handler in `qm-go/logging` that writes the fields listed in [logging and tracing](logging-and-tracing.md). Today `card-auth` and `fx-quote` each carry their own wrapper around an older library, and the two disagree on field names, which makes cross-service searches in Lantern clumsy.

Dara's worry was allocations on the authorisation hot path. Hamza had run the `card-auth` load test with the new handler: no measurable change at p99, and slightly fewer allocations per request than the old wrapper.

- **Decision:** adopt `log/slog` with the shared handler. Kwabena updates the coding standards today.
- No big-bang migration: services move as they are touched. Lukas asked that both payments Go services move before the end of the year, since they produce most of the logs on-call reads; Dara and Imogen agreed.

## ENG-30: version handling in `merchant-api`

Noor and Felix showed where ENG-30 stands. Header parsing and the version registry merged in sprint 37 behind a flag. The first change that needs a new dated version, a renamed field on refunds, is in review, along with the transformer that serves the old shape to merchants on earlier versions. CI now runs the contract tests once per supported version.

Theo asked whether the requested version is logged. It is not yet. Agreed that `merchant-api` logs it as `api_version` on every request, which also gives Merchant Experience the data to see who is still on old versions.

Kwabena asked whether `ledger` would ever see the version. No: as the June guild agreed, `merchant-api` translates at its edge and nothing behind it changes.

## Time to first review over the summer

The Lantern dashboard "engineering review health" showed Payouts' median time to first review above one business day for most of August, against the target in the [code review guidelines](code-review.md). Yusuf explained that two of the team's four regular reviewers were on annual leave at once and the rota did not cover the gap. The team now puts two people on the rota for any week when someone on it is away. Other teams stayed within the target.

## Kafka start-up failures in CI

Lukas and Hamza reported that in August about one integration run in eleven failed because the Kafka container was not ready when the tests started. Hamza has changed the CI templates and `qm` to wait on the broker's health check rather than on a fixed sleep. Several teams had quarantined tests that were never flaky, only early; their owners should bring them back now, following the [testing strategy](testing-strategy.md).

## Any other business

Sunniva gave notice that ENG-20, the Conveyor backfill tooling, will soon ask for confirmation from the owners of source tables before a large backfill of their events runs. Owners will be asked in their team channel; the procedure is in [backfilling historical partitions](../data/backfills.md).

## Actions

| Action | Owner | Due |
|---|---|---|
| Update the coding standards for `log/slog` | Kwabena | 2026-09-16 |
| Move `card-auth` and `fx-quote` to the shared handler | Dara | By the end of the year |
| Log `api_version` on every `merchant-api` request (ENG-30) | Felix | End of sprint 38 |
| Un-quarantine tests that only failed on Kafka start-up | Each team lead | End of sprint 39 |
| Add the "two on the rota" rule to the code review page | Yusuf | End of sprint 38 |

Next meeting: Wednesday 2026-10-14. Chair: Léa.
