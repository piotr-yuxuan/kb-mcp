---
title: "ADR-012: One database per service"
---

- **Status:** Accepted, 2021-03-15
- **Author:** Kwabena Stroud
- **Deciders:** Ottilie Marsh, Bram Oyelaran, Nadia Ferreira, Yusuf Achterberg,
  Lukas Brennand

## Context

[ADR-004](adr-004-postgresql.md) made PostgreSQL our default database in 2017 and, for
simplicity, put every service in one shared cluster, `qm-main`. Each service was meant
to keep to its own schema: `ledger`, `payouts`, `merchant_api`, `notify` and so on.
That was a convention, not a rule the database enforced. The only exception is
`card-auth`, whose database has lived in the card data environment, on a cluster of
its own, since we moved to Kubernetes ([ADR-010](adr-010-kubernetes.md)).

Four years on, `qm-main` holds six schemas, serves six services and a dozen jobs,
and has become the place where our teams collide. We counted the problems of the last
twelve months.

### Services read each other's tables

A search of our repositories found twenty-three queries in which a service reads
tables in another service's schema. `merchant-api` builds the payout list that
merchants see by joining straight onto `payouts.payout`. `notify` reads merchant
contact details from `merchant_api.merchant`. Reporting jobs join across five schemas
at once.

Each of these reads is a hidden contract. In August, the Payouts team renamed a column
that, as far as they knew, only their service used. The merchant dashboard's payout
page failed for every merchant for fifty minutes until the change was rolled back.

### One team's migration blocks another team's writes

In October, an index build on a large `notify` table took a lock that queued writes to
a table it referenced, and the queue spread. Ledger postings waited behind it for six
minutes. Nobody had done anything wrong by the rules we had: the migration had been
reviewed by its team, and its team had no reason to know about the ledger's writes.

### Connections are a shared pool

`qm-main` accepts a fixed number of connections. In December a connection leak in one
reporting job used them all, and every service on the cluster started failing at once.
The job was not even running in production hours by design; it had been rescheduled by
accident.

### Upgrades need everyone

The last major PostgreSQL upgrade required a maintenance window for the whole company,
because every service depends on the same cluster. Agreeing the date took longer than
doing the work.

### Settings fit nobody

The ledger needs strict settings: synchronous replication to a standby and the
strongest isolation level for postings. Other services pay for those settings
without needing them. Conversely, the ledger shares memory and disk with workloads
whose spikes it cannot predict.

### Credentials and cost are shared

Several services connect with the same role. When something writes to a table it
should not, we cannot tell which service did it. And the cluster's cost cannot be
split between the teams that cause it.

## Decision

Every service owns exactly one database, and no other service connects to it.

1. **One database per service.** Each service has its own PostgreSQL database. A
   database belongs to exactly one service and is never shared, not even with another
   service of the same team.
2. **Placement is Platform's call.** Platform decides which cluster hosts which
   database. Small databases of the same criticality may share a cluster, but they
   never share a database, a role or a connection pool.
3. **The ledger is alone.** The `ledger` database runs on a cluster of its own, with
   the settings Ledger chooses. Nothing else is placed on it.
4. **Owner-only access.** Only the owning service connects, with a role created for
   that service and no other. No other service gets credentials, not even read-only
   ones.
5. **Data crosses boundaries through the owner.** A service that needs another
   service's data asks for it through the owner's API, or keeps its own copy of the
   facts it needs, fed by the owner's domain events
   ([ADR-007](adr-007-message-broker.md)).
6. **No cross-database queries.** No foreign data wrappers, no links between
   databases, no shared views.
7. **Reporting reads the data platform.** Analytics, finance reporting and ad hoc
   queries read from the data platform, which receives its own copies of the data.
   They never read from a service's production database or from its replicas. How the
   data platform is organised is described in
   [Data platform overview](../data/platform-overview.md).
8. **Each team runs its own schema changes**, in its own database, through the shared
   process in [Database migrations](../release/database-migrations.md).

The databases, as planned on the day of this decision:

| Service | Database | Cluster |
|---|---|---|
| `ledger` | `ledger` | dedicated |
| `payout-gateway` | `payout_gateway` | Payouts, shared |
| `settlement-batcher` | `settlement` | Payouts, shared |
| `merchant-api` | `merchant_api` | Merchant Experience, shared |
| `notify` | `notify` | Merchant Experience, shared |
| `fx-quote` | `fx_quote` | Payments Core, shared |
| `card-auth` | `card_auth` | card data environment, unchanged |

`merchant-hub` and `risk-scorer` keep no database of their own: the first is a front
end that calls `merchant-api`, and the second is served from a model with no
transactional state.

### Choosing between an API call and a local copy

Rule 5 leaves the consuming team a choice. We expect it to be made the same way
everywhere:

| The consumer needs | Use | Example |
|---|---|---|
| The current value, at the moment of a decision | The owner's API | `card-auth` checking a merchant's settings before an authorisation |
| A value to display or to filter on, where a few seconds of lag is harmless | A local copy fed by events | the payout list in the merchant dashboard |
| History, or a join across several owners | The data platform | the monthly volume report for finance |
| Something the owner does not publish | A request to the owner | ask in the owning team's channel; do not work around it |

A local copy holds only the fields the consumer uses, is rebuilt from the owner's API
when it is first created, and is kept current by events from then on. `notify`, for
example, keeps each merchant's contact address and language, fed by
`merchant.updated`, and nothing else from the merchant record.

Access is set up so that the rule holds even if someone forgets it:

```sql
-- Run by Platform when a database is created; one role per service.
CREATE ROLE payout_gateway_app LOGIN;
REVOKE CONNECT ON DATABASE payout_gateway FROM PUBLIC;
GRANT CONNECT ON DATABASE payout_gateway TO payout_gateway_app;
GRANT USAGE, CREATE ON SCHEMA public TO payout_gateway_app;
```

## Migration

We are moving one service at a time, starting with the one that suffers most.

1. **Ledger first.** Ledger replaces the reads other services make of its tables with
   API calls and events, then moves its schema to its own cluster.
2. **Then Payouts.** `payout-gateway` and `settlement-batcher` follow. The payout list
   in `merchant-api` is the largest cross-read and the hardest to replace: it needs
   `merchant-api` to keep its own copy of payout statuses, fed by events.
3. **Then the rest.** `merchant-api`, `notify` and `fx-quote` move last.
4. **Then `qm-main` is switched off.**

For each service the steps are the same:

1. List every query that reads or writes the service's tables from outside it. The
   database's own statistics, collected for a month, are more reliable than a search
   of the code.
2. Replace each of those queries with an API call or an event-fed copy. This is the
   long part, and it is done by the consuming team with the owning team's help.
3. Revoke every other role's access to the schema. Wait two weeks. Anything that
   breaks was missed in step 1.
4. Copy the schema to its new database with logical replication, then switch the
   service over during a short pause in writes.
5. Drop the old schema from `qm-main`.

## Consequences

### What gets better

- A team can change its own tables without asking who else reads them, because nobody
  else does.
- A migration or a runaway query in one service can no longer hold up the ledger.
- Upgrades, maintenance and settings are per database, chosen by the people who
  understand the workload.
- Every write to a table comes from a known service, through a role that belongs to it.
- Database costs follow the services that cause them.

### What gets harder

- **No transaction spans two services.** A payout recorded by `payout-gateway` and
  posted by `ledger` is two transactions in two databases. We rely on the outbox
  pattern from ADR-007 to publish events reliably, on idempotent consumers
  ([ADR-008](adr-008-idempotency-keys.md)), and on reconciliation to find the rare
  case where the two disagree; see
  [Runbook: ledger reconciliation breaks](../payments/ledger-reconciliation.md).
- **Copies are briefly stale.** A service that keeps its own copy of another
  service's data sees changes a little after they happen. For the payout list in the
  merchant dashboard this means a status may lag by a few seconds. We judged that
  acceptable; screens where it is not must call the owner's API.
- **More to run.** More clusters, more backups, more monitoring, more upgrades. Most of
  this falls on Platform, which will automate database creation, roles and backups
  before the migration reaches the second team.
- **Reporting changes.** Analysts who query `qm-main` directly today must move to the
  data platform. The Data Platform team plans that move with them.
- **Local development** needs one database per service instead of one for everything.
  The development environment's seed data will have to follow.

## Alternatives considered

### Keep the shared cluster and add discipline

We tried this for two years. Reviews cannot catch a cross-schema read that the
reviewer does not know is one, and conventions do not stop a lock or a connection
leak in one schema from affecting the others.

### One schema per service, enforced by grants, on the shared cluster

Revoking cross-schema grants would stop services reading each other's tables, and we
use exactly this as step 3 of the migration. As an end state it leaves the shared
locks, connection limits, upgrades and settings untouched, which are half of our
problems.

### One database per team

Fewer databases to run, and teams already own a repository each
([ADR-005](adr-005-repository-per-team.md)). But services move between teams, and two
services of the same team can have very different needs: `payout-gateway` and
`settlement-batcher` both belong to Payouts and behave nothing alike. Ownership by
service survives reorganisations; ownership by team does not.

### A distributed SQL database

It would let us keep cross-service queries and transactions, which is precisely the
coupling we want to remove. It would also mean a second database engine, against
ADR-004.

## Related ADRs

- [ADR-004](adr-004-postgresql.md): PostgreSQL remains the engine.
- [ADR-005](adr-005-repository-per-team.md): ownership of code, which this record
  extends to data.
- [ADR-007](adr-007-message-broker.md) and later
  [ADR-019](adr-019-replicated-event-log.md): events as the way to share facts.
- [ADR-008](adr-008-idempotency-keys.md): idempotent consumers.
- [ADR-020](adr-020-strongroom.md): where each service's database credentials live.

## Update, 2022-06-20

The migration finished this month. The last cross-read, the payout list in
`merchant-api`, now reads from its own event-fed copy, and `qm-main` was switched off
on 2022-06-14.

## Update, 2025-06-16

Credentials for every service database now live only in Strongroom, under ADR-020.

## Update, 2026-06-08

ENG-10 is done. It tightened how teams run schema changes in their own databases
without downtime; the rules are in Database migrations, linked above.
