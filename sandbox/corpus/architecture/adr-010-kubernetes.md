---
title: "ADR-010: Run services on Kubernetes"
---

- **Status:** Accepted, 2019-02-18
- **Author:** Lukas Brennand
- **Deciders:** Ottilie Marsh, Bram Oyelaran, Nadia Ferreira, Yusuf Achterberg

## Context

Our services run on virtual machines built from images and configured by scripts that
each team maintains. With forty engineers and fourteen deployable services and jobs,
this is costing us more each month:

- A deploy replaces machines one at a time and takes about forty minutes for the
  larger services. A deploy that fails half-way leaves a mix of old and new machines
  that someone has to tidy up by hand.
- Scaling is manual. Before the big marketplace sales in November we added machines
  by ticket, two days ahead, and removed them a week late.
- Every team has written its own deploy scripts, health checks and log shipping, and
  no two behave quite alike at three in the morning.
- Machines drift. A security patch applied by hand to some machines and not others
  took a week to find.

## Decision

Stateless services run as containers on Kubernetes.

- **Managed control plane.** We use the managed Kubernetes offered by our cloud
  provider. We run the workloads, not the control plane.
- **Clusters.** One cluster per environment, staging and production. The services
  inside the card data environment, starting with `card-auth`, run in a separate
  production cluster of their own, so that the scope of PCI DSS assessment stays as
  small as it is today.
- **State stays outside.** Databases remain hosted PostgreSQL
  ([ADR-004](adr-004-postgresql.md)), not containers in the cluster.
- **Ownership.** Platform owns the clusters, their upgrades and the shared add-ons.
  Teams own their workloads and declare them through one shared deployment tool, so
  that no team writes cluster manifests by hand. That tool became Shipwright; how code
  travels through it is described in
  [How code reaches production](../release/deployment-pipeline.md).
- **Resources.** Every workload declares requests and limits for processor and memory.
  A workload without them is refused by the cluster.
- **Autoscaling.** Services scale horizontally on load, between bounds the owning team
  sets and reviews.

## Consequences

- Deploys become rolling updates measured in minutes, and a failed rollout stops
  itself instead of leaving a half-updated fleet.
- Capacity for peaks is a number in a file rather than a ticket.
- Health checks, log shipping and metrics are set up once by Platform, for everyone.
- Kubernetes moves fast, and staying on a supported version is a recurring cost that
  Platform must plan for every year. The most recent such upgrade is ENG-9,
  Kubernetes 1.31.
- Engineers have new things to learn: pods, probes and why a container was killed for
  using too much memory. Platform runs a half-day introduction for every team.

## Alternatives considered

- **Keep virtual machines, with better tooling.** Shared images and one deploy tool
  would fix the drift and some of the scripts, but not the speed of deploys or the
  manual scaling.
- **A container service specific to our cloud provider.** Simpler to start with, but
  it ties every service's deployment format to one provider and offers less control
  over the card data environment's separation.
- **Functions as a service.** Attractive for small jobs, wrong for long-lived services
  with connection pools and strict latency budgets such as those under
  [ADR-003](adr-003-go-latency-critical.md).

## Related ADRs

- [ADR-004](adr-004-postgresql.md): databases stay outside the cluster.
- [ADR-011](adr-011-opentelemetry.md): tracing, set up once per cluster.
- [ADR-021](adr-021-active-passive-regions.md): a second region, with its own clusters.
