---
title: "Writing a Conveyor DAG"
---

# Writing a Conveyor DAG

*A walkthrough by Hana Ostrowska. Last reviewed 2026-09-24.*

This page takes you from an idea for a new mart to a scheduled pipeline. It assumes you
have read the [Data platform overview](platform-overview.md) and have a clone of the
`data-pipelines` repository. The running example is a tier 2 mart of refund rates per
merchant, `marts.merchant_refund_rates_daily`.

## The four files

A pipeline is four files, all in `data-pipelines`, plus a fixture test (step 5):

```text
dags/merchant_refund_rates_daily.py          the DAG: tasks, schedule, partition
models/marts/merchant_refund_rates_daily.sql the SQL that builds one partition
checks/marts/merchant_refund_rates_daily.yaml quality checks and freshness deadline
catalogue/owners.yaml                         one new entry: owner and steward
```

Names follow [Warehouse naming conventions](naming-conventions.md): the pipeline takes
the mart's name.

## 1. The DAG

```python
from conveyor import Pipeline, Sensor, SqlTask, daily

pipeline = Pipeline(
    name="merchant_refund_rates_daily",
    owner="team-data",
    schedule=daily(at="03:15"),  # UTC
    partition="date",  # one partition per UTC day
    tier=2,
    retries=2,
    retry_delay_minutes=10,
)

wait = Sensor(
    "wait_for_orders",
    pipeline=pipeline,
    upstream="merchant_orders_daily",  # waits for the same partition to publish
    timeout_minutes=120,
)

build = SqlTask(
    "build_mart",
    pipeline=pipeline,
    model="models/marts/merchant_refund_rates_daily.sql",
    write="overwrite_partition",
)

wait >> build
```

Conveyor adds the `quality_checks` and `publish` tasks itself, from the checks file.

## 2. The model

The model builds exactly one partition. Conveyor passes it `{{ partition }}`, the
partition's date, and the model must use nothing else to decide which data to read.

```sql
select
    o.order_date,
    o.merchant_id,
    o.currency,
    sum(o.refunded_amount_minor) as refunded_amount_minor,
    sum(o.captured_amount_minor) as captured_amount_minor,
    cast(sum(o.refunded_amount_minor) as double)
        / nullif(sum(o.captured_amount_minor), 0) as refund_ratio
from marts.merchant_orders_daily as o
where o.order_date = date '{{ partition }}'
group by o.order_date, o.merchant_id, o.currency
```

Write it in the house style; see the [SQL style guide](sql-style-guide.md).

## 3. The checks

```yaml
table: marts.merchant_refund_rates_daily
tier: 2
freshness:
  partition: yesterday
  deadline_utc: "09:00"
row_count:
  partition: yesterday
  mode: warn
tests:
  - unique: [order_date, merchant_id, currency]
  - not_null: [order_date, merchant_id, currency]
```

The codes these checks can raise, and where they go, are on
[Data quality alerts](quality-alerts.md).

## 4. Try it before review

Build one partition into `scratch`, under your user name; nothing else is touched:

```bash
conveyor run merchant_refund_rates_daily --partition 2026-09-20 --target scratch
conveyor run merchant_refund_rates_daily --partition 2026-09-20 --target scratch --checks-only
```

Then a dry-run backfill over the last 31 days, to see the cost and the shape:

```bash
conveyor backfill merchant_refund_rates_daily --from 2026-08-21 --to 2026-09-20 \
    --dry-run --target scratch
```

## 5. Add a fixture test

Checks catch problems in real data; a fixture test catches mistakes in your logic before
any real data is involved. Put a few hand-written input rows and the output you expect
in `tests/fixtures/`, named after the pipeline:

```yaml
# tests/fixtures/merchant_refund_rates_daily.yaml
partition: "2026-09-20"
inputs:
  marts.merchant_orders_daily:
    - {order_date: "2026-09-20", merchant_id: mer_a, currency: GBP,
       captured_amount_minor: 10000, refunded_amount_minor: 500}
    - {order_date: "2026-09-20", merchant_id: mer_b, currency: EUR,
       captured_amount_minor: 0, refunded_amount_minor: 200}
expected:
  - {merchant_id: mer_a, currency: GBP, refund_ratio: 0.05}
  - {merchant_id: mer_b, currency: EUR, refund_ratio: null}
```

```bash
conveyor test merchant_refund_rates_daily
```

The second row is the interesting one: a merchant with refunds and no captures that day
must give `null`, not a division error. Write at least one fixture row for every edge
case you can think of, because that is where reviewers will look.

## 6. Review and release

Open a pull request with the dry-run output attached. One reviewer from Data Platform is
required; if the mart reads personal data, the columns must be tagged first (see
[Tagging personal data columns](personal-data-columns.md)). After merge, Shipwright
deploys the DAG and Conveyor schedules it from the next day. Fill the history with a
backfill, following [Backfilling historical partitions](backfills.md).

## Hourly pipelines

An hourly pipeline differs in three places: `schedule=hourly(at_minute=20)`,
`partition="hour"`, and a model that filters on `{{ partition_start }}` and
`{{ partition_end }}` rather than on a single date. The freshness deadline in the
checks file uses `partition: previous_hour`. Keep hourly pipelines small: a run that
takes more than 20 minutes will soon overlap the next one, and Conveyor will skip the
later run rather than run two at once.

## What reviewers look for

These are the comments that come up most often in review, roughly in order:

| Comment | What to change |
|---|---|
| "This reads the clock" | Replace `current_date` with the partition |
| "No grain in the name" | Rename to end in `_daily`, `_hourly` or `_current` |
| "Who owns this?" | Add the entry to `catalogue/owners.yaml` |
| "These columns look personal" | Tag them in the model's column file |
| "Deadline too tight" | Move the schedule earlier or the deadline later |
| "Where is the dry run?" | Attach the dry-run output to the pull request |
| "`select *`" | List the columns |

## Rules that catch people out

- **No `current_date` or `now()` in a model's logic.** A model that reads the clock
  gives a different answer every time it runs, and backfills become meaningless. The one
  exception is an audit column such as `built_at`, which records when the partition was
  written and is never used to select or compute anything.
- **Overwrite, never append.** A partition written twice must end up the same as a
  partition written once.
- **Depend on publishes, not on times.** Use a `Sensor` on the upstream pipeline rather
  than scheduling "a bit later and hoping".
- **Pick the schedule from the deadline backwards.** Allow at least twice the typical
  runtime, plus the sensor's timeout, before the freshness deadline.
- **Tier 1 is not self-service.** Tier 1 pipelines page someone at night; Tomasz Wilde
  approves every one.
