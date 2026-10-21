---
title: "Runbook: ledger reconciliation breaks"
---

Owned by the Ledger team (`#team-ledger`, lead Kwabena Stroud). Finance relies on this runbook for month-end, so changes to it are reviewed by Arjun Pelletier as well. Last reviewed 2026-10-12.

## In short

- The `recon-daily` job runs at 02:00 UTC and compares the ledger with our settlement bank's statement for the previous business date.
- Anything that does not match is a **break**. Breaks under £5 in total are cleared automatically; the rest raise `LedgerReconBreak`.
- Every break is either explained and corrected, or its amount is moved to the suspense account `9999-SUSPENSE` with a note.
- Breaks older than 3 business days go to the finance controller.

## What recon-daily does

`recon-daily` is a Kubernetes CronJob in the `ledger` namespace, scheduled for 02:00 UTC every day, weekends included. It works on the previous entry date and does three things in order:

1. **Checks every journal.** For each journal posted on that date, it sums the debits and the credits. They must be equal. Any journal where they differ is a break with code `LDG-4091`.
2. **Matches the bank statement.** It loads our settlement bank's end-of-day statement for each account and currency, and matches each statement line to a ledger entry by bank reference, amount and value date. Statement lines with no matching ledger entry are breaks with code `LDG-4102`.
3. **Totals and clears.** It adds up the absolute value of all open breaks from the run, in GBP at that day's rate. If the total is under £5, the run clears every break automatically, posting a single write-off journal tagged `auto_clear` and referencing each break. Otherwise the breaks stay open and the job raises `LedgerReconBreak`.

The run usually takes 12 to 18 minutes. Its results are in the ledger database, schema `recon`, on the read replica:

| Table | Holds |
|---|---|
| `recon.runs` | One row per run: start, end, entry date, counts, total break amount |
| `recon.breaks` | One row per break: code, amount, currency, account, bank reference, state, owner |
| `recon.break_notes` | Free-text notes and the journal references that resolved each break |

On weekends and UK bank holidays the bank produces no statement. The run still checks journals for `LDG-4091`, then matches the statement lines it receives on the next business day against all the entry dates since the last statement.

## The alert

`LedgerReconBreak` fires when the nightly reconciliation found breaks. A run whose breaks were all cleared automatically counts as clean, so in practice the alert means that at least one break is still open. It pages the Ledger rota in Klaxon at 07:30 UK time on business days, not at 02:30: a break is a bookkeeping problem, not an outage, and nobody needs to fix it in the night. On weekends it opens a ticket for Monday instead of paging. How the Ledger rota itself is organised is in [On-call rota and paging policy](../incidents/on-call.md).

The alert's description links to the Lantern panel "ledger reconciliation", which shows the run's breaks by code, account and age.

## The two break codes

### LDG-4091 UNBALANCED_JOURNAL

A journal's debits and credits differ. The ledger's write path rejects unbalanced journals, so one reaching the reconciliation means either a bug in a code path that bypasses that check (bulk imports, the correction tool, a migration) or a problem with the data itself. Treat every `LDG-4091` as a bug, even when the amount is small and the run cleared it automatically: an auto-cleared `LDG-4091` still opens a ticket for the Ledger team.

Find the journal and its postings:

```sql
SELECT j.journal_id, j.source_service, j.created_at,
       SUM(CASE WHEN p.side = 'debit'  THEN p.amount_minor ELSE 0 END) AS debits,
       SUM(CASE WHEN p.side = 'credit' THEN p.amount_minor ELSE 0 END) AS credits
FROM recon.breaks b
JOIN ledger.journals j ON j.journal_id = b.journal_id
JOIN ledger.postings p ON p.journal_id = j.journal_id
WHERE b.code = 'LDG-4091'
  AND b.state = 'open'
GROUP BY j.journal_id, j.source_service, j.created_at;
```

The `source_service` column tells you whose code wrote it. Fix the cause with that team before you correct the data, or tomorrow's run will find the same thing.

### LDG-4102 MISSING_SETTLEMENT_LINE

A bank statement line has no ledger entry. The bank moved money and the ledger does not know why. This is by far the more common code, and most of its causes are known:

| Cause | How to recognise it | Resolution |
|---|---|---|
| A payout returned by the seller's bank | Credit line with a return reason code, referencing an earlier payout | `payout-gateway` posts the return journal; if it did not, Payouts posts it |
| A bank fee or interest | Small debit with the bank's fee narrative | Post a fee journal to the bank charges account |
| A payout batch submitted twice | Two debit lines for the same batch on the same day | Stop. Page Payouts; see [Runbook: rolling back payout-gateway](payout-gateway-rollback.md) for why this happens |
| A settlement from the acquiring bank with an unexpected reference | Large credit whose reference does not match the expected format | Usually a format change at the acquiring bank; match it by hand and raise a ticket |
| Timing: the ledger entry has a different value date | Matching entry exists one business day either side | Match it by hand; no correction needed |

List the open ones for a run:

```sql
SELECT break_id, amount_minor, currency, bank_reference, statement_narrative, age_business_days
FROM recon.breaks
WHERE code = 'LDG-4102'
  AND state = 'open'
ORDER BY ABS(amount_minor) DESC;
```

## Working a break

Work the largest breaks first. For each one:

1. **Claim it.** Set yourself as owner so that two people do not chase the same line:

   ```bash
   shipwright exec ledger -- ledger-admin breaks claim --break-id brk_7d21e0
   ```

2. **Explain it.** Use the tables above. Write what you found in a note, even if it is "matches payout batch b_41a9 returned by the seller's bank".
3. **Correct it.** If the ledger is missing an entry or holds a wrong one, post a correcting journal. Never edit or delete an existing journal; the ledger is append-only.

   ```bash
   shipwright exec ledger -- ledger-admin post-correction \
     --break-id brk_7d21e0 \
     --from-account 1100-BANK-GBP \
     --to-account 2310-SELLER-RETURNS \
     --amount-minor 48250 --currency GBP \
     --note "Payout returned by seller's bank, ref RTN-0911"
   ```

   Corrections over £1,000 need a second Ledger engineer's approval in the tool before they post.
4. **Or suspend it.** If after a reasonable look you cannot explain the amount, move it to `9999-SUSPENSE` so that the books balance while the investigation continues. Unexplained amounts go to the suspense account; they are not written off, and they are not left open.

   ```bash
   shipwright exec ledger -- ledger-admin suspend --break-id brk_7d21e0 \
     --note "Credit from acquiring bank, reference format unknown, asked Payouts"
   ```

## The suspense account

`9999-SUSPENSE` is a holding account, not a resolution. Every amount in it has a break reference and an owner, and the Ledger team goes through it every Monday. When an amount is explained, a correcting journal moves it out of suspense to the right account, and the break's state changes from `suspended` to `resolved`.

At month-end Finance expects the suspense account to be as close to zero as possible; the close calendar is in [Month-end close calendar](../finance/month-end-close.md).

## Escalation to Finance

Breaks older than 3 business days go to the finance controller, whether they are open or sitting in suspense. Age counts from the business date of the run that found the break, in UK business days.

`recon-daily` does the routing itself: on the fourth business day it sets the break's state to `escalated` and emails a summary to `finance@quillmoor.example`, addressed to the finance controller. The Ledger team stays the owner and keeps working the break; escalation means Finance now knows, can judge the accounting impact, and may decide on a write-off that engineering cannot make.

| Age in business days | State | Who acts |
|---|---|---|
| 0 to 3 | `open` or `suspended` | Ledger rota |
| 4 and over | `escalated` | Ledger rota, with the finance controller informed and deciding on write-offs |

## A worked example

Tuesday's run, for Monday's entry date, finds three breaks:

| Break | Code | Amount | Statement narrative |
|---|---|---|---|
| `brk_7d21e0` | `LDG-4102` | £482.50 credit | Return of an earlier payout, reason "account closed" |
| `brk_7d21e4` | `LDG-4102` | £3.20 debit | Monthly account charge |
| `brk_7d21e9` | `LDG-4102` | €1,240.00 credit | Reference in a format nobody recognises |

The total is far above £5, so nothing is cleared and `LedgerReconBreak` pages at 07:30. The engineer on the Ledger rota claims all three. The first is a returned payout that `payout-gateway` failed to record: a correcting journal moves it to the seller returns account, and a ticket goes to Payouts. The second is the bank's charge: a fee journal. The third cannot be explained by lunchtime, so it is suspended to `9999-SUSPENSE` with a note, and Payouts are asked to query it with the bank. By the following Monday, the fourth business day, it is still unexplained, so it is escalated to the finance controller; on the Wednesday the bank confirms it as a misdirected payment and returns it, and the suspense amount is cleared.

## Break states

```text
open --> claimed --> resolved
  |         |
  |         +--> suspended --> resolved
  |                   |
  +--> auto_cleared   +--> escalated (after 3 business days) --> resolved
```

## Edge cases

**A large run after a payments incident.** After a payout rollback or a bank outage, a single run can hold hundreds of breaks. Most will be timing differences that resolve themselves in the next run. Wait for the next run before working them, unless they are larger than £10,000 in total, and say so in `#team-ledger`.

**EUR breaks.** The £5 auto-clear threshold applies to the total of the run in GBP. A run with only EUR breaks is converted at that day's rate, so the effective threshold in euros moves a little from day to day.

**Statement arrives late.** If the bank's statement has not arrived by 02:00 UTC, `recon-daily` checks journals only and retries the statement match hourly until 08:00 UTC. A missing statement after that is itself a ticket for Payouts, who hold the relationship with our settlement bank.

**A break that appears and disappears.** Usually a value-date difference. If the same reference flips between open and matched on consecutive runs, raise it with the Ledger team: the matching window may need widening.

## History

The nightly reconciliation has existed since the ledger did, but most of its present behaviour came from ENG-2, Ledger reconciliation hardening, in 2025. Two changes from that epic matter to this runbook:

- **Refunds settled after midnight.** Before ENG-2, `LDG-4102` was raised for refunds settled after midnight UTC: the bank dated them the next day, the ledger dated them the day the refund was requested, and every one became a break that the next run quietly matched. The fix matches refund lines across the date boundary, and the noise from them disappeared.
- **Automatic clearing.** Breaks under £5 in total are cleared automatically. Before that, the Ledger rota spent most mornings matching rounding differences of a few pence by hand.

The ledger reconciliation break of December 2025 is written up in [Incident report 2025-12-02: ledger reconciliation break](../incidents/report-2025-12-02-ledger-break.md).

## See also

- [Payments platform architecture](platform-architecture.md), for the ledger's model of accounts, postings and journals
- [Settlement windows and cut-off times](settlement-cutoffs.md), which explains why some statement lines carry the next business day's date
- [Runbook: rolling back payout-gateway](payout-gateway-rollback.md)
