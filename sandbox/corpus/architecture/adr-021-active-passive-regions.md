---
title: "ADR-021: Active-passive multi-region"
---

- **Status:** Accepted, 2025-09-08
- **Author:** Lukas Brennand
- **Deciders:** Ottilie Marsh, Bram Oyelaran, Kwabena Stroud, Nadia Ferreira,
  Yusuf Achterberg, Callum Ibe

## Context

Since 2017, everything Quillmoor runs in production has lived in one region of our
cloud provider. Within that region we spread across zones, and we have survived the
loss of a zone more than once without merchants noticing. We have never had a plan
for the loss of the whole region, other than restoring backups somewhere else, which
we have never tried and estimate would take days.

Three things make that no longer acceptable:

- **Our partners ask.** Our settlement bank and the card schemes now want a recovery
  plan that has been tested, not described.
- **Our size.** A day without Quillmoor Pay is a day without sales for every
  marketplace we serve, and a day without payouts for their sellers.
- **It is now feasible.** With one database per service
  ([ADR-012](adr-012-database-per-service.md)), events on a replicated log
  ([ADR-019](adr-019-replicated-event-log.md)) and secrets in one store
  ([ADR-020](adr-020-strongroom.md)), each piece of state has one owner and one
  replication story.

## Decision

We run in two regions, both in Europe, in an active-passive arrangement.

- **The primary region** serves all traffic, all the time, under normal conditions.
- **The standby region** runs a copy of every service at minimum size, ready to scale
  up. It serves no merchant traffic while the primary is healthy.
- **PostgreSQL**: every service database has a replica in the standby region, kept by
  asynchronous streaming replication.
- **Kafka**: every topic is mirrored to the standby region, with consumer offsets.
- **Strongroom and Switchboard** are replicated to the standby region, so that
  services there can start and read their flags without the primary.
- **Failover is a human decision.** Nothing fails over automatically. The IC of a SEV1
  proposes it, as defined in
  [Production incident management](../incidents/incident-management.md), and the head of platform engineering, or the chief
  technology officer, decides.
- **Targets.** Once the decision is taken, we aim to be serving merchants from the
  standby region within 1 hour, and to lose at most 5 minutes of committed writes.
- **Payouts restart last.** `payout-gateway` does not send batches from the standby
  region until Payouts has confirmed with our settlement bank which batches it
  received, because a batch recorded in the lost minutes could otherwise be sent twice.
- **Failback** to the primary is planned, rehearsed and done in a deploy window, never
  in a hurry.
- **Testing.** We fail over for real in a game day at least once a year. The first is
  planned for April 2026; see [Game day April 2026: region failover](../incidents/game-day-2026-04.md).

### What a failover looks like

The detailed runbook belongs to Site Reliability and is rehearsed at each game day. In
outline:

1. The IC declares that the primary region is lost or unusable, and the decision to
   fail over is taken and recorded in the incident channel.
2. Writes to the primary are fenced, where the primary can still be reached, so that
   nothing writes to both regions.
3. The PostgreSQL replicas in the standby region are promoted, the ledger's first.
4. Services in the standby region are scaled up to production size, and consumers
   resume from their mirrored offsets.
5. Public addresses are switched to the standby region.
6. `card-auth` and `merchant-api` take traffic first; then `notify` and the dashboard;
   `payout-gateway` and `settlement-batcher` last, once Payouts has confirmed the
   bank's view of in-flight batches.
7. Ledger reconciles against the bank, as described below.

## Consequences

- We pay for a standby that does nothing on most days: about a quarter of our
  production compute, plus storage for the replicas.
- Writes committed in the primary in the last few minutes before a loss may be
  missing in the standby. The ledger is reconciled against the bank's statements after
  a failover, using the usual process in
  [Runbook: ledger reconciliation breaks](../payments/ledger-reconciliation.md).
- Every infrastructure change now happens twice. Platform upgrades clusters one region
  at a time, the standby first; the Kubernetes upgrade in ENG-9 is the first to follow
  that rule.
- Public addresses, such as `api.quillmoor.example`, switch region through DNS with a
  short time to live, which we lowered ahead of this work.
- Runbooks must say which region they apply to, or that they apply to both.

## Alternatives considered

- **Active-active.** Both regions serving traffic. `card-auth` could work this way,
  but the ledger needs a single writer for each account, and two regions each sending
  payouts would turn every network split into a risk of paying sellers twice. The
  complexity is far beyond what the benefit is worth to us today.
- **Backup and restore only.** Cheapest by far, but recovery would take days, and we
  could not test it without rebuilding everything.
- **Stay in one region.** We can no longer answer our partners' questions with that.

## Related ADRs

- [ADR-010](adr-010-kubernetes.md): the clusters, now one set per region.
- [ADR-012](adr-012-database-per-service.md): one database per service, one replica each.
- [ADR-019](adr-019-replicated-event-log.md): topics mirrored between regions.
- [ADR-020](adr-020-strongroom.md): secrets available in both regions.
