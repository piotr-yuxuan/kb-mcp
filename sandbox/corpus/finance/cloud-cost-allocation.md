---
title: "Cloud cost allocation and tagging"
---

# Cloud cost allocation and tagging

Owned by the FinOps working group: Leontine Barrow (financial planning lead, Finance)
and Bram Oyelaran (head of platform engineering). Last reviewed on 2026-10-06.
Questions go to `#team-platform` for tagging and to `#ask-finance` for anything about
budgets.

Cloud is Quillmoor's second-largest cost after salaries, and the one that moves fastest.
This page explains how every pound on the cloud bill is traced back to a cost centre,
which tags make that possible, what happens to costs nobody claims, and how the monthly
review works.

## What FinOps means here

FinOps, short for cloud financial operations, is the practice of making cloud spending
visible to the engineers who cause it, so that cost becomes one engineering trade-off
among others, alongside latency, reliability and delivery time. At Quillmoor it is not a
team. It is a small working group from Finance and Platform, plus a responsibility that
every engineering team carries for its own spend.

Four principles guide the work:

1. **Every pound has an owner.** Each cost lands on a cost centre, and each cost centre
   has a budget holder.
2. **Teams see their costs daily**, not at the end of the quarter, on the Lantern
   dashboard "Cloud costs by cost centre".
3. **The team that causes a cost decides about it.** Finance points out trends and
   anomalies; it does not switch anything off.
4. **Allocation must be explainable.** If a budget holder cannot see why a cost landed
   on their cost centre, the rule is wrong, and we change it.

## The three required tags

Every cloud resource that can carry tags must carry these three. Kubernetes workloads
carry them as labels on their namespace, from which they are copied onto the billing
data.

| Tag | Allowed values | Example | Notes |
|---|---|---|---|
| `cost-centre` | A cost centre code from the [cost centre list](cost-centres.md), in the form `CC-` and four digits | `CC-3200` | The cost centre that pays, not the team that happens to run the resource |
| `service` | The service's name as it appears in the service catalogue | `payout-gateway` | Use `shared` only for platform components that serve many services |
| `env` | `prod`, `staging`, `dev` or `sandbox` | `prod` | `sandbox` is the merchant-facing test environment, not a personal playground |

The keys are lower case, with a hyphen in `cost-centre`. `costcentre`, `CostCentre` and
`cost_center` are all different keys to the billing system, and all of them count as
untagged.

Teams may add their own tags, such as `owner` or `data-classification`, but the three
above are the only ones that drive allocation.

## Applying the tags

The platform's provisioning modules take the three tags as required inputs, so anything
created through them is tagged from the start:

```yaml
module: platform/postgres-instance
inputs:
  name: ledger-replica-2
  tags:
    cost-centre: CC-3300
    service: ledger
    env: prod
```

For Kubernetes, label the namespace once and every pod in it is allocated accordingly:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payout-gateway
  labels:
    cost-centre: CC-3200
    service: payout-gateway
    env: prod
```

Resources created by hand in the console, which should be rare, must be tagged by the
person who creates them before the end of the day.

A tag check runs every night against the whole estate. It lists untagged and badly
tagged resources by account and by team on the Lantern dashboard, and posts a summary to
each team's channel on Monday mornings. A resource that stays untagged for 14 days is
raised with the team lead.

## How costs are allocated

The billing data arrives daily. Costs are allocated in the order below; each step takes
what the previous steps left.

| Step | Cost | Allocated by |
|---|---|---|
| 1 | Resources with a valid `cost-centre` tag | The tag, directly |
| 2 | Shared Kubernetes clusters | Each namespace's requested CPU and memory, hour by hour |
| 3 | Warehouse compute for Trino | Data scanned by each team's queries; see [keeping warehouse queries cheap](../data/query-costs.md) |
| 4 | The Kiln GPU cluster | GPU hours used by each team; see [GPU cluster quotas and scheduling](../ml/gpu-cluster.md) |
| 5 | Platform overheads: shared networking, cluster control planes, logging, support charges | Pro rata to each cost centre's costs from steps 1 to 4 |
| 6 | Commitment discounts | Pro rata to the eligible usage that benefited from them |
| 7 | Anything left | `CC-9000 Unallocated` |

A few consequences are worth knowing:

- **Requests, not usage, drive step 2.** A namespace that requests eight cores and uses
  one pays for eight. Right-sizing requests is the quickest saving most teams have.
- **GPU hours have been reported per team since Kiln's quotas came in** (ENG-23), which
  is what made step 4 possible. Before that, GPU costs sat with Risk ML regardless of
  who ran the jobs.
- **Commitment discounts are bought centrally** by Platform, through the
  [spend approval matrix](spend-approval.md) like any other purchase, and their benefit
  is spread across the teams whose usage they cover. No team is rewarded or penalised
  for where a commitment happened to land.

## Untagged costs: `CC-9000 Unallocated`

Any cost that cannot be traced to a cost centre lands in `CC-9000 Unallocated`. It is
a real cost centre in the accounting system, owned by the FinOps working group, and it
has a budget of zero.

Our target is to keep unallocated cloud costs under 3% of the monthly bill. The rules
are:

1. In the month a cost first appears unallocated, the working group tries to find its
   owner from the account, the resource names and the deploy history in Shipwright.
2. If the owner is found, the resource is tagged and the month's cost is moved to the
   right cost centre in the following month's allocation.
3. If a resource is still unallocated in a second consecutive month, its full cost for
   both months is charged to the cost centre of the account's owner, whether or not that
   team created it.

Nobody should code anything to `CC-9000` by hand. Expenses and purchase orders coded to
it are rejected in Tally.

## The monthly review

The FinOps working group holds a monthly cost review on the **second Wednesday of each
month**, once the previous month's books are closed (see the
[month-end close calendar](month-end-close.md)). It lasts 45 minutes.

**Who attends:** the working group, the team leads of the five largest cloud cost
centres for the month, and anyone whose cost centre moved by more than 15% against the
previous month. Others are welcome.

**Agenda:**

1. The month's total against budget and against the latest forecast.
2. The share in `CC-9000 Unallocated`, and the oldest unallocated items.
3. The ten largest increases and decreases by cost centre and by service, each
   explained by its team.
4. Commitment coverage: how much eligible usage was covered by a commitment, and
   whether any commitment is due for renewal in the next three months.
5. Anomalies raised during the month (see below) and what came of them.
6. Actions from the previous review.

**Output:** short notes in the FinOps folder of this space, with each action assigned to
a named person and a date. Financial planning uses the notes to update the cloud lines
of the monthly forecast.

### Example: the review of 14 October 2026

The review looked at September 2026. The bill was £412,600, 2.1% under the month's
budget.

| Cost centre | September 2026 | Change on August |
|---|---|---|
| `CC-3700` Data Platform | £96,300 | +6% |
| `CC-3100` Payments Core | £71,800 | +2% |
| `CC-3800` Risk ML | £64,900 | +11% |
| `CC-3400` Platform | £52,400 | -3% |
| `CC-3200` Payouts | £38,700 | +1% |
| `CC-3300` Ledger | £31,200 | +4% |
| `CC-4000` Merchant Experience | £27,600 | 0% |
| `CC-3500` Site Reliability | £10,900 | -8% |
| Other cost centres | £8,900 | +3% |
| `CC-9000` Unallocated | £9,900 | -12% |
| **Total** | **£412,600** | **+3%** |

Unallocated costs were 2.4% of the bill, within target for the third month running.
Risk ML explained its 11% increase by the retraining runs for `fraudscore-v7`, which
were planned and budgeted. Data Platform's increase came from the backfills that
followed the new backfill tooling; Tomasz Wilde agreed to bring a forecast for the rest
of the year to the November review. Two actions were recorded: Platform to remove an
idle staging database in `CC-3400` by the end of October, and Merchant Experience to fix
the `env` label on two namespaces still tagged `production` instead of `prod`.

## Anomaly alerts

Every morning a Lantern check compares each cost centre's previous day of cloud spend
with its average over the preceding 28 days. When the day is more than 40% higher, and
the difference is more than £500, it posts an alert to the owning team's channel and to
the working group. Most alerts have a good reason, such as a load test or a backfill;
the team replies in the thread with the reason, or with a fix.

## Seeing your own costs

The Lantern dashboard "Cloud costs by cost centre" shows yesterday's allocated cost by
cost centre, service and environment, with a month-to-date total against budget.

For anything more detailed, the allocated costs are in the warehouse table
`marts.cloud_costs_daily`, one row per day, cost centre, service, environment and
allocation step. For example, a team's production cost by service for September:

```sql
select
    service,
    sum(allocated_cost_gbp) as cost_gbp
from marts.cloud_costs_daily
where cost_centre = 'CC-3200'
  and env = 'prod'
  and usage_date between date '2026-09-01' and date '2026-09-30'
group by service
order by cost_gbp desc;
```

Figures for the current month change daily until the month closes, as late billing
data and credits arrive.

## Budgets and forecasts

Each cost centre's cloud budget is set in the [annual budget cycle](budget-cycle.md),
starting from a forecast that the working group prepares from the last six months of
allocated costs. During the year, the cloud lines of each reforecast start from the same
data. If you know of a change that the trend will not show, such as a new region, a
large backfill or a service being retired, tell the working group before the reforecast
opens.

## Frequently asked questions

**We are launching a new service. What do we need to do?**
Create its namespace and resources through the platform modules with the three tags,
and check the Lantern dashboard the day after the first deploy to see its costs appear.

**Our costs went up because another team calls our service more often. Who pays?**
The team that owns the service, at least for now. We do not recharge between services,
because the effort would exceed the benefit. If a single caller drives a large share of
your cost, raise it at the monthly review.

**Who pays for staging?**
The cost centre on the `cost-centre` tag, as for production. The `env` tag lets you see
staging separately, and staging should rarely exceed a fifth of a service's production
cost.

**A resource is tagged with the wrong cost centre. Can last month be corrected?**
Yes, once. Fix the tag, then ask the working group to move the cost in the next month's
allocation. We do not reopen closed months.

**Why does my cost centre carry part of the platform overheads?**
Because every service depends on shared networking, logging and cluster control planes,
and spreading them in proportion to direct costs is the simplest fair rule we found. The
overhead share has been between 9% and 12% of the bill for the past year.

## Related pages

- [Cost centre list](cost-centres.md)
- [Annual budget cycle](budget-cycle.md)
- [Spend approval matrix](spend-approval.md)
- [Keeping warehouse queries cheap](../data/query-costs.md)
- [GPU cluster quotas and scheduling](../ml/gpu-cluster.md)
