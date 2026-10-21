---
title: "Data retention schedule"
---

# Data retention schedule

| | |
|---|---|
| Policy owner | Beatrix Sallow, DPO |
| Implementation | Data Platform (Tomasz Wilde) for the warehouse; each service team for its own stores |
| Approved | 2026-04-22 |
| Last reviewed | 2026-04-22 |

This schedule says how long Quillmoor keeps each category of data held in engineering
systems, and what happens at the end. It applies to production databases, the
warehouse and logs. It does not cover HR records, contracts or email, which have their
own rules.

Keeping data longer than we need is a risk, not a safety net: every extra year is more
to protect, more to search when a person asks what we hold, and more to erase.

## The schedule

| Category | Examples | Kept for | Counted from | At the end |
|---|---|---|---|---|
| Payment records | Authorisations, captures, refunds, chargebacks, payouts, ledger journals, settlement files | 7 years | The date of the payment or payout | Removed by the retention job |
| Application logs | Service logs from `card-auth`, `payout-gateway`, `merchant-api` and the rest | 90 days | The log line's timestamp | Expired by the log store |
| Merchant user profiles | Names, emails and roles of Merchant Hub users | While the account is open, then 2 years | Account closure | Removed, or earlier on an erasure request |
| Notification history | Emails and webhooks sent by `notify` | 1 year | Sending | Removed |
| Pipeline history and quality results | `ops.conveyor_runs`, `ops.dq_results` | 2 years | The run | Removed |
| Iceberg snapshots | Earlier versions of warehouse tables | 7 days | The snapshot's commit | Expired nightly |
| Scratch tables | Anything in `scratch` | 21 days | The last write | Dropped |

Payment records are kept for the full period even when a person asks for erasure,
because we are legally required to keep them. In that case the personal details in
those records are pseudonymised and the amounts, dates and references stay; see
[Erasure requests in the warehouse](erasure-requests.md).

## How it is enforced

- **Warehouse tables** carry their retention in table properties, and a Conveyor
  pipeline, `retention_daily`, removes expired partitions every day at 07:30 UTC. A
  table without a retention property cannot be promoted to `marts`.
- **Application logs** are expired by the log store itself after 90 days. Logs must not
  contain personal data beyond identifiers; a log line with an email address in it is a
  bug, to be fixed in the service, and must never contain card data.
- **Production databases** are each team's responsibility; the retention job of each
  service is listed in the team's runbook.

```sql
-- Which warehouse tables declare which retention
select table_name, properties['quillmoor.retention'] as retention
from iceberg.ops.catalogue_tables
where table_name like 'marts.%'
order by retention, table_name;
```

## Legal holds

When Legal or Risk Operations need data kept for a claim, a regulator's inquiry or a
fraud investigation, the DPO places a legal hold on it. A hold suspends removal for the
data it names, whatever this schedule says, until the DPO lifts it. Data Platform keeps
the list of holds in `privacy.legal_holds`; the retention job skips anything on it.

## Changing the schedule

Ask the DPO, by email to `privacy@quillmoor.example`, with the category, the period you
propose and why. Shorter periods are usually approved quickly. Longer ones need a
reason that holds up: "it might be useful for analysis" does not.

The classification of each kind of data, which decides who can see it while we hold
it, is in [Data classification](../security/data-classification.md).
