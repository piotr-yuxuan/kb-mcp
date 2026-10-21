---
title: "payout-gateway 4.12 release notes"
---

> [!WARNING]
> Do not deploy 4.12. It can start a retry storm after `PGW-5021`. Use 4.13 or later.

| | |
|---|---|
| Released | Wednesday 28 May 2025 |
| Previous release | 4.11.2 |
| Epic | ENG-1, Payout-gateway resilience |
| Released by | Payouts, `#team-payouts` |
| Migrations | None |

## Summary

4.12 caps batches at 500 payouts. At end-of-day peaks a single batch used to hold several thousand payouts: the bank took longer to acknowledge such large files, and when one became stuck, every payout in it waited. With the cap, a stuck batch holds at most 500. 4.12 also starts checking the status of stuck batches automatically.

## Changes

### Changed

- **Batches are capped at 500 payouts.** When more than 500 payouts are waiting for one marketplace and currency at a cycle, the scheduler cuts several batches of at most 500 each, in order of payout creation. The cap is the configuration key `scheduler.max_batch_size`:

  ```yaml
  # payout-gateway: config/scheduler.yaml
  scheduler:
    interval: 15m
    max_batch_size: 500
  ```

  Raising the cap needs the Payouts lead's agreement; lowering it is safe at any time.
- Each cycle now submits more, smaller files. Expect a cycle at the evening peak to send around 60 batches where it used to send a dozen.

### Added

- **Automatic status checks for stuck batches.** When a batch raises `PGW-5021`, `payout-gateway` now asks the bank's status interface about each payout in the batch, and retries the question until it gets an answer, so that many stuck batches resolve themselves without a person.

### Fixed

- The scheduler skipped a cycle when it started within one second of a quarter-hour boundary.

## Operational notes

- The **Stuck batch ratio** panel will move to a smaller scale, since each cycle now has more batches.
- `settlement-batcher` needed no change: it already handled several files per cycle for the same currency.

## Rolling back

Rolling back to 4.11.2 is safe; there are no migrations. Batches become uncapped again from the next cycle.

## Known issues

*Added after release.* The automatic status checks can turn a few stuck batches into a **retry storm**. The checks run per payout rather than per batch and retry immediately, with no backoff and no limit, so a handful of stuck batches of 500 payouts each produce thousands of status requests a minute. The bank slows down under that load, its acknowledgements for other batches arrive late, more batches pass the 10-minute mark and raise `PGW-5021`, and each of those starts its own checks.

Fixed in 4.13 under ENG-1. See [payout-gateway 4.13 release notes](release-notes-payout-gateway-4-13.md).

## Next

The previous release is [payout-gateway 4.11 release notes](release-notes-payout-gateway-4-11.md).
