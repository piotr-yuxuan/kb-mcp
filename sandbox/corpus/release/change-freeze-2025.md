---
title: "Change freeze calendar 2025"
---

# Change freeze calendar 2025

> [!NOTE]
> These freezes are over. The current calendar is [Change freeze calendar 2026](change-freeze-2026.md).

Owner: Platform (release engineering). Last reviewed: 2026-01-12.

In 2025 Quillmoor froze production changes twice: from 24 November to 2 December 2025, around the busiest trading days of our marketplaces, and from 18 December 2025 to 5 January 2026, over the year end.

| Freeze | From | To (inclusive) | Why |
|---|---|---|---|
| Peak trading | Monday 24 November 2025 | Tuesday 2 December 2025 | The Black Friday weekend and the Monday after it, when card volumes run at about three times a normal week |
| Year end | Thursday 18 December 2025 | Monday 5 January 2026 | Reduced staffing, bank holidays, and heavy settlement volumes |

Production deploys resumed on Wednesday 3 December 2025 and on Tuesday 6 January 2026.

## What the freeze covered

- the canary and full rollout stages in Shipwright, for every service;
- infrastructure changes: Kubernetes, networking, Strongroom policies;
- schema migrations, including expand steps;
- turning feature flags up for more merchants.

## What stayed allowed

- engaging kill switches, and turning flags down or off;
- hotfixes for a declared SEV1 or SEV2, through the [hotfix process](hotfix-process.md);
- build, test and staging, so that releases were ready for the first deploy day after each freeze.

## Exceptions in 2025

In 2025 an exception needed a `CHG-` ticket approved by the site reliability lead, Lukas Brennand. The approval rule changed for 2026; see that year's page.

| Freeze | Exception requests | Approved | Incidents during the freeze |
|---|---|---|---|
| Peak trading | 7 | 4 | One SEV3, on 2 December ([its report](../incidents/report-2025-12-02-ledger-break.md)) |
| Year end | 5 | 3 | None above SEV4 |

The approved exceptions were: two fixes to merchant-facing exports in Merchant Hub, a Strongroom certificate renewal that could not wait, a `risk-scorer` configuration change requested by Risk Operations, and three small `merchant-api` fixes in the year-end freeze. The five refusals were all changes that could have shipped the week before the freeze.

## What we took into 2026

- Publish the calendar earlier. The 2025 dates went out in late October, and several teams planned launches into the first freeze without noticing.
- Say explicitly that turning a flag up is a change. Two teams argued in 2025 that it was not.
- Hold the last deploy day before each freeze for small, low-risk releases; big ones belong a week earlier.

How deploy windows work outside freezes is on [How code reaches production](deployment-pipeline.md). The exception tickets themselves are still in the Change Register, filed under the type "Freeze exception", for anyone who wants to see what was asked for and why.
