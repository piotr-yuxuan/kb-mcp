---
title: "Launch checklist"
---

Owner: Ama Rowntree. Last reviewed: 2026-05-18.

Use this checklist for anything that changes what merchants see or do: a new feature, a new API endpoint, a change in pricing or a change in a default. Copy it into the epic's description in ENG, tick items as they are done, and link the evidence.

Not every item applies to every launch. Strike out what does not apply and say why in one line; do not delete it.

## Launch sizes

| Size | Examples | What changes |
|---|---|---|
| Large | Self-serve refunds, euro settlement | Every section applies; leadership is told the date a week ahead |
| Medium | Saved views, a new report | Skip the commercial section unless pricing changes |
| Small | A new filter, a copy change | Product, engineering and support sections only |

## Product

- [ ] Brief written and linked from the epic, with goals, non-goals and metrics.
- [ ] The key result the launch serves is named on the quarter's OKR page.
- [ ] Success metrics are visible on a Lantern dashboard before launch, not after.
- [ ] Release stage decided: pilot, preview or generally available, as defined in [Product terminology](terminology.md).
- [ ] Entry drafted for the [Merchant Hub release notes](merchant-hub-release-notes-2026.md).

## Engineering

- [ ] The feature is behind a Switchboard flag, with a plan to remove it after full rollout; see [Feature flags and kill switches](../release/feature-flags.md).
- [ ] Rollout goes through the normal [deployment pipeline](../release/deployment-pipeline.md), including the canary.
- [ ] A change ticket is raised if the change is high-risk; see [Raising a change ticket](../release/change-tickets.md).
- [ ] The launch date avoids the dates on the [change freeze calendar](../release/change-freeze-2026.md).
- [ ] API changes follow the [API design guidelines](../engineering/api-design.md) and are versioned as [ADR-023](../architecture/adr-023-api-versioning.md) requires.

## Reliability

- [ ] The service's SLO covers the new path, or a new SLO is added to the [SLO catalogue](../incidents/slo-catalogue.md).
- [ ] Alerts route to the owning team's Klaxon rota.
- [ ] The on-call engineers have read a short runbook for the feature.

## Security and privacy

- [ ] Data the feature stores is classified; see [Data classification](../security/data-classification.md).
- [ ] New personal data, or a new use of it, has been discussed with `privacy@quillmoor.example`.
- [ ] Any new third-party supplier has passed the [vendor security review](../security/vendor-security-review.md).

## Design and accessibility

- [ ] Every new screen passes the [Accessibility checklist](../design/accessibility.md).
- [ ] Screens follow [Theming and dark mode](../design/theming.md).
- [ ] Copy follows the [Content style guide](../design/content-style.md).

## Support

- [ ] Merchant Support has had a walkthrough at least a week before a large launch.
- [ ] Harbour macros written or updated; see [Support macros](../support/macros.md).
- [ ] The escalation path for the feature is agreed with Femi Haldane's team.
- [ ] French translations reviewed by Inès Moreau's team, for anything in Merchant Hub.

## Commercial and legal

- [ ] Pricing, if any, is on the [pricing overview](pricing.md).
- [ ] Contract or terms changes requested through Clausebook.
- [ ] Account managers have the talking points for strategic merchants.

## After launch

- [ ] Metrics reviewed at two weeks and at the end of the quarter.
- [ ] The Switchboard flag removed on schedule.
- [ ] The brief updated with results.
