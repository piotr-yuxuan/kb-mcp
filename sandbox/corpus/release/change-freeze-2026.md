---
title: "Change freeze calendar 2026"
---

# Change freeze calendar 2026

Owner: Bram Oyelaran, head of platform engineering. Published: 2026-09-07. Last reviewed: 2026-10-14.

Two production change freezes are planned for the end of this year: 23 November to 1 December 2026, and 17 December 2026 to 4 January 2027. Please put them in your team's planning now: work that is not in production by the last deploy day before a freeze waits until the first deploy day after it.

| Freeze | Starts | Ends (inclusive) | Last deploy day before | First deploy day after |
|---|---|---|---|---|
| Peak trading | Monday 23 November 2026 | Tuesday 1 December 2026 | Thursday 19 November | Wednesday 2 December |
| Year end | Thursday 17 December 2026 | Monday 4 January 2027 | Wednesday 16 December | Tuesday 5 January 2027 |

The peak trading freeze covers the Black Friday weekend and the Monday after it, our marketplaces' busiest days of the year. The year-end freeze covers reduced staffing, the bank holidays, and the heavy settlement volumes of the last days of December.

## What is frozen

- The canary and full rollout stages in Shipwright, for every service. Build, test and staging keep running.
- Schema migrations, including expand steps.
- Infrastructure changes: node pools, cluster versions, ingress, network policy, Strongroom policies.
- Turning feature flags up, so that more merchants get new behaviour.

What is not frozen: engaging a kill switch, and turning a flag down or off. Those are always allowed; see [Feature flags and kill switches](feature-flags.md).

## Exceptions

**Any exception needs a `CHG-` ticket approved by the head of platform engineering.** That includes hotfixes for a declared SEV1 or SEV2. Approval from your own lead, or from Site Reliability, is not enough this year.

To ask for one:

1. Raise a ticket in the Change Register with the type "Freeze exception"; see [Raising a change ticket](change-tickets.md).
2. Say why it cannot wait for the first deploy day after the freeze, and what waiting would cost, in merchants affected or money.
3. Name the person who will deploy and watch the release, and give the back-out plan.
4. Post the ticket key in `#team-platform`. Expect an answer within one working day.

During an incident, raise the ticket with the type "Emergency" and say so in the incident channel. The head of platform engineering is reachable through Klaxon throughout both freezes for exactly this, and approves in the Change Register; the IC's approval in Shipwright is still needed as well.

An approved exception still goes through every stage of the pipeline, canary included. Unless it is an emergency during a declared SEV1 or SEV2, it also respects the deploy windows on [How code reaches production](deployment-pipeline.md).

## Getting ready

- **The week before the last deploy day:** land anything large or risky. Thursday 19 November itself is for small releases only.
- **Contract steps of migrations** that are due in late November should run before the freeze or wait until December; see [Database migrations](database-migrations.md).
- **Kill switches:** each team confirms in `#team-platform` that its kill switches were exercised in `staging-eu` this quarter.
- **On-call:** rotas covering both freezes are agreed in Klaxon before the first freeze starts, with swaps settled early; see [On-call rota and paging policy](../incidents/on-call.md).

## What changed since 2025

Exceptions in 2025 were approved by the site reliability lead; they now go to the head of platform engineering, so that one person sees every request across both freezes. Turning flags up is now listed explicitly as frozen. The 2025 dates and outcomes are on [Change freeze calendar 2025](change-freeze-2025.md).
