---
title: "payout-gateway 4.13 release notes"
---

| | |
|---|---|
| Released | Tuesday 10 June 2025 |
| Previous release | 4.12.1 |
| Epic | ENG-1, Payout-gateway resilience |
| Released by | Payouts, `#team-payouts` |
| Migrations | None |

## Summary

4.13 fixes the retry storm after `PGW-5021` that 4.12 could start: ENG-1's bug. Status checks for stuck batches are now made once per batch, with backoff and a hard limit, and give up cleanly. 4.13 is the oldest release that any rollback of `payout-gateway` may target.

## Changes

### Fixed

- **Retry storm after `PGW-5021`.** In 4.12, a stuck batch made `payout-gateway` query the bank's status interface for every payout in the batch, retrying at once and without limit. A few stuck batches were enough to slow the bank, which made more batches stuck. 4.13 changes three things:
  1. **One status check per batch**, not per payout. The bank's status interface answers for the whole file.
  2. **Exponential backoff with jitter**, starting at 30 seconds and doubling, for at most 5 attempts. After the fifth, the batch stays `stuck` and is left for a person to resolve with the bank.
  3. **A global limit** of 20 status checks per second across all pods, whatever the number of stuck batches.

  The settings live with the scheduler's:

  ```yaml
  # payout-gateway: config/scheduler.yaml
  stuck_batch_checks:
    per: batch
    initial_backoff: 30s
    max_attempts: 5
    global_rate_limit_per_second: 20
  ```

### Changed

- New metrics `pgw_status_checks_total` and `pgw_status_checks_throttled_total`, shown on "payout-gateway overview" under the stuck batch panels.
- `pgw-admin status` now shows how many stuck batches are still being checked automatically and how many are waiting for a person.

### Unchanged

- The batch cap of 500 payouts from 4.12 stays.
- The kill switch, drain command and stuck state from 4.10 and 4.11 behave as before.

## Operational notes

- After upgrading, stuck batches may stay stuck for up to about 15 minutes while the backoff runs its course. That is intended: a slow answer is better than a flood.
- If `pgw_status_checks_throttled_total` rises steadily, more batches are stuck than the global limit can check. That is no longer a `payout-gateway` problem but a sign that the bank, or our link to it, is in trouble: page the Payouts rota rather than raising the limit.
- With this release the Payouts team considers the pause, drain and roll back sequence complete, and has written it up as [Runbook: rolling back payout-gateway](payout-gateway-rollback.md).

## Rolling back

Do not roll back below 4.13. Rolling back to 4.12.1 brings the retry storm back. If 4.13 or a later release misbehaves, roll back to an earlier 4.13 patch or forward to a fix.

## Known issues

None.

## Next

The previous release is [payout-gateway 4.12 release notes](release-notes-payout-gateway-4-12.md). ENG-1 closed at the end of ENG Sprint 8, on 3 August 2025.
