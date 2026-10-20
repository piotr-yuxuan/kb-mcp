---
title: "ADR-020: Strongroom as the only secrets store"
---

- **Status:** Accepted, 2025-06-16
- **Author:** Callum Ibe, head of security
- **Deciders:** Ottilie Marsh, Bram Oyelaran, Lukas Brennand, Nadia Ferreira

## Context

Most of our services read their secrets from Strongroom, our secrets manager. Most is
not all. An inventory carried out by Security in April found secrets in five places:

1. Strongroom, for about two thirds of production secrets;
2. Kubernetes secret objects created by hand, for services that predate Strongroom
   or were set up in a hurry;
3. variables in our continuous integration system, including two production database
   passwords;
4. configuration files committed to repositories, each one already a scanner finding;
5. engineers' laptops, as files used for "just this once" maintenance.

Each place has its own access controls, its own audit trail or none, and its own way
of being rotated or not. When a secret leaks, the first question is "where else is it
stored?", and the answer takes hours. We could not rotate production credentials on a
schedule, because nobody could list them all.

## Decision

Strongroom is the only place where a secret is stored at Quillmoor.

- **Services** read their secrets from Strongroom at start-up and whenever Strongroom
  renews them, through the Strongroom agent that runs beside every workload. Secrets
  are held in memory and never written to a container's disk.
- **Pipelines** fetch short-lived credentials from Strongroom for each run. No secret
  is kept as a variable in continuous integration.
- **People** read secrets through Strongroom's command line or web console, signed in
  with single sign-on. Every read is logged against a name.
- **Kubernetes secret objects** may be created only by the Strongroom agent. The
  clusters refuse any created by hand.
- **Repositories** hold no secrets, not even encrypted ones. A secret found in a
  repository, a chat message, a ticket or a laptop file is treated as leaked, and
  handled as described in
  [Playbook: leaked secret or API key](../security/leaked-secret.md).
- **Ownership.** Every secret has an owning team, recorded in Strongroom, which is
  responsible for rotating it.

Everyday tasks, such as adding a secret, granting a service access to it or reading
one during an incident, are described in [Using Strongroom](../security/strongroom-how-to.md).

## Consequences

- One inventory, one audit trail and one place to rotate. Automating rotation becomes
  possible; that work is ENG-14.
- Strongroom becomes critical. If it is unavailable, services that are already running
  keep the secrets they hold, but new pods cannot start. Platform runs it with replicas
  and monitors it as a tier-one service.
- Moving the remaining third is work for every team. Security gives each team a list
  of its secrets outside Strongroom, and the deadline is the end of September.
- The few engineers used to keeping a credential on their laptop for maintenance lose
  that habit, and some lose an afternoon. That is the point.

## Alternatives considered

- **The secrets store offered by our cloud provider.** Good, but it would mean a
  second store beside Strongroom for the card data environment, which is where we most
  need one.
- **Keep several stores, with a policy for each.** That is the situation the inventory
  found, with a policy added. It does not answer "where else is it stored?".
- **Encrypted secrets in repositories.** Convenient for small teams, but every clone
  becomes a copy of the secret, and rotation means a commit in every repository that
  holds one.

## Related ADRs

- [ADR-010](adr-010-kubernetes.md): the clusters whose secret objects are now managed
  by the agent.
- [ADR-012](adr-012-database-per-service.md): each service's database credentials,
  one role per service, now held here.

## Update, 2025-10-13

The migration finished at the end of September. ENG-14 is done, and production
database credentials are now rotated on a schedule by Strongroom.
