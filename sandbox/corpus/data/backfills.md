---
title: "Backfilling historical partitions"
---

# Backfilling historical partitions

*Maintained by Hana Ostrowska for Data Platform. Last reviewed 2026-10-14. Questions in
`#team-data`.*

A backfill builds, or builds again, the historical partitions of a Conveyor pipeline
with the pipeline's current code. You need one whenever last night's run is not enough:
a fix to a model's logic, a new column that should exist for past days, source data
that was corrected after the fact, or a new pipeline that needs history before anyone
can use it.

This page explains when to backfill, the two hard limits Conveyor enforces, and the
procedure we expect everyone to follow, including how to check the result.

> [!IMPORTANT]
> Two rules are enforced by Conveyor and cannot be waived:
>
> 1. **At most 31 partitions per run.** Longer ranges are split into several backfills.
> 2. **Never between 00:00 and 06:00 UTC.** That window belongs to the scheduled
>    nightly pipelines.

## Do you need a backfill?

| Situation | What to do |
|---|---|
| Last night's partition failed and you have fixed the cause | Not a backfill: `conveyor run PIPELINE --partition DATE` for that one partition |
| You changed a model's logic and past partitions are now wrong | Backfill the affected range |
| You added a column and consumers want it for past days | Backfill the range they need, not all of history |
| An upstream team corrected source data for a period | Backfill the period once the correction has reached `raw` |
| A new pipeline needs history before launch | Backfill in monthly ranges, oldest first |
| Captures or settlement lines arrived more than a week late | Backfill the month after it closes, agreed with Finance |
| The source data itself is wrong and not yet corrected | Not yet: a backfill would copy the error faithfully |

If you are not sure whether the change affects past partitions, run a dry run (below);
it costs nothing and tells you which partitions would change.

## Why these limits

**31 partitions per run.** A partition of a daily pipeline is one day, so 31 partitions
cover any calendar month. Before the cap, one backfill over two years of
`fraud_features_daily` held most of the Trino cluster for nine hours, wrote one enormous
Iceberg commit and left nothing to restore to halfway through. Capping each run keeps
commits small, lets the scheduler interleave other work, and means that a mistake costs
at most a month to put right. The cap shipped as part of ENG-20, the Conveyor backfill
tooling epic.

Note that the cap counts partitions, not days. For an hourly pipeline such as
`payouts_hourly`, 31 partitions are 31 hours, a little over a day.

**Nothing between 00:00 and 06:00 UTC.** The nightly pipelines run in that window and
have deadlines at its end: `merchant_orders_daily` must be ready by 06:00 UTC for
Finance. They need the whole of Trino's batch capacity to make it on a busy night.
Conveyor refuses to start a backfill in the window, and a backfill still running at
00:00 UTC is suspended after its current partition and resumes by itself at 06:00 UTC.
Plan long backfills so that they finish in the working day; it is easier to check the
result when you are awake.

## Before you start

Check these, in order:

1. **You own the pipeline, or its steward agreed.** The steward is listed in the data
   catalogue (see [Data catalogue and table ownership](table-ownership.md)).
2. **Finance agreed, for finance marts.** Backfilling a closed month changes figures
   Finance may already have reported. Do not touch a finance mart during the
   [month-end close](../finance/month-end-close.md) without their agreement in writing
   in `#team-data`.
3. **No other backfill of the same pipeline is running.** Conveyor allows one at a time
   per pipeline; check with `conveyor backfill list --pipeline PIPELINE`.
4. **The fix is merged and deployed.** A backfill runs the deployed code, not your
   branch.
5. **You know which downstream tables depend on this one.** The dry run lists them.

## Procedure

### 1. Choose and count the range

Ranges are inclusive at both ends and use partition keys: dates for daily pipelines
(`2026-01-01`), hours for hourly ones (`2026-09-28T14`). January 2026 is exactly 31
partitions, so it fits in one run; the first quarter of 2026 needs three.

### 2. Dry run

```bash
conveyor backfill merchant_orders_daily --from 2026-01-01 --to 2026-01-31 --dry-run
```

The dry run prints the partitions it would build, an estimate of the data each would
scan, the downstream pipelines that read the table, and, for each partition, whether
the new code would change any row. Save the output; you will attach it to your
announcement.

```text
backfill plan: merchant_orders_daily
  partitions:        31 (2026-01-01 .. 2026-01-31)
  estimated scan:    412 GiB
  estimated runtime: 2 h 40 min at max-parallel 2
  partitions changed by current code: 31 of 31
  downstream:        none scheduled; ad hoc readers: finance revenue report
  nightly window:    clear (start before 21:20 UTC to finish before 00:00 UTC)
```

If the plan says that no partition would change, stop: your change does not need a
backfill.

### 3. Announce

Post in `#team-data`, and in the owning team's channel if the table is not ours:

```text
Backfill: merchant_orders_daily, 2026-01-01 to 2026-01-31 (31 partitions)
Why: fix for refunds counted twice on days with no orders
Start: today 10:00 UTC, expected end 12:45 UTC
Downstream: none scheduled; Finance revenue report figures for January will change
Agreed with: Rafael Quist (steward), Finance in this channel
Dry run: attached
```

### 4. Start it

```bash
conveyor backfill merchant_orders_daily --from 2026-01-01 --to 2026-01-31
```

Conveyor answers with a backfill identifier such as `bf-20261014-0931`. Two options
are worth knowing:

- `--max-parallel N` builds up to N partitions at once. The default is 2 and the
  ceiling is 4; above 2, ask in `#team-data` first, as it competes with everyone's
  queries.
- `--include-downstream` queues backfills of the downstream pipelines for the same
  range once this one succeeds. Use it when downstream tables are derived purely from
  this one; otherwise backfill them yourself in order.

### 5. Watch it

```bash
conveyor backfill status bf-20261014-0931
conveyor backfill logs bf-20261014-0931 --partition 2026-01-17
```

Quality checks run on every partition, as they do on a scheduled run, with two
differences: freshness (`DQ-017`) is not evaluated for historical partitions, and the
row-count check (`DQ-031`) compares each partition with the days before it in the
backfilled history, not with this week. A `DQ-044` schema alert still blocks the
partition. The codes are explained in [Data quality alerts](quality-alerts.md).

A failed partition does not stop the others. When the backfill ends, failed partitions
are listed in the status output; fix the cause and start a new backfill for those
partitions only.

### 6. Check the result

Every partition the backfill wrote is a new Iceberg snapshot, so you can compare the
table before and after. Take the snapshot identifier from just before your backfill
started:

```sql
select snapshot_id, committed_at
from iceberg.marts."merchant_orders_daily$snapshots"
where committed_at < timestamp '2026-10-14 10:00:00 UTC'
order by committed_at desc
limit 1;
```

Then compare totals per day:

```sql
with before as (
    select order_date, sum(refunded_amount_minor) as refunded_minor
    from iceberg.marts.merchant_orders_daily for version as of 7841230095512647721
    where order_date between date '2026-01-01' and date '2026-01-31'
    group by order_date
),
after as (
    select order_date, sum(refunded_amount_minor) as refunded_minor
    from iceberg.marts.merchant_orders_daily
    where order_date between date '2026-01-01' and date '2026-01-31'
    group by order_date
)
select
    b.order_date,
    b.refunded_minor as before_minor,
    a.refunded_minor as after_minor,
    a.refunded_minor - b.refunded_minor as delta_minor
from before as b
join after as a on a.order_date = b.order_date
order by b.order_date;
```

The deltas should match what you expected from the fix and nothing else. A change in a
column you did not touch means something else changed between the original run and
now, usually late source data, and is worth understanding before you announce success.

### 7. Close it

Reply to your announcement with the result, the backfill identifier and anything
unexpected. If Finance figures changed, say by how much for the month in total.

## Ranges longer than 31 partitions

Split the range into calendar months and start them one after another, oldest first.
Conveyor does not yet split ranges for you; automatic splitting is the part of ENG-20
still in progress in ENG Sprint 40. Until it ships, this loop does the job and stops
cleanly before the nightly window:

```bash
#!/usr/bin/env bash
# Backfill merchant_orders_daily for 2025-10 to 2026-03, one month per run.
set -euo pipefail

for month in 2025-10 2025-11 2025-12 2026-01 2026-02 2026-03; do
  first="${month}-01"
  last="$(date -u -d "${first} +1 month -1 day" +%F)"

  hour="$(date -u +%H)"
  if (( 10#${hour} >= 21 )); then
    echo "Too close to the nightly window; resume tomorrow from ${month}." >&2
    exit 1
  fi

  conveyor backfill merchant_orders_daily \
    --from "${first}" --to "${last}" --wait
done
```

`--wait` makes the command return only when that backfill has finished, so the months
never overlap. For hourly pipelines, split by day instead: 24 partitions per run.

## When a backfill went wrong

If the result is wrong, put the table back as it was before your backfill started, then
work out what happened. Iceberg keeps the earlier snapshot; restoring it is a metadata
operation and takes seconds:

```sql
alter table iceberg.marts.merchant_orders_daily
    execute rollback_to_snapshot(7841230095512647721);
```

Restoring discards every commit since that snapshot, including any scheduled run that
happened in between, so check the snapshot list first and, if a nightly run committed
since, build that partition again afterwards with `conveyor run`. Tell `#team-data` and
the steward before you restore anything.

## Erased subjects stay erased

Backfills read from `staging`, which filters out every subject in
`privacy.erasure_log`, and the erasure job also scrubs `raw`. A backfill therefore
cannot bring back a subject who has been erased, provided it reads only from the
warehouse. Never backfill from an export, a file on your laptop or an old copy of a
table: that is the one way to undo an erasure. See
[Erasure requests in the warehouse](erasure-requests.md).

## Cost

A month of `merchant_orders_daily` scans about 400 GiB. Backfills are charged to the
owning team's cost centre like any other query. If your dry run estimates more than
5 TiB in total, talk to Data Platform first; there is usually a cheaper way, such as
building only the new column. More in [Keeping warehouse queries cheap](query-costs.md).

## Checklist

Copy this into your announcement thread and tick it off as you go:

```text
[ ] Fix merged and deployed; backfill runs deployed code
[ ] Steward agreed (and Finance, for a finance mart)
[ ] No other backfill of this pipeline running
[ ] Range counted: 31 partitions or fewer per run
[ ] Start time outside 00:00 to 06:00 UTC, with time to finish before midnight
[ ] Dry run saved and attached
[ ] Announced in #team-data
[ ] Snapshot identifier noted from before the start
[ ] Result compared with the earlier snapshot
[ ] Downstream tables handled, or explicitly not needed
[ ] Result posted in the thread
```

## Questions people ask

**Can I backfill at the weekend?** Yes, outside the nightly window, but tell the data
on-call in `#team-data` first; they will be the ones paged if it goes wrong. See
[Data platform on-call](data-on-call.md).

**Can I raise the cap for one run?** No. Split the range. The cap is not a setting.

**Can I backfill a table I do not own?** Only with its steward's agreement, recorded in
the channel.

**I started a backfill at 23:50 UTC and it stopped.** It was suspended at 00:00 UTC
after the partition it was building, and will resume at 06:00 UTC. You do not need to
do anything; next time, start earlier.

**Does a backfill trigger alerts downstream?** Only if you use `--include-downstream`,
in which case each downstream backfill runs its own checks.

**Do I need a backfill for a column that only consumers of recent data use?** Not
necessarily. If nobody needs the column before a given date, document that date in the
table's description and backfill nothing. Empty history is better than history nobody
asked for and everybody pays for.

**Can two different pipelines be backfilled at the same time?** Yes, if they do not
depend on each other. Keep the total of `--max-parallel` across them at 4 or less.
