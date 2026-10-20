---
title: "Incident report 2025-06-03: payouts delayed"
---

# Incident report 2025-06-03: payouts delayed

| | |
|---|---|
| Severity | SEV2 |
| Identifiers | `PGW-5021 PAYOUT_BATCH_STUCK`, `PayoutQueueBacklog` |
| Channel | `#inc-payouts-delayed` |
| IC | Sunniva Okafor |
| Operations lead | Jonah Treadwell (payments on-call), then Yusuf Achterberg |
| Author | Yusuf Achterberg |
| Review held | 2025-06-06 |
| Status | Final; all actions done |

## Summary

On the morning of Tuesday 3 June 2025, payouts to sellers were delayed by up to 4 hours
45 minutes. A 42-minute slowdown at our settlement bank left a few payout batches
unacknowledged. `payout-gateway` 4.12, deployed six days earlier, reacted to each stuck
batch by polling the bank for every payout in it, every 30 seconds, without backing off.
The bank throttled our connection, after which even healthy batches went
unacknowledged. We paused the scheduler, resolved the stuck batches by hand with the
bank's operations desk, and resumed once the bank lifted the throttle. Every delayed
payout was sent and paid the same day; none was paid twice.

## Impact

- **7,300 payouts** to **2,100 sellers** on **46 marketplaces** were delayed, the
  earliest from 08:06 UTC, the last sent at 12:52 UTC.
- All were GBP and all were sent before the same-day cut-off of 15:30 UK time (14:30
  UTC), so sellers received their money on the day it was due. See
  [settlement windows and cut-off times](../payments/settlement-cutoffs.md).
- No payout was lost or duplicated.
- Merchant Support handled 64 Harbour tickets from marketplaces whose sellers were
  asking where their money was.

Why SEV2 and not SEV1: payouts were degraded, not down. Batches kept leaving, slowly,
until we paused them ourselves, and the pause was a mitigation rather than an outage.

## Timeline (UTC)

| Time | Event |
|---|---|
| 05-28 13:40 | `payout-gateway` 4.12 deployed. It caps batches at 500 payouts and rewrites how stuck batches are followed up |
| 07:58 | The settlement bank's acknowledgement service slows down (confirmed by the bank later in the morning) |
| 08:16 | First `PGW-5021` on a batch submitted at 08:06. 4.12 starts polling the bank's status endpoint for each of its payouts |
| 08:31 | The bank starts throttling our connection. Acknowledgements for healthy batches stop arriving |
| 08:40 | Stuck batch ratio at 38% on the "payout-gateway overview" dashboard. The bank's own slowdown ends about now, unnoticed by us |
| 08:46 | `PayoutQueueBacklog` fires; Klaxon pages `payments-primary` as SEV2 |
| 08:49 | Jonah Treadwell acknowledges |
| 08:55 | SEV2 declared |
| 08:58 | Sunniva Okafor joins from the IC rota and takes IC |
| 09:06 | DECISION: pause the scheduler with `ks.payout-gateway.batch-scheduler`. No deploy in the last 24 hours, so no rollback |
| 09:09 | Yusuf Achterberg joins; the `payouts` rota is paged |
| 09:15 | Beacon: Payouts "Degraded performance" |
| 09:18 | A restart of the pods is proposed to stop the polling. The IC declines: a restart resubmits in-flight batches |
| 09:24 | Yusuf reaches the bank's operations desk. The bank confirms it is throttling us because of our request volume |
| 09:41 | Traces show about 18,000 status requests per minute, against about 150 on a normal morning |
| 09:50 | Payouts engineers start resolving stuck batches with the bank, one by one; each resolution ends that batch's polling |
| 11:02 | Last of 23 stuck batches resolved; request rate back to normal |
| 11:15 | The bank lifts the throttle |
| 11:19 | Kill switch back to live; the scheduler resumes |
| 12:20 | Queue under 2,000; `PayoutQueueBacklog` resolves |
| 12:52 | Queue back to its normal size; last delayed payout acknowledged |
| 13:10 | Resolved in Klaxon and on Beacon |

## Root cause

4.12 changed how `payout-gateway` follows up a batch after `PGW-5021`. Instead of one
status query per batch, it queried each payout in the batch separately, every 30
seconds, with no backoff and no limit across batches. A full batch of 500 payouts, the
new cap, produced 1,000 requests a minute on its own; 23 stuck batches produced about
18,000. A short slowdown at the bank
therefore produced a retry storm, the storm produced throttling, and the throttling
produced more stuck batches: a loop that outlived the bank's original problem by more
than two hours.

Contributing factors:

- Staging load tests used a bank stub that always answered quickly, so the new
  follow-up path had never run against a slow bank.
- Nothing alerted on our outbound request rate to the bank; we learnt about it from
  the bank.
- Stuck batches can only be resolved by hand, one at a time. That is deliberate, since
  no release resubmits a stuck batch on its own, but 23 of them took 72 minutes.

## What went well

- The kill switch paused the scheduler cleanly; queued payouts waited without loss.
- The IC refused the pod restart. With batches in flight, a restart would have
  resubmitted them and could have paid sellers twice.
- The bank's operations desk was reached within 15 minutes of Yusuf joining.
- Beacon and Support told merchants the same thing; the payout delay wording written
  that morning became the "Payouts delayed" template on
  [status page communications](status-page.md).

## Actions

| Action | Type | Owner | Ticket | Status |
|---|---|---|---|---|
| Follow up a stuck batch with one query per batch, exponential backoff and a global limit | Prevent | Yusuf Achterberg | `pir-action` under ENG-1 | Done, shipped in 4.13 |
| Bank stub in staging that answers slowly and throttles, used in every payout load test | Prevent | Jonah Treadwell | `pir-action` under ENG-1 | Done |
| Alert on outbound request rate to the settlement bank | Detect | Jonah Treadwell | `pir-action` under ENG-1 | Done |
| Add "do not restart the pods" to the payout-gateway runbook | Process | Yusuf Achterberg | `pir-action` | Done |
| Shared wording for payout delays on Beacon and in Harbour | Process | Femi Haldane | `pir-action` | Done |

The retry storm is the bug fixed in
[payout-gateway 4.13](../payments/release-notes-payout-gateway-4-13.md). The
[payout-gateway rollback runbook](../payments/payout-gateway-rollback.md) now says not to
roll back below 4.13 for exactly this reason.
