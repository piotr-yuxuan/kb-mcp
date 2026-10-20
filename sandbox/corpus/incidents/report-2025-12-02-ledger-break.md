---
title: "Incident report 2025-12-02: ledger reconciliation break"
---

# Incident report 2025-12-02: ledger reconciliation break

SEV3, `LDG-4091 UNBALANCED_JOURNAL`, alert `LedgerReconBreak`. Channel
`#inc-ledger-break`. IC and author: Rafe Lindgren (Ledger). Short-form review held on
2025-12-04 with Kwabena Stroud and Arjun Pelletier. Final.

## Summary

The monthly fee run on 1 December posted 1,214 fee journals whose debits and credits
differed by one penny. The nightly reconciliation flagged them early on 2 December.
The cause was a commission split, released on 20 November, that worked out each leg in
floating point and rounded each leg separately. We posted correcting journals the same
morning; the fix shipped on 3 December, the first day after the change freeze. The only
effect outside the company was that fee invoices for 31 marketplaces went out a day
late.

## Impact

- 1,214 journals unbalanced by 1p each, **£12.14 in total**. All GBP.
- Monthly fee invoices for **31 marketplaces** were issued on 3 December instead of
  2 December, because invoicing refuses to read unbalanced journals.
- Seller balances and payouts were not affected: the differences sat on the fee legs,
  not on the sellers' accounts.
- Graded SEV3: a minor degradation (late invoices) with a workaround (Finance told the
  affected marketplaces, and the fees were visible in Merchant Hub throughout).

## Timeline (UTC)

```text
11-20 10:30  ledger release with the tiered commission split for marketplace fees
12-01 00:05  monthly fee run posts 48,600 fee journals through the bulk posting path
12-02 02:00  recon-daily starts
12-02 02:38  LedgerReconBreak: 1,214 LDG-4091 UNBALANCED_JOURNAL; posted to #team-ledger
             (SEV3 default, no page out of hours)
12-02 08:12  Rafe Lindgren, on the ledger rota, picks it up
12-02 08:40  SEV3 declared, #inc-ledger-break
12-02 09:05  Finance told; invoice generation, due at 10:00, held
12-02 10:15  cause found: per-leg rounding in the new split function
12-02 10:50  Arjun Pelletier agrees the correction: a 1p rounding leg on each journal
12-02 11:30  correcting journals posted through the posting API
12-02 12:40  reconciliation re-run for 1 December: no breaks
12-02 13:20  resolved; invoices scheduled for the morning run on 3 December
12-03 10:20  fix deployed
```

## Root cause

Marketplaces on tiered pricing pay a commission that is split three ways: our fee, the
scheme cost recovery and the marketplace's rebate. The new split function multiplied
the fee by each leg's share as a floating-point number and rounded each result to the
penny. Three independently rounded legs do not always add up to the total; in 1,214
cases they were a penny over or under.

Two things let that reach the ledger:

- **Floating point in money code**, contrary to
  [ADR-017](../architecture/adr-017-money-minor-units.md). The code review did not
  catch it, because the function took and returned integer pence; the floats were
  inside.
- **The bulk posting path skipped the balance check.** The ordinary posting API refuses
  a journal whose debits and credits differ. The bulk path, added for month-start
  volumes, inserted journals directly and relied on the nightly reconciliation to
  catch mistakes, which it did, a day later.

The month-start fee run is the only caller of the new code path, so nothing showed
between the release on 20 November and 1 December.

## What went well

- The reconciliation did its job: every unbalanced journal was found on the first
  night.
- Every penny was explained, so nothing had to go to the suspense account; the
  corrections went to the rounding differences account with Finance's agreement. See
  [the ledger reconciliation runbook](../payments/ledger-reconciliation.md) for how
  breaks are normally worked.
- The fix waited one day for the end of the
  [2025 change freeze](../release/change-freeze-2025.md) rather than going in as an
  exception. The correcting journals were data, not a deploy, so they did not need one.

## Actions

| Action | Type | Owner | Status |
|---|---|---|---|
| Split amounts in integer minor units, giving the remainder to the largest leg | Prevent | Rafe Lindgren | Done, 2025-12-03 |
| Send the bulk posting path through the same balance check as the posting API | Prevent | Kwabena Stroud | Done, 2026-01 |
| Lint rule in the ledger repository rejecting floating-point types in money code | Prevent | Rafe Lindgren | Done |
| Rehearse the month-start fee run on staging on the last business day of each month | Detect | Kwabena Stroud | Done; runs monthly |

All four are ENG tickets labelled `pir-action`, filed without an epic: ENG-2, the
reconciliation hardening epic, had closed in October. They appear on the
[PIR actions tracker](pir-actions-tracker.md).
