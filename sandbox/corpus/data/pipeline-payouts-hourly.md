---
title: "Pipeline: payouts_hourly"
---

# Pipeline: payouts_hourly

Steward: Hana Ostrowska (Data Platform). Business owner: Yusuf Achterberg, Payouts team
lead. Last reviewed 2026-09-08.

`payouts_hourly` summarises, for every hour, the payouts that `payout-gateway` sent to
marketplace sellers and what happened to them: how many were created, sent, confirmed
by our settlement bank or returned, and for how much, in GBP and EUR. It is the
warehouse view of payouts. It is not the place to look when payouts are stuck right
now; that is a live problem for the Payouts on-call, and the warehouse is at least an
hour behind.

## At a glance

| | |
|---|---|
| Output | `marts.payouts_hourly` |
| Partition | `payout_hour`, one UTC hour, such as `2026-09-28T14` |
| Schedule | Every hour at 20 minutes past, for the previous hour |
| Freshness deadline | 50 minutes past the hour, for the previous hour |
| Tier | 1 |
| Sources | `staging.stg_payout_gateway__payouts`, `staging.stg_payout_gateway__batches`, `staging.stg_settlement_batcher__files` |
| Typical runtime | 4 to 7 minutes |

## Columns

| Column | Meaning |
|---|---|
| `payout_hour` | Hour in which the payout was created by `payout-gateway` |
| `currency` | `GBP` or `EUR` |
| `batches_count` | Batches sent in that hour; four on a normal hour, as batches go every 15 minutes |
| `payouts_created` | Payouts created |
| `payouts_sent` | Payouts included in a batch sent to the bank |
| `payouts_confirmed` | Payouts the bank has confirmed so far |
| `payouts_returned` | Payouts returned by the bank, for example for a closed account |
| `amount_sent_minor` | Total sent, in minor units of `currency` |
| `amount_returned_minor` | Total returned, in minor units |
| `median_seconds_to_confirm` | Median time from batch sent to bank confirmation |

Confirmations and returns trickle in for days, so each run rebuilds the previous hour
and refreshes the 72 hours before it. A return that arrives later than that appears only
after a backfill.

## Quality checks

The checks follow the framework on [Data quality alerts](quality-alerts.md), with two
local choices:

- `payouts_hourly` is the one table where `DQ-031` blocks the run instead of warning.
  A sudden drop in payout rows has twice meant that ingestion from `payout-gateway` was
  silently stalled, and the Payouts team prefers a late table to a wrong one.
- Hours whose 7-day median is under 200 payouts are exempt from `DQ-031`, through
  `row_count.min_median_rows: 200`. Overnight volume is too low for a percentage to mean
  much.

A test also checks that `payouts_sent` never exceeds `payouts_created` for the same
hour and currency.

## Who uses it

- **Payouts**: the "payouts by hour" dashboard in Lantern, for trends and capacity
  planning. Oskar Ngata uses it for the product metrics in the payouts review.
- **Finance**: the treasury view of cash leaving our settlement bank, day by day.
- **Merchant Support**: answering "when did my payouts slow down?" after the event.

## Backfills

Partitions are hours, so the backfill limit of 31 partitions per run covers 31 hours. A
day at a time is the usual unit:

```bash
conveyor backfill payouts_hourly --from 2026-09-28T00 --to 2026-09-28T23 --dry-run
```

The rest of the procedure is on [Backfilling historical partitions](backfills.md).

## Planned change

We intend to move the grain to 15 minutes so that each row matches one batch. It is not
scheduled yet; the open question is whether the Lantern dashboards can cope with four
times the rows. Comments to `#team-data`.
