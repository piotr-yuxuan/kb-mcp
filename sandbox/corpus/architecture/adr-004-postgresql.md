---
title: "ADR-004: PostgreSQL as the default database"
---

- **Status:** Accepted, 2017-05-08
- **Author:** Ottilie Marsh
- **Deciders:** Nadia Ferreira, Yusuf Achterberg, Kwabena Stroud

## Context

Every service we have started so far stores something: merchants and their settings,
payments and their states, payouts, and the ledger's journals. Two engineers have
already reached for different databases in prototypes. If each team picks its own,
we will end up running four engines, badly, with nobody expert in any of them.

What we need from a transactional store:

- Transactions with strict guarantees. A payment that is half recorded is worse than
  one that is not recorded at all.
- Constraints enforced by the database, not only by application code.
- Mature tooling for backups, point-in-time recovery and replication.
- Good support from Python and Go ([ADR-002](adr-002-python-back-office.md),
  [ADR-003](adr-003-go-latency-critical.md)).
- An engine that the people we hire already know.

## Decision

PostgreSQL is the default database for transactional data at Quillmoor.

- A service that needs to store state uses PostgreSQL unless an ADR says otherwise.
  Choosing another engine for production data is an architecture decision, not a
  team's preference.
- We use the hosted PostgreSQL offered by our cloud provider, with point-in-time
  recovery enabled, rather than running our own servers.
- Constraints, foreign keys and check constraints are used wherever they express a
  business rule. "The application already checks it" is not a reason to leave one out.
- `jsonb` columns are allowed for payloads we store and return as a whole, such as a
  raw response from the issuer, but not for fields we filter or join on.
- Schema changes go through reviewed migration files kept with the service's code.
  The process for writing and running them is described in
  [Database migrations](../release/database-migrations.md).

## Consequences

- Our expertise concentrates on one engine. Query tuning, backups and upgrades become
  shared knowledge instead of one person's secret.
- At first, every service shares one cluster. This is cheap and simple while we are
  small, and will need revisiting as we grow.
- Workloads that PostgreSQL serves badly, such as large-scale analytics, will need a
  separate decision when they arrive rather than being forced into the transactional
  database.

## Alternatives considered

- **MySQL.** A fine engine that two of us know, but its handling of constraints and
  its transactional schema changes were weaker for our needs.
- **A document database.** Flexible early on, but money moves between records, and we
  want multi-record transactions and constraints without building them ourselves.
- **Apache Cassandra.** Scales writes well, but offers none of the transactional
  guarantees a ledger depends on.

## Related ADRs

- [ADR-012](adr-012-database-per-service.md): One database per service.
- [ADR-017](adr-017-money-minor-units.md): how money is stored in those databases.

## Update, 2021-03-15

The shared cluster mentioned under "Consequences" was split up by ADR-012. This record
still sets the engine; ADR-012 sets who may connect to what.
