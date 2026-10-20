---
title: "Data platform overview"
---

# Data platform overview

**Owner:** Tomasz Wilde, data platform lead
**Team channel:** `#team-data`
**Last reviewed:** 2026-09-29

This page is the front door to Quillmoor's data platform: what it is made of, how data
moves through it, and where to go next. If you are new to the warehouse, read this page
first, then [Requesting warehouse access](warehouse-access.md) and
[Warehouse naming conventions](naming-conventions.md). If something is broken right now,
skip to [Data platform on-call](data-on-call.md).

## What the platform is for

The data platform gives every team one place to answer questions about payments,
payouts, merchants and risk without touching production databases. It serves four
kinds of consumer:

- **Finance**, for the daily revenue report, the month-end close and treasury views of
  payouts.
- **Risk ML**, for the features that the fraud models are trained and scored on.
- **Product and Merchant Experience**, for funnel analysis, merchant health and the
  numbers behind roadmap decisions.
- **Operations teams** (Payouts, Merchant Support, Risk Operations), for dashboards in
  Lantern that read from the warehouse rather than from live services.

It is not an operational system. Nothing that moves money reads from the warehouse, and
nothing in the warehouse is the source of truth for a balance: the `ledger` service is.
If a warehouse number and a ledger number disagree, the ledger wins and we have a bug.

## The stack at a glance

| Component | What we use | Notes |
|---|---|---|
| Table format | Apache Iceberg | Parquet data files on object storage; snapshots give us time travel and safe rewrites |
| Query engine | Trino | `trino.quillmoor.example`, catalogue `iceberg`; used by people, dashboards and pipelines alike |
| Orchestration | Conveyor | Schedules and runs every pipeline; also the `conveyor` CLI for runs and backfills |
| Ingestion | PostgreSQL logical replication; the domain event log | Service databases and domain events land in `raw` |
| Metrics and alerting | Lantern | Freshness, row counts and pipeline health, at `lantern.quillmoor.example` |
| Secrets | Strongroom | Pipeline service credentials; nobody keeps warehouse passwords in code |
| Compute | Kubernetes | Trino workers and Conveyor workers run in their own node pool |

All of the above is either open-source software we operate ourselves (Iceberg, Trino,
PostgreSQL, Kubernetes) or one of our internal tools (Conveyor, Lantern, Strongroom).
We do not use a hosted warehouse, which keeps cardholder-adjacent data inside our own
estate and keeps costs predictable.

## Layers

Every table in the warehouse lives in one of three layers. The layer is the schema name,
so you can tell at a glance what you are querying.

| Layer | Schema | What it holds | Who writes it | Who should read it |
|---|---|---|---|---|
| Raw | `raw` | Data exactly as it arrived from a source, append-only, with load metadata | Ingestion jobs only | Data Platform, and pipeline authors debugging a source |
| Staging | `staging` | One cleaned model per source entity: types fixed, names normalised, duplicates removed, erasure filters applied | Conveyor staging models | Pipeline authors |
| Marts | `marts` | Business tables built for a purpose, with an owner, a grain and quality checks | Conveyor mart models | Everyone with access |

A few rules follow from this:

1. **Read marts.** If the table you need does not exist in `marts`, ask in `#team-data`
   before building a dashboard on `staging` or, worse, `raw`. Raw tables change shape
   when their source changes; marts have a contract.
2. **Never write to `raw` by hand.** Corrections go into staging logic, so that the
   original record survives for audit.
3. **One grain per mart.** `marts.merchant_orders_daily` is one row per merchant, day and
   currency; it is not also a per-order table. The grain is the last word of the table
   name (see [Warehouse naming conventions](naming-conventions.md)).

Besides the three layers there are three service schemas, which are not layers and
which most people never query:

- `privacy`: the erasure request queue and `privacy.erasure_log`; see
  [Erasure requests in the warehouse](erasure-requests.md).
- `ops`: pipeline run history and the results of data quality checks.
- `scratch`: personal and team scratch tables, dropped automatically 21 days after
  their last write.

## How data moves

```text
 service databases (PostgreSQL)          domain event log (Apache Kafka)
   card-auth, ledger, payout-gateway,      payment, payout and merchant events
   merchant-api, fx-quote, notify
              |                                         |
              | logical replication                     | consumer group dw-ingest
              v                                         v
        +-------------------------------------------------------+
        |  raw.*            append-only, load metadata           |
        +-------------------------------------------------------+
                                  |
                                  | Conveyor: staging models
                                  v
        +-------------------------------------------------------+
        |  staging.stg_*    typed, deduplicated, erasure-filtered|
        +-------------------------------------------------------+
                                  |
                                  | Conveyor: mart models + quality checks
                                  v
        +-------------------------------------------------------+
        |  marts.*          owned, documented, checked           |
        +-------------------------------------------------------+
              |                    |                     |
         Lantern dashboards   finance reports     Risk ML features
```

Ingestion from service databases uses PostgreSQL logical replication into a set of
replication slots owned by the `dw-ingest` role. Each service team owns its schema and
its migrations; we only read. When a service team changes a column, our staging model
for it has to follow, which is why schema changes upstream raise `DQ-044` (see
[Data quality alerts](quality-alerts.md)) and why we ask every team to follow the
expand-then-contract pattern described in
[Database migrations](../release/database-migrations.md).

Domain events arrive through the replicated event log adopted in
[ADR-019](../architecture/adr-019-replicated-event-log.md). Our consumer group commits
its offsets only after the events are written to an Iceberg snapshot, so a crash in
ingestion produces a duplicate at worst, never a gap. Staging models deduplicate on the
event identifier.

## Conveyor

Conveyor is the orchestrator. A pipeline is a DAG of tasks defined in Python in the
`data-pipelines` repository; each task usually runs one SQL model through Trino and
writes one partition of one Iceberg table. Conveyor knows the partition each run is
responsible for, which is what makes backfills and retries safe.

The three pipelines most people ask about each have their own page:

| Pipeline | Builds | Page |
|---|---|---|
| `merchant_orders_daily` | Daily orders and amounts per merchant | [Pipeline: merchant_orders_daily](merchant-orders-daily.md) |
| `payouts_hourly` | Hourly payout volumes and states | [Pipeline: payouts_hourly](pipeline-payouts-hourly.md) |
| `fraud_features_daily` | Daily features for the fraud models | [Pipeline: fraud_features_daily](pipeline-fraud-features-daily.md) |

Day-to-day commands:

```bash
# Run one partition of a pipeline now (for example after fixing a failed task)
conveyor run payouts_hourly --partition 2026-09-28T14

# Show the last runs of a pipeline and their state
conveyor runs merchant_orders_daily --last 7

# Fill a range of historical partitions; read the backfills page first
conveyor backfill merchant_orders_daily --from 2026-09-01 --to 2026-09-07 --dry-run
```

Backfills have rules of their own, about how many partitions a run may cover and when
it may start; they are on [Backfilling historical partitions](backfills.md). Writing
a new pipeline is covered in [Writing a Conveyor DAG](writing-a-dag.md).

DAG changes are merged to the main branch of `data-pipelines` after review and go out
through Shipwright like any other service, so the usual
[deployment pipeline](../release/deployment-pipeline.md) rules apply to them.

## Querying the warehouse

Most people use Trino through a SQL client or a notebook. The command-line client works
too:

```bash
trino --server https://trino.quillmoor.example \
      --catalog iceberg --schema marts \
      --user "$USER" --external-authentication
```

Iceberg keeps snapshots of every table, so you can look at a table as it was at a point
in time. This is the quickest way to answer "did this number change overnight?":

```sql
-- Totals for one day, now and as the table stood on Monday morning
select
    'now' as as_of,
    sum(captured_amount_minor) as captured_minor
from iceberg.marts.merchant_orders_daily
where order_date = date '2026-09-20'
union all
select
    'monday 07:00 UTC',
    sum(captured_amount_minor)
from iceberg.marts.merchant_orders_daily
    for timestamp as of timestamp '2026-09-21 07:00:00 UTC'
where order_date = date '2026-09-20';
```

Two habits keep queries fast and cheap: always filter on the partition column, and
select only the columns you need. [Keeping warehouse queries cheap](query-costs.md) has
the rest.

## Ownership, quality and personal data

Three pages describe the obligations that come with a table in `marts`:

- **Ownership.** Every mart has an owning team and a named steward, recorded in the data
  catalogue. See [Data catalogue and table ownership](table-ownership.md).
- **Quality.** Every mart declares a freshness deadline and row-count expectations,
  checked after each run. See [Data quality alerts](quality-alerts.md).
- **Personal data.** Every column that holds personal data is tagged, so that access
  controls and the erasure job can find it. See
  [Tagging personal data columns](personal-data-columns.md).

Card numbers never reach the warehouse: PANs stay in the card data environment
described in [Payments platform architecture](../payments/platform-architecture.md),
and the ingestion of `card-auth` replicates only tokenised references and the last four
digits.

## Access

Access is by Trino role, granted per layer and per data classification. Most people
need `analyst_internal`, which reads `marts` tables classed Internal. Confidential
marts, staging and raw each need their own role and an approval from the table's owner.
The process is on [Requesting warehouse access](warehouse-access.md); roles are
certified in the quarterly access reviews run by Security.

## The team

| Person | Focus |
|---|---|
| Tomasz Wilde | Data platform lead; roadmap, priorities, approvals for new marts |
| Hana Ostrowska | Senior data engineer; Conveyor, backfill tooling |
| Rafael Quist | Analytics engineer; marts for Finance and Product |
| Signe Abernethy | Data engineer; ingestion, privacy tooling, the erasure job |

The team runs an on-call rota in Klaxon, described in
[Data platform on-call](data-on-call.md), and holds office hours on the third Thursday of each
month; the notes are in the section, for example
[July 2026](office-hours-2026-07.md) and [September 2026](office-hours-2026-09.md).

## Where to start, by role

**You want numbers for a decision or a report.** Ask for `analyst_internal`, find the
mart in the data catalogue, read its description and grain, and query it through Trino.
If no mart answers your question, describe the question in `#team-data` rather than
assembling one from staging tables; someone has often built it already.

**You are building a pipeline.** Read [Writing a Conveyor DAG](writing-a-dag.md), the
[SQL style guide](sql-style-guide.md) and the naming conventions, then build one
partition into `scratch` before you open a pull request. Ask for `staging_reader` if
your models read staging tables owned by others.

**You own a service whose database we replicate.** You do not need warehouse access to
keep us working, but you do need to tell us before you rename, retype or drop a column:
a message in `#team-data` a sprint ahead turns a `DQ-044` at three in the morning into
a routine change. If your service starts storing a new kind of personal data, tell us
as well, so that it is tagged before it reaches `marts`.

**You handle requests about personal data.** The privacy team works with the
`privacy` schema and the erasure job; start with
[Erasure requests in the warehouse](erasure-requests.md) and the
[Data retention schedule](retention-schedule.md).

## Recent and current work

| Epic | What it delivered | When |
|---|---|---|
| ENG-17 | Rebuilt `merchant_orders_daily` and moved it earlier in the night | Done, August 2025 |
| ENG-18 | The data quality alert framework and its three alert codes | Done, December 2025 |
| ENG-19 | Automated erasure across the warehouse | Done, July 2026 |
| ENG-20 | Conveyor backfill tooling | In progress, ENG Sprint 40 |

The next items on our list, not yet scheduled, are column-level lineage in the data
catalogue and moving `payouts_hourly` to a 15-minute grain so that it lines up with
payout batches.

## Known limits

- **No streaming.** The freshest table in the warehouse is hourly. If you need
  something closer to real time, you need a Lantern metric emitted by the service, not
  a warehouse query.
- **Late data.** Refunds, chargebacks and settlement lines arrive days or weeks after
  the payment they belong to. Marts recompute a trailing window on each run; anything
  older needs a backfill.
- **Raw is not cleaned.** Raw tables still hold duplicates and rows that staging
  filters out, including rows of erased subjects awaiting the next erasure run. Do not
  build on raw.
- **Scratch is temporary.** Tables in `scratch` disappear 21 days after their last write.
  If a scratch table matters, it should become a mart.

## Terms we use

- **Partition:** the slice of a table one run writes, usually one day (`2026-09-20`) or
  one hour (`2026-09-28T14`), always in UTC.
- **Snapshot:** an Iceberg version of a table; each commit creates one.
- **Freshness deadline:** the time by which a table's latest partition must be complete.
- **Steward:** the person in the owning team who answers questions about a table.
- **Backfill:** building or rebuilding historical partitions of a pipeline.
