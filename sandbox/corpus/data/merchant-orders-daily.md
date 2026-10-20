---
title: "Pipeline: merchant_orders_daily"
---

# Pipeline: merchant_orders_daily

| | |
|---|---|
| Conveyor pipeline | `merchant_orders_daily` |
| Output table | `marts.merchant_orders_daily` |
| Schedule | Every day at 01:30 UTC |
| Ready by | 06:00 UTC (the freshness deadline) |
| Partition | `order_date`, one UTC calendar day |
| Owning team | Data Platform (`#team-data`) |
| Steward | Rafael Quist |
| Business owner | Arjun Pelletier, finance director, for the daily revenue report |
| Tier | 1: pages the data on-call out of hours |
| Last reviewed | 2026-10-06, by Rafael Quist |

`merchant_orders_daily` is the warehouse's daily summary of what every merchant sold:
how many orders, how much was authorised and captured, how much was refunded, in the
original currency and converted to GBP. It is the most widely read table we have, and
the one Finance's daily revenue report is built on, so it is also the one with the
tightest deadline.

## Who reads it

| Consumer | What they use | When they need it |
|---|---|---|
| Finance | The daily revenue report, sent by email at 08:00 UK time | Complete by 06:00 UTC |
| Finance | Month-end revenue figures for the close | First working days of the month |
| Product | The merchant health dashboard in Lantern | During the working day |
| Merchant Support | The "top merchants by volume" view used to spot unusual drops | During the working day |
| Risk Operations | Merchant volume trends when reviewing a merchant's risk profile | Ad hoc |

Because of the first line of that table, a late `merchant_orders_daily` is a late
finance mart, and is handled as described in [Data quality alerts](quality-alerts.md).

## History

The pipeline was rebuilt under ENG-17, finished in ENG Sprint 9 (August 2025). Before
the rebuild it was a single 900-line query that started at 04:00 UTC, took up to an
hour and three quarters on busy days and missed the deadline about twice a month,
usually after a slow night in ingestion. The rebuild split the query into the tasks
below, made each task write a partition idempotently, and moved the run to 01:30 UTC,
as soon as the night's ingestion is reliably committed. Typical runtime is now 50 to
60 minutes, so a normal night has the table ready by about 02:30 UTC, with three and a
half hours of margin for a retry.

The one significant miss since then is described in the
[incident report of 2026-05-20](../incidents/report-2026-05-20-orders-late.md); its
actions are tracked there.

## What a row means

The grain is **one row per merchant, per `order_date`, per currency**. An order is a
payment authorised by `card-auth` that carries an order reference from `merchant-api`.

| Column | Type | Meaning |
|---|---|---|
| `order_date` | `date` | UTC calendar date on which the payment was authorised |
| `merchant_id` | `varchar` | Quillmoor merchant identifier, `mer_` followed by 20 characters |
| `marketplace_id` | `varchar` | The marketplace the merchant sells through |
| `currency` | `varchar(3)` | ISO 4217 code of the payment's presentment currency |
| `orders_count` | `bigint` | Orders authorised that day |
| `authorised_amount_minor` | `bigint` | Sum of authorised amounts, in minor units of `currency` |
| `captured_amount_minor` | `bigint` | Sum captured so far against those orders |
| `refunded_amount_minor` | `bigint` | Refunds **processed on that date**, whatever the order's date |
| `declined_count` | `bigint` | Authorisations declined that day, by the issuer or by `risk-scorer` |
| `gross_amount_gbp_minor` | `bigint` | `captured_amount_minor` converted to GBP pence |
| `fx_rate_source` | `varchar` | `fx-quote` when the quote stored at authorisation was used; `daily-close` otherwise |
| `built_at` | `timestamp(6) with time zone` | When the partition was last written |

Amounts are integers in minor units, following
[ADR-017](../architecture/adr-017-money-minor-units.md). Never sum amounts across
currencies; use `gross_amount_gbp_minor` for cross-currency totals.

### Three things that surprise people

1. **Days are UTC.** A payment made at 00:30 in Paris in summer belongs to the
   previous `order_date`. Merchant Hub shows merchants their local day, so its numbers
   will not match this table at the edges of the day. This is expected.
2. **Refunds are counted on the day they are processed.** A refund on 3 October against
   an order of 14 September adds to the 3 October row, not to the 14 September one.
   This keeps old partitions stable; the price is that `captured_amount_minor -
   refunded_amount_minor` for a single day is not "net sales of that day's orders".
3. **Captures catch up for a week.** Most captures arrive within minutes of
   authorisation, but some merchants capture on dispatch. Each run therefore rebuilds
   the target day and the six days before it. A capture arriving more than seven days
   after authorisation reaches the table only through a backfill; Finance's month-end
   process asks for one (see below).

## How the run works

The DAG has eight tasks. Each writes or checks exactly one partition, so any task can
be retried without side effects.

```text
wait_for_ingestion
      |
      +--> stg_orders ------+
      +--> stg_captures ----+--> build_mart --> quality_checks --> publish
      +--> stg_refunds -----+
      +--> fx_to_gbp -------+
```

| Task | What it does | Typical duration |
|---|---|---|
| `wait_for_ingestion` | Waits until the `raw` loads of `card-auth`, `merchant-api` and `ledger` have committed a watermark past 00:45 UTC | 0 to 10 minutes |
| `stg_orders` | Refreshes `staging.stg_merchant_api__orders` for the seven-day window | 6 minutes |
| `stg_captures` | Refreshes `staging.stg_ledger__captures` | 9 minutes |
| `stg_refunds` | Refreshes `staging.stg_ledger__refunds` | 4 minutes |
| `fx_to_gbp` | Joins each captured payment to its `fx-quote` quote, or to the daily closing rate, in `staging.int_merchant_orders_daily__fx_to_gbp` | 7 minutes |
| `build_mart` | Overwrites the seven partitions of `marts.merchant_orders_daily` | 15 minutes |
| `quality_checks` | Runs the checks below against the new snapshot | 3 minutes |
| `publish` | Marks the partition ready in Conveyor and posts to `#data-alerts` | Seconds |

`wait_for_ingestion` gives up at 04:30 UTC. If ingestion has not committed by then, the
task fails, the data on-call is paged, and the problem is upstream of this pipeline.

`build_mart` runs the model below and Conveyor replaces the seven partitions with its
result in a single Iceberg commit, so readers see either the old seven days or the new
seven days, never a mixture:

```sql
-- models/marts/merchant_orders_daily.sql, simplified
select
    o.order_date,
    o.merchant_id,
    o.marketplace_id,
    o.currency,
    count_if(not o.declined)                   as orders_count,
    sum(if(o.declined, 0, o.authorised_amount_minor))
                                               as authorised_amount_minor,
    coalesce(sum(c.captured_amount_minor), 0)  as captured_amount_minor,
    coalesce(max(r.refunded_amount_minor), 0)  as refunded_amount_minor,
    count_if(o.declined)                       as declined_count,
    coalesce(sum(f.gross_amount_gbp_minor), 0) as gross_amount_gbp_minor,
    max(f.fx_rate_source)                      as fx_rate_source,
    current_timestamp                          as built_at
from staging.stg_merchant_api__orders as o
left join staging.stg_ledger__captures as c
    on c.order_id = o.order_id
left join staging.int_merchant_orders_daily__fx_to_gbp as f
    on f.order_id = o.order_id
left join staging.int_merchant_orders_daily__refunds_by_day as r
    on r.merchant_id = o.merchant_id
   and r.currency = o.currency
   and r.refund_date = o.order_date
where o.order_date between date '{{ window_start }}' and date '{{ partition }}'
group by 1, 2, 3, 4
```

The snippet above leaves out the handling of merchants that refunded on a day with no
orders, which is done with a second union branch.

## Quality checks

The checks are declared in `checks/marts/merchant_orders_daily.yaml` and evaluated by
the framework described in [Data quality alerts](quality-alerts.md). The codes are
explained there; this table says what they mean for this pipeline.

| Check | What fails it | Code or effect | Blocks `publish`? |
|---|---|---|---|
| Freshness | Partition for yesterday not published by 06:00 UTC | `DQ-017` | Not applicable |
| Row count | Yesterday's row count far from its recent median | `DQ-031` | No: warns only |
| Upstream schema | A column used from `stg_merchant_api__orders`, `stg_ledger__captures` or `stg_ledger__refunds` changed type or vanished | `DQ-044` | Yes |
| Unique key | Two rows share `order_date`, `merchant_id` and `currency` | Task failure | Yes |
| Non-negative amounts | Any amount column below zero | Task failure | Yes |
| Known currency | `currency` not in the reference list | Task failure | Yes |
| Ledger agreement | GBP `captured_amount_minor` for the day differs from the ledger's captured total by more than 0.1% | Task failure | Yes |

```yaml
# checks/marts/merchant_orders_daily.yaml (excerpt)
table: marts.merchant_orders_daily
tier: 1
freshness:
  partition: yesterday
  deadline_utc: "06:00"
row_count:
  partition: yesterday
  mode: warn
schema:
  upstream:
    - staging.stg_merchant_api__orders
    - staging.stg_ledger__captures
    - staging.stg_ledger__refunds
tests:
  - unique: [order_date, merchant_id, currency]
  - non_negative: [authorised_amount_minor, captured_amount_minor, refunded_amount_minor]
  - accepted_values: {column: currency, ref: staging.stg_fx_quote__currencies}
  - ledger_agreement: {currency: GBP, tolerance_ratio: 0.001}
```

The ledger agreement check is the one that most often fails for a real reason: it has
caught a duplicated capture event twice and a missing replication slot once. When it
fails, do not loosen the tolerance to get the table out; tell Finance the report will be
late and find the cause.

## When it goes wrong

### The run failed before 06:00 UTC

1. Open the run in Conveyor and read the failed task's log. Most failures are a
   timeout in `wait_for_ingestion` or a blocking check.
2. If the cause was transient (a Trino worker restarted, a lock on a staging table),
   start the run again for the same partition:

   ```bash
   conveyor run merchant_orders_daily --partition 2026-10-05
   ```

3. If a blocking check failed, fix the cause, not the check. For `DQ-044`, the
   upstream team almost certainly shipped a migration; ask in their channel and pin our
   staging model to the old column with a cast until they confirm.
4. Post what you did in `#team-data`, in the thread under the failure alert.

### It will miss 06:00 UTC

As soon as you know, tell Finance in `#team-data` (they watch it from 07:00 UK time)
that the revenue report will be late and when you expect the table. Then follow the
severity guidance in [Data quality alerts](quality-alerts.md): a late finance mart is
handled as an incident of its own, with its own channel, and the data on-call leads it
until handover.

Useful query to see where each recent partition stands:

```sql
select
    partition_key,
    state,
    started_at,
    finished_at,
    date_diff('minute', started_at, finished_at) as minutes
from iceberg.ops.conveyor_runs
where pipeline = 'merchant_orders_daily'
  and started_at > current_timestamp - interval '10' day
order by started_at desc;
```

### Numbers look wrong but the checks passed

Compare with the previous snapshot before changing anything. If yesterday's numbers
moved overnight, the seven-day rebuild is the usual explanation (late captures).

```sql
select snapshot_id, committed_at, summary['added-records'] as added
from iceberg.marts."merchant_orders_daily$snapshots"
order by committed_at desc
limit 10;
```

## Historical partitions

Older partitions are filled or corrected with a backfill, never by editing the table.
Finance asks for one each month, after the month-end close, to pick up captures that
arrived more than a week late:

```bash
conveyor backfill merchant_orders_daily --from 2026-09-01 --to 2026-09-30 --dry-run
```

The limits on range and timing, and how to check the result, are on
[Backfilling historical partitions](backfills.md). Agree the timing with Finance first,
so that a backfill does not change figures they have already reported.

## Frequently asked

**Are test merchants included?** No. Merchants flagged `is_test_merchant` in
`staging.stg_merchant_api__merchants` are excluded in `stg_orders`, so the sandbox
accounts described in [Test merchants and test cards](../payments/test-merchants.md)
never appear in the table or in Finance's figures.

**Why is `fx_rate_source` sometimes `daily-close`?** A small share of payments, mostly
from merchants on older integrations, were authorised without an `fx-quote` quote being
stored against them. For those, `fx_to_gbp` uses the day's closing rate. The column lets
Finance see how much of a day's GBP total depends on it; on a normal day it is well
under 1%.

**Why did a merchant's row for last Tuesday change this morning?** Because each run
rebuilds the last seven days to pick up late captures. Partitions older than that only
change through a backfill.

**Can I join this table to individual orders?** Not directly: the grain is a merchant's
day. For order-level questions, ask for `staging_reader` and use
`staging.stg_merchant_api__orders`, or ask in `#team-data` whether an order-level mart
would serve more people than you.

**Why GBP and not EUR for the converted total?** Quillmoor reports in GBP. A EUR view
for the Paris office's reporting is on the wish list but not scheduled.

## Changing the pipeline

- Changes to columns or grain need a heads-up to the consumers listed above, at least
  one sprint ahead, in `#team-data` and by email to `finance@quillmoor.example`.
- New columns are added at the end; a column is never renamed in place. Add the new
  one, populate it by backfill, move consumers, then drop the old one.
- Every change ships with a dry-run backfill over the last 31 days, compared with the
  current table, attached to the review.
- The steward approves changes to the model; Tomasz Wilde approves changes to the
  freshness deadline or the tier.

Related: [Data platform overview](platform-overview.md),
[Writing a Conveyor DAG](writing-a-dag.md),
[Data catalogue and table ownership](table-ownership.md).
