---
title: "Payments weekly sync 2026-09-15"
---

Tuesday 15 September 2026, 10:30 UK time. ENG Sprint 38, day two.

- **Present:** Nadia Ferreira (chair), Yusuf Achterberg, Kwabena Stroud, Oskar Ngata, Lukas Brennand.
- **Apologies:** Arjun Pelletier.
- **Notes:** Nadia Ferreira.

## Follow-ups

| Action from 1 September | Status |
|---|---|
| EUR close moved in `settlement-batcher` configuration, tested in staging | Done. Change ticket raised; waiting for approval |
| Merchant-facing wording on EUR payout timing (Femi) | Done. Support will update their payout delay answers at go-live |
| Merchant Hub help text (Oskar) | Ready, behind the same go-live |
| Review of `card-auth` decline reasons for ENG-30 (Nadia) | Done; see item 2 |
| Settlement cut-offs page | Open until go-live |

## 1. EUR buffer go-live

The 30-minute buffer agreed on [1 September](weekly-sync-2026-09-01.md) is ready. Yusuf proposed going live on a Tuesday, so that the first day under the new close is a normal business day with the whole team in. The date depends on the change ticket's approval; the aim is the first half of October, comfortably before the change freeze in [Change freeze calendar 2026](../release/change-freeze-2026.md).

Lukas asked for a dry run: `settlement-batcher` in staging ran for a week with the new close and produced the expected files, with the last same-day EUR file closing at 13:30 CET each day. Nothing else to check before production.

## 2. Date-based API versioning (ENG-30)

Nadia reviewed the decline reasons that `card-auth` passes through `merchant-api`. They are stable and documented. One reason code is spelt inconsistently with the others; Merchant Experience prefer to rename it in the next API version rather than now, and Payments Core agree.

## 3. Peak readiness

The November peak is ten weeks away. Last year's load test, the one ENG-3 started, found `CAU-1301` at about 2.5 times normal peak traffic. Traffic has grown since, so the test is worth repeating against the current release before the freeze. Nadia will run it in staging with Lukas.

Yusuf raised the payout side: end-of-day peaks are where `PayoutQueueBacklog` fires, and the batch cap means a peak cycle can now send well over a hundred batches. He will check with the bank's operations desk that they expect that volume.

## 4. Ledger

Kwabena: the first monthly suspense review with Finance was held on 7 September. Arjun found it useful. `9999-SUSPENSE` held four items at the start of the month and none at the end of the meeting.

## 5. Cadence

Back to weekly from 29 September, as agreed in August.

## Decisions

1. The EUR buffer goes live on a Tuesday, after the change ticket is approved, and before the change freeze.
2. The `card-auth` load test is repeated in staging before the freeze, at the current release.
3. The payments sync returns to weekly on 29 September.

## Actions

| Owner | Action | Ticket | Due |
|---|---|---|---|
| Yusuf Achterberg | Go live with the EUR buffer once approved; then update [Settlement windows and cut-off times](settlement-cutoffs.md) | | 2026-10-13 |
| Nadia Ferreira | Repeat the `card-auth` load test in staging, with Site Reliability | ENG-3 (background) | 2026-10-16 |
| Yusuf Achterberg | Confirm expected peak batch volumes with the settlement bank's operations desk | | 2026-10-02 |
| Oskar Ngata | Tell Merchant Experience that the decline reason rename can wait for the next API version | ENG-30 | 2026-09-18 |
| Kwabena Stroud | Book the October suspense review with Finance | | 2026-09-30 |
