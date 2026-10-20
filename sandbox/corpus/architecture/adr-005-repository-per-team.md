---
title: "ADR-005: One repository per team"
---

- **Status:** Accepted, 2017-10-16
- **Author:** Bram Oyelaran
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Yusuf Achterberg, Kwabena Stroud

## Context

Since January all our code has lived in a single Git repository, `quillmoor`. That
suited eleven engineers. We are now twenty-six, organised into four teams (Payments
Core, Payouts, Ledger and Merchant Experience), with a fifth, Platform, forming this
quarter. The single repository is starting to hurt:

- **Continuous integration** runs every test for every change. A typo fix in the
  merchant dashboard waits twenty-five minutes for the ledger's integration tests.
- **Ownership is unclear.** Directories have no owners, so changes to `card-auth`
  are sometimes approved by people who have never run it.
- **Releases are coupled.** A broken test in one team's code blocks every other team's
  merge until someone fixes it, usually not the person who broke it.
- **Access is all or nothing.** Contractors helping with the dashboard can read the
  settlement code and its configuration.

We looked at fixing these inside one repository. The tooling to run only affected
tests, enforce directory owners and split access exists, but adopting it is a project
in itself, and we have no one free to run it.

## Decision

Each team owns exactly one Git repository, named after the team: `payments-core`,
`payouts`, `ledger`, `merchant-experience` and `platform`.

1. **Layout.** A team's services live under `services/<service>/`, its internal
   libraries under `libs/`. A repository may hold both Python and Go code
   ([ADR-002](adr-002-python-back-office.md), [ADR-003](adr-003-go-latency-critical.md)).
2. **Owners.** The repository's owners file names the team. Every change needs a
   review from someone in the owning team; the number of approvals is set in
   [Code review guidelines](../engineering/code-review.md).
3. **Shared libraries.** Code used by more than one team lives in the `platform`
   repository and is published as versioned packages. Other teams depend on released
   versions, never on source paths in another repository.
4. **Moving a service.** When a service changes team, it moves to the new team's
   repository with its history. The old path keeps a pointer for six months.
5. **Cross-team changes.** A change that spans teams is made as one change per
   repository, each linked to the others and merged in dependency order.

## Consequences

- Each team's continuous integration runs only its own tests. Early measurements on a
  copy of `payouts` show builds under six minutes.
- Ownership is explicit and enforced by the hosting, not by convention.
- Atomic changes across teams are no longer possible. Renaming a field used by three
  teams becomes three changes and a short period where both names work.
- Library versions drift between teams. We need a policy for keeping them current,
  now kept in [Dependency update policy](../release/dependency-updates.md).
- Team reorganisations now have a cost in repository moves. We accept it: teams change
  less often than code does.
- Branching, commit messages and tags follow the shared rules in
  [Git conventions](../engineering/git-conventions.md), whichever repository you are
  in.

## Alternatives considered

- **Keep one repository and invest in tooling.** A build system with fine-grained
  caching and affected-test detection would solve the speed problem, and owners files
  per directory the ownership one. It remains the better end state on paper, but costs
  months of one engineer we do not have.
- **One repository per service.** Clean boundaries, but with nine services and five
  teams it multiplies configuration, permissions and dependency upgrades for little
  gain. We may revisit it for services that are shared across teams.
- **Do nothing.** The status quo gets worse with every hire.

## Related ADRs

- [ADR-002](adr-002-python-back-office.md) and [ADR-003](adr-003-go-latency-critical.md):
  the two languages a team repository may hold.
- [ADR-012](adr-012-database-per-service.md): ownership of data follows the same
  service boundaries.
