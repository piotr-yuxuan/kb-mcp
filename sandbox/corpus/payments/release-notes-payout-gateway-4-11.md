---
title: "payout-gateway 4.11 release notes"
---

| | |
|---|---|
| Released | Wednesday 14 May 2025 |
| Previous release | 4.10.1 |
| Epic | ENG-1, Payout-gateway resilience |
| Released by | Payouts, `#team-payouts` |
| Migrations | One, on `payout-gateway`'s own database (expand only) |

## Summary

4.11 lets the on-call pause the batch scheduler from Switchboard, with no deploy, and adds a status command that shows at a glance what the service is doing. It also makes the service's ledger writes idempotent. Sellers and merchants see no change.

## Changes

### Added

- **Kill switch `ks.payout-gateway.batch-scheduler`.** When flipped, the scheduler stops cutting new batches. Payouts keep arriving and keep queueing; batches already in flight carry on. Flipping it back resumes batching at the next 15-minute cycle. Until now the only way to stop batches was to scale the service to zero.
- **`pgw-admin status`.** Prints the running release, the scheduler's state, the queue depth, the number of in-flight and stuck batches, and the age of the oldest in-flight batch:

  ```bash
  shipwright exec payout-gateway -- pgw-admin status
  ```

  ```text
  release:            4.11.0
  scheduler:          running
  queued payouts:     312
  in-flight batches:  41
  oldest in-flight:   1m48s
  stuck batches:      0
  ```

- A column `scheduler_paused_at` on the `scheduler_state` table, recording when the kill switch was last flipped.

### Changed

- **Idempotent ledger writes.** Every payout journal now carries an idempotency key derived from the payout identifier, as [ADR-008](../architecture/adr-008-idempotency-keys.md) requires. A retried write to the ledger can no longer post a payout twice in our books.
- Batch submission and acknowledgement are now traced with OpenTelemetry, so a batch can be followed from the scheduler to `settlement-batcher` and back.

### Fixed

- `pgw_queue_depth` counted payouts under a hold, which are not waiting for a batch. They are now reported separately as `pgw_payouts_held`.
- `pgw-admin drain --wait` printed its summary twice when it gave up after 20 minutes.

## Operational notes

- The kill switch is the first step of any rollback from now on. The Payouts team is writing a runbook around pause, drain and roll back; until it is published, ask in `#team-payouts` before using the switch outside an incident.
- Flipping the switch during a cycle does not cut that cycle's batches short; the cycle completes and the next one does not start.

## Rolling back

Rolling back to 4.10.1 is safe. The new column is ignored by 4.10.1, and Shipwright keeps the migration in place. If the kill switch is flipped when you roll back, 4.10.1 will not see it and will resume batching at once: flip it back first, on purpose, or keep the service drained.

## Known issues

None.

## Next

4.12 caps the size of batches. See [payout-gateway 4.12 release notes](release-notes-payout-gateway-4-12.md); the previous release is [payout-gateway 4.10 release notes](release-notes-payout-gateway-4-10.md).
