---
title: "payout-gateway 4.10 release notes"
---

| | |
|---|---|
| Released | Tuesday 29 April 2025 |
| Previous release | 4.9.3 |
| Epic | ENG-1, Payout-gateway resilience |
| Released by | Payouts, `#team-payouts` |
| Migrations | None |

## Summary

4.10 is the first release of the payout-gateway resilience work. It gives batches an explicit **stuck** state and adds a **drain** command, so that `payout-gateway` can be stopped without leaving batches half-recorded. Nothing changes for sellers or merchants.

## Changes

### Added

- **`pgw-admin drain --wait`.** Stops taking batches from the queue and waits until every in-flight batch has either been acknowledged by the bank or been marked stuck. It gives up after 20 minutes and prints what is left. Run it inside the service with Shipwright:

  ```bash
  shipwright exec payout-gateway -- pgw-admin drain --wait
  ```

- **A `stuck` batch state.** A batch that the bank has not acknowledged after 10 minutes is now marked `stuck` and raises `PGW-5021 PAYOUT_BATCH_STUCK`. Until now the same situation produced a timeout line in the logs and nothing else, and the batch stayed "in flight" for ever.
- **Metrics** `pgw_batches_in_flight`, `pgw_batches_stuck_total` and `pgw_queue_depth`, and a **Stuck batch ratio** panel on the Lantern dashboard "payout-gateway overview".

### Changed

- **Start-up recovery ignores stuck batches.** On start, `payout-gateway` still resubmits batches that have no acknowledgement, but no longer touches batches in the `stuck` state. A stuck batch is resolved by a person, with the bank.
- **Graceful shutdown** now waits up to 120 seconds for in-flight batches, up from 30.
- Every log line about a batch carries its batch identifier (`batch_id`).

### Fixed

- A batch whose acknowledgement arrived in the same second as a pod shutdown could be recorded twice in the batch table. No duplicate payment resulted, because the bank had only received one file, but reconciliation reported a break the next morning.

## Operational notes

- The drain command is meant to be followed by a release change or a planned restart. On its own it leaves the service idle: after a drain, the queue only moves again once the pods are replaced.
- The stuck state does not yet page anyone. The Payouts team is collecting a few weeks of data before setting a threshold.
- `PGW-5021` counts will look higher than the timeout lines they replace, because batches that eventually succeed after 10 minutes are now counted as well.

## Rolling back

Rolling back to 4.9.3 is safe: there are no migrations. The `stuck` state is stored as a value of an existing column, which 4.9.3 reads as "in flight", so batches marked stuck by 4.10 would be resubmitted by 4.9.3's recovery. Before rolling back, list the stuck batches and resolve them with the bank:

```bash
shipwright exec payout-gateway -- pgw-admin batches list --state stuck
```

## Known issues

None.

## Next

4.11 adds a Switchboard kill switch for the batch scheduler. See [payout-gateway 4.11 release notes](release-notes-payout-gateway-4-11.md).
