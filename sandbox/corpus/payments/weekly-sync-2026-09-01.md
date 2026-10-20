---
title: "Payments weekly sync 2026-09-01"
---

**Tuesday 1 September 2026**, 10:30 to 11:30 UK time, ENG Sprint 37. A longer slot than usual for the EUR cut-off item.

| | |
|---|---|
| Chair | Nadia Ferreira |
| Present | Nadia Ferreira, Yusuf Achterberg, Kwabena Stroud, Oskar Ngata, Lukas Brennand |
| Guests | Femi Haldane (Support), Arjun Pelletier (Finance) |
| Notes | Yusuf Achterberg |

## Summary

The meeting decided to add a 30-minute buffer before the EUR cut-off. From go-live, `settlement-batcher` will close the last same-day EUR file at 13:30 CET, 30 minutes before our settlement bank's 14:00 CET cut-off. Nothing changes for GBP for now.

## 1. EUR cut-off buffer

Yusuf presented the acceptance times of the last EUR file before the cut-off on each business day in August:

| Accepted by the bank | Business days in August |
|---|---|
| Before 13:30 CET | 6 |
| 13:30 to 13:50 CET | 9 |
| 13:50 to 14:00 CET | 5 |
| After 14:00 CET (missed) | 1 |

The trend is the problem rather than the single miss: in June, no day was later than 13:45. More sellers are paid in EUR each month, the late-morning cycles are larger, and the bank's acceptance slows a little around midday.

Three options were discussed:

1. **Do nothing** and accept the occasional miss. Rejected: each miss moves every payout in that file to the next business day, and sellers notice.
2. **A 30-minute buffer.** The last same-day EUR file closes at 13:30 CET. Payouts that reach the scheduler after it wait for the first file of the next business day, which is what would have happened to them anyway if the file had missed.
3. **A 60-minute buffer.** Safer, but it pushes the effective cut-off to midday in Paris, which the French marketplaces would feel. Femi pointed out that Support already struggles to explain a cut-off at 13:00 UK time to sellers in France.

Arjun asked whether the buffer changes anything in the books. It does not: value dates come from the bank, and the ledger records what the bank reports. Kwabena confirmed that reconciliation needs no change.

Lukas asked whether a missed 13:30 internal close should page anyone. Agreed not: the bank's cut-off is what matters, and the existing alerts already cover stuck batches.

## 2. Closed epics

ENG-28 (chargeback evidence) and ENG-13 (Beacon automation) both closed on 30 August. The `card-auth` evidence endpoint and the payout delay template shipped before the close.

## 3. Date-based API versioning (ENG-30)

Merchant Experience have asked each team that shapes a `merchant-api` response to review it before the versioning work freezes the current shapes. For payments, that means the decline reasons that `card-auth` passes through to merchants. Nadia will review them.

## Decisions

1. **Add a 30-minute buffer before the EUR cut-off.** `settlement-batcher` closes the last same-day EUR file at 13:30 CET. The bank's cut-off stays at 14:00 CET; the buffer is ours.
2. The change goes through the Change Register with a `CHG-` ticket, since it changes when sellers are paid.
3. No change to GBP. Yusuf will bring GBP acceptance times for September to the first sync in October.

## Actions

| Owner | Action | Ticket | Due |
|---|---|---|---|
| Yusuf Achterberg | Change the EUR close in `settlement-batcher`'s configuration, test it in staging, raise the `CHG-` ticket | ENG-4 (background) | 2026-09-10 |
| Femi Haldane | Check the merchant-facing wording about EUR payout timing | | 2026-09-15 |
| Oskar Ngata | Update the payout timing help text in Merchant Hub, to go live with the change | | 2026-09-15 |
| Nadia Ferreira | Review `card-auth` decline reasons exposed through `merchant-api` | ENG-30 | 2026-09-15 |
| Yusuf Achterberg | Update [Settlement windows and cut-off times](settlement-cutoffs.md) once the buffer is live | | At go-live |

Previous: [Payments weekly sync 2026-08-18](weekly-sync-2026-08-18.md). Next: [Payments weekly sync 2026-09-15](weekly-sync-2026-09-15.md).
