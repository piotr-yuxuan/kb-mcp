---
summary: "One severity scale for incidents, security and support"
---

## Problem

We run three scales: SEV1 to SEV4 for [production incidents](../../corpus/incidents/incident-management.md),
S1 to S4 for [security incidents](../../corpus/security/incident-response-plan.md), and
P1 to P4 for [support tickets](../../corpus/support/priorities-and-slas.md). New joiners
mix them up, and during the February 2026 Merchant Hub outage a P1 was read as a SEV1
for twenty minutes.

## Idea

Keep three scales for what they measure, but name them so that they cannot be confused,
and publish one table that maps each level to the others and to who gets paged.

## Not in scope

Changing any response time or on-call rule.

Raised by Lukas Brennand and Femi Haldane.
