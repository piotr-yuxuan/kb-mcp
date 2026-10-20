---
title: "Keeping warehouse queries cheap"
---

# Keeping warehouse queries cheap

Last reviewed 2026-09-02 by Rafael Quist.

Trino reads data files from object storage, and what we pay for, in compute and in
other people's waiting time, is mostly how much it reads. A query that scans a year of
`raw` to count yesterday's orders costs a hundred times what it should and slows down
everyone's dashboards while it runs. Most expensive queries are expensive by accident.
Here is how to avoid the usual accidents.

## The five habits

**1. Filter on the partition column.** Every large table is partitioned, usually by a
date. A filter on that column lets Trino skip whole files; a filter on anything else
does not.

```sql
-- Reads one day
select count(*) from marts.merchant_orders_daily
where order_date = date '2026-09-01';

-- Reads the whole table: the function hides the partition column from the planner
select count(*) from marts.merchant_orders_daily
where format_datetime(cast(order_date as timestamp), 'yyyy-MM') = '2026-09';
```

**2. Select only the columns you need.** Data files are columnar: ten columns cost ten
columns, and `select *` on a wide table costs all of them.

**3. Query marts, not raw.** Marts are smaller, already deduplicated and partitioned for
the questions people ask. A `raw` table holds every version of every row.

**4. `limit` does not make a query cheap.** `select * ... limit 10` with no filter can
still read the whole table before returning ten rows. Filter first.

**5. Estimate when an estimate will do.** `approx_distinct(merchant_id)` is far cheaper
than `count(distinct merchant_id)` and accurate to about 2%.

## Check before you run

`explain` shows what Trino plans to read, without reading it. Look for the table scan
and its constraint on the partition column:

```sql
explain (type io)
select merchant_id, sum(captured_amount_minor)
from marts.merchant_orders_daily
where order_date >= date '2026-09-01'
group by merchant_id;
```

If the output shows no constraint on `order_date`, the filter is not being used.

## Limits on ad hoc queries

People's queries run in the `adhoc` resource group, separate from pipelines and
dashboards:

| Resource group | Who | Concurrent queries | Time limit |
|---|---|---|---|
| `pipelines` | Conveyor | Shared pool | None, but deadlines apply |
| `dashboards` | Lantern | Shared pool | 2 minutes per query |
| `adhoc` | People and notebooks | 3 per person | 30 minutes per query |

A query that hits the limit is cancelled, not queued. If you genuinely need a longer
query, it probably belongs in a pipeline; ask in `#team-data`.

## Who pays

Each query is attributed to the cost centre of the Trino role or service account that
ran it, using the same `cost-centre` tags as the rest of our cloud spend (see
[Cloud cost allocation and tagging](../finance/cloud-cost-allocation.md)). Data Platform
posts the twenty most expensive queries of the month in `#team-data` on the first
Monday of the next month. Nobody is told off; the authors usually find a cheaper form
within a day.

## Backfills

A backfill of a large table is the most expensive thing most of us ever run. Always
start with `--dry-run`, which estimates the scan, and follow
[Backfilling historical partitions](backfills.md).
