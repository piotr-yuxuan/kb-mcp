---
title: "Settlement windows and cut-off times"
---

Maintained by the Payouts team (`#team-payouts`) with Finance. Page owner: Yusuf Achterberg. Product questions: Oskar Ngata. Last reviewed on 2026-07-28.

This page answers one question that Support, Finance and on-call engineers all ask in different words: *if a payout leaves now, when does the seller get the money?* The answer depends on the currency, on the time our settlement bank accepts the batch, and on the calendar.

## The cut-offs at a glance

| Currency | Rail | Cut-off | Accepted before the cut-off | Accepted after the cut-off | Calendar |
|---|---|---|---|---|---|
| GBP | Domestic same-day bank transfer | 15:30 UK time | Settles the same business day | Settles the next business day | Bank holidays in England and Wales |
| EUR | SEPA credit transfer | 14:00 CET (13:00 UK time) | Settles the same business day | Settles the next business day | SEPA closing days |

Quillmoor Payouts pays only in GBP and EUR. A seller whose bank account is in any other currency cannot be onboarded for payouts; Support has a macro for that conversation.

## What "cut-off" means here

The cut-off is the latest time at which **our settlement bank must have accepted a file** for it to be processed that business day. It is the bank's clock that counts, not ours, and not the time at which the payout was created.

Between a payout being created and the bank accepting it there are three steps, each of which takes time:

1. **Batching.** `payout-gateway` cuts batches every 15 minutes, at :00, :15, :30 and :45 past each hour. A payout created at 15:16 waits for the 15:30 batch.
2. **File building.** `settlement-batcher` renders each batch as a file in the bank's format. This takes seconds for a normal batch.
3. **Acceptance.** The bank accepts the file and acknowledges it. Most acknowledgements arrive within two minutes. If none arrives within 10 minutes, `payout-gateway` raises `PGW-5021` and the batch is treated as stuck.

So a GBP payout created at 15:20 joins the 15:30 batch and will very likely be accepted at about 15:31: after the cut-off. It settles the next business day. Anyone promising a seller "same day" should count back from the cut-off, not from the clock.

## Time zones

- **UK time** is the time in London: GMT in winter, BST in summer.
- **CET**, on this page and in `settlement-batcher`'s configuration, means the time in Paris: CET in winter, CEST in summer. The SEPA cut-off does not move with the seasons in local terms; it stays at 14:00 Paris time all year.

The UK and France change their clocks on the same weekends, so the EUR cut-off is 13:00 UK time all year round. That is the conversion most people need, and it is the one Support quotes.

All timestamps in `payout-gateway`, `settlement-batcher` and the ledger are stored in UTC. Local time appears only in the cut-off configuration, with an explicit time zone:

```yaml
# settlement-batcher: config/cutoffs.yaml
cutoffs:
  GBP:
    rail: gbp-same-day
    cutoff: "15:30"
    timezone: Europe/London
    calendar: uk-england-wales
  EUR:
    rail: sepa-credit-transfer
    cutoff: "14:00"
    timezone: Europe/Paris
    calendar: sepa
```

### The last batch that makes it

Counting back from each cut-off gives the last batch that normally reaches the bank in time. These are observations from the first half of 2026, not guarantees:

| Currency | Cut-off, UK time | Last batch that normally makes it | First batch that normally misses |
|---|---|---|---|
| GBP | 15:30 | 15:15 | 15:30 |
| EUR | 13:00 | 12:45 | 13:00 |

The 15:15 GBP batch is usually accepted by 15:18, which leaves room for a slow acknowledgement but not for a stuck one. On the busiest days of the month, when large marketplaces pay their sellers at the same moment, the 15:15 batch can be one of several dozen, and the bank's acceptance times stretch.

## Checking when a payout was accepted

When a seller or a colleague asks about one payout, look up its batch and the bank's acceptance time rather than guessing from the creation time:

```bash
shipwright exec payout-gateway -- pgw-admin payouts show --payout-id po_5Kq81mZt
```

```text
payout:        po_5Kq81mZt
seller:        sel_3Hn20cWa
amount:        1,250.00 EUR
created:       2026-07-07T11:12:44Z
batch:         b_8e01c7 (cut at 2026-07-07T11:15:00Z)
accepted:      2026-07-07T11:17:02Z
cut-off:       2026-07-07T12:00:00Z (14:00 Europe/Paris)
value date:    2026-07-07
```

The `cut-off` line is printed in UTC with the local time beside it, which avoids most arguments. In July, 14:00 in Paris is 12:00 UTC and 13:00 in London.

## Business days, weekends and bank holidays

A business day is a day on which the rail settles. Weekends never are. Beyond weekends, each currency follows its own calendar:

- **GBP** follows the bank holidays of England and Wales, including substitute days when a bank holiday falls on a weekend.
- **EUR** follows the SEPA closing days: 1 January, Good Friday, Easter Monday, 1 May, 25 December and 26 December. There are no substitute days.

`payout-gateway` keeps cutting batches every 15 minutes on weekends and bank holidays, and `settlement-batcher` keeps sending files. The bank accepts them and holds them until the next business day. That is deliberate: it spreads the load of a Monday morning over the whole weekend, and a held file is a file that cannot be late.

Because the two calendars differ, GBP and EUR payouts made at the same moment can settle on different days.

## Worked examples

All times are UK time, and "accepted" means accepted by our settlement bank.

| Payout accepted | Currency | Settles | Why |
|---|---|---|---|
| Tuesday 7 July 2026, 11:00 | GBP | Tuesday 7 July | Before the 15:30 cut-off |
| Tuesday 7 July 2026, 13:20 | EUR | Wednesday 8 July | After the EUR cut-off, 13:00 UK time |
| Friday 22 August 2025, 16:00 | GBP | Tuesday 26 August | After the cut-off; Monday 25 August was the summer bank holiday |
| Friday 22 August 2025, 16:00 | EUR | Monday 25 August | 25 August is not a SEPA closing day |
| Thursday 2 April 2026, 15:45 | GBP or EUR | Tuesday 7 April | Good Friday and Easter Monday close both rails |
| Thursday 30 April 2026, 14:00 | EUR | Monday 4 May | After the cut-off; Friday 1 May is a SEPA closing day |
| Friday 1 May 2026, 10:00 | GBP | Friday 1 May | 1 May is a business day for GBP |
| Friday 1 May 2026, 16:00 | GBP | Tuesday 5 May | Monday 4 May was the early May bank holiday |
| Saturday, any time | GBP or EUR | The next business day | Weekends never settle |

## Who maintains the calendars

Finance publishes the next calendar year's bank holidays for both rails each November. Payouts loads them into `settlement-batcher` as two files, `calendars/uk-england-wales.yaml` and `calendars/sepa.yaml`, through a normal release. A missing year makes `settlement-batcher` refuse to start, which is noisy but safe.

If the government announces an extra bank holiday at short notice, Finance tells `#team-payouts`, and Payouts ships a calendar-only release. That has happened once since 2017.

## When things go wrong near a cut-off

**A stuck batch near the cut-off.** A batch that raises `PGW-5021` at 15:25 is unlikely to be accepted before 15:30. Do not resubmit it by hand to "catch" the cut-off; a resubmitted batch can be paid twice. Follow [Runbook: rolling back payout-gateway](payout-gateway-rollback.md), which explains the stuck state, and accept that the payouts settle the next business day.

**Payouts paused for an incident.** Pausing the scheduler across a cut-off moves every queued payout to the next business day. Tell `#inc-payments` when a pause will cross a cut-off, so that Support can prepare.

**The bank is late.** Occasionally our settlement bank accepts a file late because of its own problems. The cut-off is still the cut-off: the bank decides whether a late file settles that day, and tells Payouts. The ledger records the value date the bank reports.

**Reconciliation the next morning.** A payout that misses a cut-off shows on the bank statement a business day later than the ledger expected. The nightly reconciliation matches it by reference within a business day either side, so it does not normally become a break; if it does, see [Runbook: ledger reconciliation breaks](ledger-reconciliation.md).

## What to tell merchants and sellers

Support answers sellers from [Payout delays: what to tell merchants](../support/payout-delay-faq.md), which is written for that audience. Two points from this page matter for those conversations:

- the time that counts is when our settlement bank accepted the batch, not when the payout was created in Merchant Hub;
- a payout made on a Friday afternoon, or before a bank holiday, can take several calendar days while still being on time.

New sellers' payouts are also subject to a hold before they are ever batched; that is a separate question, covered in [Payout holds and releases](payout-holds.md).

## Questions we are often asked

**Why does EUR close earlier than GBP?** The SEPA cut-off is set by our settlement bank, which has to pass the files on to the SEPA clearing in time for that day's settlement. The GBP rail is domestic to the bank and gives it more room.

**Can we ask the bank for an exception?** Not for a single payout. Payouts can ask the bank to accept a late file in an emergency, but the bank decides, and has said yes twice in three years.

**Do refunds follow these cut-offs?** No. Refunds go back to the buyer's card through the card schemes and follow the schemes' settlement cycles, not ours.

**Does a held payout count as late?** No. A payout under a hold is not batched until the hold ends; the cut-offs apply from that moment.

## History

**Before 2025.** Quillmoor Payouts started in GBP only, with the 15:30 UK time cut-off it still has. EUR payouts were added later through our settlement bank's international transfer service, which settled the next business day at best, whatever the time.

**ENG-4, Multi-currency settlement.** Between October 2025 and March 2026, ENG-4 moved EUR payouts onto SEPA credit transfers, with a 14:00 CET cut-off, and taught `settlement-batcher` to keep a calendar per currency. Same-day EUR settlement dates from that work. It also introduced the `timezone` field above, after a test run showed that a cut-off configured as "14:00" with no zone would have moved by an hour at the end of March.

## Related pages

- [Payments platform architecture](platform-architecture.md), for how `payout-gateway` and `settlement-batcher` divide the work
- [Payments glossary](glossary.md), for settlement, payout and the other terms used here
- [Runbook: rolling back payout-gateway](payout-gateway-rollback.md)
- [Runbook: ledger reconciliation breaks](ledger-reconciliation.md)
