---
title: "Data platform on-call"
---

# Data platform on-call

Owner: Tomasz Wilde. Last reviewed 2026-10-12.

Data Platform keeps one person on call at all times for the warehouse and its tier 1
pipelines. This page says what the data on-call is responsible for, what pages them and
what can wait, and what to do in the first half hour. The company-wide rules for being
on call, including acknowledgement times, swaps and allowances, are on
[On-call rota and paging policy](../incidents/on-call.md) and are not repeated here.

## The rota

- **Rota:** "Data Platform" in Klaxon. If you are new to Klaxon, start with
  [Setting up Klaxon on your phone](../incidents/klaxon-setup.md).
- **Members:** Hana Ostrowska, Rafael Quist, Signe Abernethy, with Tomasz Wilde as
  secondary for every shift.
- **Shift:** one week, handing over on Mondays at 10:00 UK time, like every other rota.
- **Contact in hours:** `#team-data`. Out of hours: page through Klaxon.

## What you are responsible for

- The tier 1 pipelines: `merchant_orders_daily`, `payouts_hourly`,
  `fraud_features_daily` and the finance marts.
- Conveyor and Trino being available to run them.
- Ingestion into `raw` for the sources that tier 1 pipelines read.
- The `privacy_erasure` job, in working hours.

You are not responsible for the services upstream. If `ledger` replication stops
because the Ledger team's database is in trouble, your job is to notice, tell them
through their on-call, and protect our tables, not to fix their database.

## What pages, and what does not

| Event | Pages out of hours? |
|---|---|
| `DQ-017` on a tier 1 table | Yes |
| `DQ-044` holding a tier 1 pipeline | Yes |
| Conveyor scheduler unavailable for more than 15 minutes | Yes |
| Ingestion more than 2 hours behind for a source a tier 1 pipeline reads | Yes |
| `DQ-031` warning on any table | No: next working day |
| Anything on a tier 2 table | No: owning team, working hours |
| `privacy_erasure` job failure | No: first thing next working morning |

The codes are explained on [Data quality alerts](quality-alerts.md).

## The first half hour

1. Acknowledge the page in Klaxon and say in `#team-data` that you are on it.
2. Open the pipeline in Conveyor and find the failing or stuck task.
3. Decide whether the problem is ours (a model, Conveyor, Trino) or upstream (a source
   service, its database, the event log).
4. If a finance mart will miss its deadline, or already has, declare an incident with
   `/klaxon declare` and handle it as the quality alerts page says. Tell Finance in the
   incident channel and in `#team-data`.
5. If the cause is upstream, page the owning team's on-call through Klaxon; for the
   payments services, `payments-oncall@quillmoor.example` reaches them too.
6. Fix, or retry, or wait for upstream; then confirm the partition published and the
   alert cleared.

Useful commands:

```bash
conveyor runs merchant_orders_daily --last 3
conveyor run merchant_orders_daily --partition 2026-10-11
conveyor backfill list --running
```

If a backfill is competing for capacity with a late tier 1 run, pause it with
`conveyor backfill pause` and tell its owner; it will not have been started inside the
nightly window, but a long one can still be running in the evening.

## Problems we have seen before

| Symptom | Usual cause | First move |
|---|---|---|
| `wait_for_ingestion` times out on several pipelines at once | A replication slot fell behind after an upstream database failover | Check ingestion lag per source in Lantern; tell the owning team |
| One staging model held by `DQ-044` | An upstream migration renamed or retyped a column | Ask the owning team; pin the staging model with a cast if the change is final |
| Runs slow everywhere, no errors | Trino lost workers, or Platform is upgrading the node pool | Check the cluster panel in Lantern; ask Platform about nodes |
| `payouts_hourly` blocked by `DQ-031` in the day | Payout ingestion stalled, or a genuine surge | Compare with `payout-gateway` metrics in Lantern before overriding anything |
| Conveyor UI unreachable | The Conveyor scheduler pod restarting | Check its deployment; escalate to Platform after 15 minutes |

## Handing over

On Monday at 10:00, the outgoing on-call posts a hand-over in `#team-data` and walks the
incoming one through it. Use the company's
[On-call handover checklist](../incidents/handover-checklist.md), plus these
data-specific items:

- open `DQ-031` warnings nobody has explained;
- backfills running or planned this week, and who owns them;
- the age of the oldest unapplied erasure request;
- annotations expiring in the coming week;
- any upstream migration announced that could raise `DQ-044`.

## Escalation

1. Tomasz Wilde, secondary on every shift.
2. Bram Oyelaran, head of platform engineering, when Trino or Kubernetes capacity is
   the problem and Platform needs to act.
3. For incidents of any severity, the roles and channel set by
   [Production incident management](../incidents/incident-management.md).
