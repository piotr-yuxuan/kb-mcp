---
title: "ADR-002: Python for back-office services"
---

- **Status:** Accepted, 2017-03-20
- **Author:** Yusuf Achterberg
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Kwabena Stroud

## Context

Much of what Quillmoor has to build in its first year never faces a cardholder:
building settlement files for our settlement bank, matching the ledger against bank
statements, checking new marketplaces during onboarding, internal admin tools, and the
reports that finance asks for at month end. This work is batch-shaped, heavy on files
and data, and judged on correctness rather than speed. Nobody is waiting on the other
end of a socket while it runs.

Seven of our eleven engineers write Python every day. Its libraries for CSV, XML,
spreadsheets and dates cover most of what back-office work needs, including the
ISO 20022 messages used for SEPA. Colleagues in finance can read a short Python script
and tell us when the logic is wrong, which has already happened twice.

The payment path itself has different needs and is covered by
[ADR-003](adr-003-go-latency-critical.md).

## Decision

Back-office services and jobs are written in Python 3.

- **What counts as back-office.** A service or job is back-office when nothing a
  cardholder or a merchant does waits on it synchronously. When in doubt, the
  architecture review decides, and the answer is recorded in the service's README.
- **Typing.** Public functions carry type hints, and the type checker runs in
  continuous integration. A failing type check fails the build.
- **Dependencies.** Every service pins its dependencies with a lock file. Upgrades
  follow the policy in [Dependency update policy](../release/dependency-updates.md).
- **Heavy lifting.** Large joins and aggregations happen in PostgreSQL
  ([ADR-004](adr-004-postgresql.md)), not in Python loops over millions of rows.
- **Shared contracts, not shared code.** Python and Go services agree on JSON shapes
  and database schemas. We do not maintain the same library twice to save a few lines.

## Consequences

- `settlement-batcher`, the reconciliation jobs and the admin tools are written in
  Python, and new back-office work starts there by default.
- We run two languages across the company. Engineers moving between teams may need to
  learn the other one, and on-call engineers must be able to read both.
- Python's speed is rarely the bottleneck for batch work, but a job that grows into a
  latency-sensitive service must be rewritten, not tuned forever. That rewrite is an
  ADR of its own.
- Style rules, formatting and the supported interpreter versions are kept in
  [Coding standards](../engineering/coding-standards.md), not here, so that they can
  change without a new ADR.

## Alternatives considered

- **Go everywhere.** One language is simpler, but Go's libraries for spreadsheets and
  bank file formats were thin in 2017, and most of the team would have been learning
  while building the settlement flow.
- **A language on the Java platform.** Mature and fast, but nobody on the team wanted
  to run it, and start-up times sit badly with short batch jobs.
- **Ruby.** Two engineers liked it; the libraries for financial file formats were
  weaker than Python's.

## Related ADRs

- [ADR-003](adr-003-go-latency-critical.md): Go for latency-critical services.
- [ADR-004](adr-004-postgresql.md): PostgreSQL as the default database.
