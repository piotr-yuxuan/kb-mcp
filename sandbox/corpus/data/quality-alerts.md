---
title: "Data quality alerts"
---

# Data quality alerts

Page owner: Tomasz Wilde. Framework maintained by Data Platform (`#team-data`).
Last reviewed: 2026-08-27.

Every table in `marts`, and the staging models that feed them, is checked after each
Conveyor run. Most checks are tests that fail a run outright (a duplicate key, a
negative amount); those show up as task failures in Conveyor. Three kinds of problem
are different: they are about time, volume and shape rather than about individual rows,
and they raise **alerts** with stable codes so that everyone, from the data on-call to
Finance, talks about the same thing. This page explains those three codes, where the
alerts go, how serious each one is, and how to configure checks for a new table.

The framework was built under ENG-18, the data quality alert framework epic, which
finished in ENG Sprint 17 in December 2025. Before it, each pipeline had its own
hand-written checks and its own idea of "late".

## The three codes

| Code | Name | Meaning | Blocks the run? |
|---|---|---|---|
| `DQ-017` | `FRESHNESS_BREACH` | A table missed its freshness deadline | Not applicable: the run is already late |
| `DQ-031` | `ROW_COUNT_DRIFT` | The row count of a partition is more than 25% off the 7-day median | No, unless the table opts in |
| `DQ-044` | `SCHEMA_DRIFT` | An upstream column changed type or vanished | Yes: the affected model does not run |

### DQ-017 FRESHNESS_BREACH

**What it means.** A table missed its freshness deadline: the partition that should be
complete by a given time had not been published when that time came.

**How it is computed.** Each table declares a deadline in UTC and which partition must
be ready by then, usually "yesterday" for daily tables and "the previous hour" for
hourly ones. Lantern evaluates every deadline every 5 minutes against Conveyor's
publish events. If the partition has not been published at the deadline, the alert
fires once and stays open until it is.

**Common causes.**

- Ingestion was late, so the pipeline waited and then timed out.
- A blocking test or a `DQ-044` stopped the run.
- The run was slow: a Trino worker was lost mid-run, or a backfill was competing for
  capacity outside its permitted hours.
- Conveyor itself was unavailable at the scheduled start.

**What to do.** Open the pipeline in Conveyor and find the task that is failing or
still running. Fix or retry it with `conveyor run`. Then decide how serious the delay
is, using the severity section below; for finance marts that decision is already made.

### DQ-031 ROW_COUNT_DRIFT

**What it means.** The number of rows in the partition just written is more than 25%
above or below the median of the 7 partitions before it. For hourly tables the
comparison is with the same hour on each of the 7 previous days, so that a quiet 03:00
is not compared with a busy 15:00.

The 25% threshold was set in ENG-18 after testing it against six months of history:
at 15% the alert fired on most Mondays; at 40% it missed both of the real incidents in
that period.

**How it is computed.**

```sql
-- What the check evaluates, for a daily table
with history as (
    select partition_key, row_count
    from iceberg.ops.dq_partition_stats
    where table_name = 'marts.merchant_orders_daily'
      and partition_key between date '2026-08-19' and date '2026-08-25'
)
select
    approx_percentile(row_count, 0.5) as median_7d,
    (select row_count
     from iceberg.ops.dq_partition_stats
     where table_name = 'marts.merchant_orders_daily'
       and partition_key = date '2026-08-26') as today
from history;
-- Alert when abs(today - median_7d) > 0.25 * median_7d
```

**Common causes.**

- A real change in business volume: peak trading days, a large merchant going live or
  leaving, bank holidays (the late-August bank holiday trips it on several tables
  every year).
- A partial load: ingestion committed only some of a source's rows before the run.
- A join that started duplicating or dropping rows after a model change.
- An upstream service that started or stopped emitting a kind of event.

**What to do.** Look at the shape before the number. If the drift is spread evenly
across merchants, it is probably volume; if it is concentrated in one source, one
merchant or one currency, it is probably a pipeline or upstream problem. The query at
the end of this page lists the partitions involved. For expected business events,
annotate in advance (see "Expected variance" below).

`DQ-031` warns by default and does not block the run, because a real surge in volume
is not a reason to withhold the data. A table can opt in to blocking with
`row_count.mode: block`; only `marts.payouts_hourly` does today.

### DQ-044 SCHEMA_DRIFT

**What it means.** A column that a staging model reads upstream changed type or
vanished. New columns do not raise it; nor do changes to columns we do not read.

**How it is computed.** Before each staging model runs, the framework compares the
upstream columns the model declares with the columns actually present in `raw`, and
their types. Any difference stops that model, and everything downstream of it waits.

**Common causes.** Almost always a service migration upstream: a column renamed, a
type widened from `integer` to `bigint`, a column dropped in the same release that
stopped writing it. The expand-then-contract pattern in
[Database migrations](../release/database-migrations.md) avoids nearly all of these;
when a team skips the expand step, we see it here first.

**What to do.**

1. Find the change: the alert names the source table and column, and the owning
   service's recent deploys are in Shipwright.
2. Ask the owning team in their channel whether the change is intended and final.
3. If it is, update the staging model and its declared columns in the same pull
   request, and let the run continue.
4. If it is not, ask them to restore the column; the run resumes on its own once the
   schema matches again.

Never suppress `DQ-044` to get a run through. A staging model reading a vanished column
as `null` produces a table that looks fine and is wrong.

## Where alerts go

| Table tier | Chat | Paging |
|---|---|---|
| Tier 1 (finance marts, `merchant_orders_daily`, `payouts_hourly`, `fraud_features_daily`) | `#data-alerts` | The data on-call, through Klaxon, at any hour |
| Tier 2 (other marts) | `#data-alerts` | No page; handled in business hours |
| Staging models | `#data-alerts` | Only when a tier 1 mart depends on them |

Each alert also creates an annotation on the table's panel in the Lantern dashboard
"warehouse freshness", so that anyone looking at a chart sees why a line has a gap.

A typical alert looks like this:

```text
DQ-017 FRESHNESS_BREACH  marts.finance_settlements_daily
partition 2026-08-26 not published by deadline 05:30 UTC
pipeline settlements_daily: task wait_for_ingestion running since 01:10 UTC
owner Data Platform, steward Rafael Quist
page: data/quality-alerts
```

## How serious is it?

Most data quality alerts are not incidents. A warning on a tier 2 table is handled by
its owning team in working hours, and that is the end of it.

**A late finance mart is handled as a SEV3.** When `DQ-017` fires on any table under
`marts.finance_*`, or on `marts.merchant_orders_daily`, which Finance's daily revenue
report is built on, the data on-call declares an incident with `/klaxon declare`,
selects SEV3, and works it in its own `#inc-` channel (for example `#inc-orders-late`).
Finance is told in that channel and in `#team-data`. What SEV3 entails, and how
incidents are run, is on [Production incident management](../incidents/incident-management.md);
this page does not repeat it.

Escalate above that only when the data problem has effects beyond reporting, for
example when wrong warehouse figures have already been sent to merchants or used for a
payout decision. Use the definitions on the incident management page and say why in
the incident channel.

| Alert | Table | Default handling |
|---|---|---|
| `DQ-017` | Finance mart or `merchant_orders_daily` | Incident, SEV3, led by the data on-call |
| `DQ-017` | Other tier 1 table | Page; data on-call fixes; incident only if consumers are affected |
| `DQ-017` | Tier 2 table | Owning team, next working day |
| `DQ-031` | Any | Investigate the same day; incident only if the data is wrong and in use |
| `DQ-044` | Any | Owning team of the source, same day; data on-call if a tier 1 table is held |

## Declaring checks for a table

Checks live next to the model, in `checks/`, one YAML file per table. A table without
a check file cannot be promoted to `marts`; the build refuses it.

```yaml
# checks/marts/finance_settlements_daily.yaml
table: marts.finance_settlements_daily
tier: 1
freshness:
  partition: yesterday        # or previous_hour for hourly tables
  deadline_utc: "05:30"
row_count:
  partition: yesterday
  mode: warn                  # warn (default) or block
  min_rows: 1                 # an empty partition always fails
schema:
  upstream:
    - staging.stg_settlement_batcher__files
    - staging.stg_ledger__settlement_lines
tests:
  - unique: [settlement_date, file_id, currency]
  - not_null: [settlement_date, file_id, currency, amount_minor]
```

Rules of thumb for choosing a deadline: give the pipeline at least twice its typical
runtime between the scheduled start and the deadline, and ask the consumers when they
actually need the data rather than picking a round number.

## Expected variance

When you know volume will move, say so before it happens. An annotation suppresses
`DQ-031` for the named partitions of the named tables and is visible in Lantern:

```yaml
# checks/annotations/2026-11-peak.yaml
reason: Peak trading weekend; volumes expected well above median
tables:
  - marts.merchant_orders_daily
  - marts.payouts_hourly
partitions:
  from: "2026-11-27"
  to: "2026-11-30"
expires: "2026-12-07"
author: rafael.quist
```

Annotations apply to `DQ-031` only. There is no way to annotate away `DQ-017` or
`DQ-044`, by design.

## Finding past alerts

All check results, passed or failed, are written to `ops.dq_results`:

```sql
select
    evaluated_at,
    table_name,
    partition_key,
    code,
    detail
from iceberg.ops.dq_results
where code in ('DQ-017', 'DQ-031', 'DQ-044')
  and evaluated_at > current_timestamp - interval '30' day
order by evaluated_at desc;
```

To see which merchants explain a row count drift on `merchant_orders_daily`:

```sql
select merchant_id, count(*) as rows_today
from iceberg.marts.merchant_orders_daily
where order_date = date '2026-08-26'
group by merchant_id
order by rows_today desc
limit 20;
```

## A worked example

On the morning of 27 August 2026, `DQ-031` fired on `marts.merchant_orders_daily`:
the partition for 26 August had 31% fewer rows than its 7-day median. Nothing else
was wrong. The run had finished at 02:41 UTC, the ledger agreement test had passed and
Finance's revenue total for the day looked normal.

The data on-call worked through it in this order:

1. **Shape.** The merchant query below showed that the drop was not spread across
   merchants. Almost all of it came from a single marketplace whose sellers had
   produced around 9,000 rows a day and now produced about 40.
2. **Upstream.** Volume in Lantern for that marketplace's authorisations was flat, so
   the payments had happened. The rows were missing, or had moved.
3. **Moved.** A search by `marketplace_id` found the missing volume under new
   `merchant_id` values: the marketplace had moved its sellers to a new account
   structure the day before. Each new merchant had one row per currency rather than
   one per seller, so the row count fell while amounts stayed the same.
4. **Decision.** No data was wrong and no consumer was affected. The on-call posted the
   explanation in the alert's thread in `#data-alerts`, told Merchant Support, whose
   "top merchants" view had changed overnight, and closed the alert.

Two lessons from that morning made it into this page: look at the shape before the
number, and check amounts as well as counts. A row-count drift with stable amounts is
usually a change in grain upstream, not lost data.

## Questions

**An alert fired during a backfill. Is that real?** Historical partitions are checked
too, with the differences listed on [Backfilling historical partitions](backfills.md).
`DQ-044` during a backfill is always real.

**Can I change the 25% threshold for my table?** Not per table. If the threshold does
not suit a table, it usually means the table's grain is too coarse or too fine for a
row count to be meaningful; set `mode: warn` and talk to Data Platform.

**Who fixes a `DQ-044` caused by another team?** They do, with our help. We will patch
the staging model to keep tier 1 tables flowing, but the decision about the column is
theirs.

**Where are the on-call expectations for these pages?** On
[Data platform on-call](data-on-call.md).
