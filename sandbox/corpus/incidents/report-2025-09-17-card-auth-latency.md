---
title: "Incident report 2025-09-17: card authorisation latency"
---

# Incident report 2025-09-17: card authorisation latency

**SEV1.** Identifiers: `CAU-1207 ISSUER_TIMEOUT`, `CardAuthP99High`. Channel
`#inc-card-auth-latency`. IC: Lukas Brennand. Operations lead: Corinne Aske, Payments
Core. Communications lead: Femi Haldane. Written by Corinne Aske; reviewed on
2025-09-22; approved by Nadia Ferreira. Final.

## Summary

On Wednesday 17 September 2025, during the evening shopping peak, one large card
issuer began answering authorisation requests slowly. Requests to that issuer waited
the full 3 seconds before failing with `CAU-1207`, and while they waited they held
`card-auth`'s workers. Within twenty minutes the worker pool was exhausted and
payments to every issuer were slowing down or failing. We scaled `card-auth` to its
maximum and lowered 3DS step-up sampling, which restored service for every other
issuer by 18:21 UTC. The issuer recovered by itself at 19:31 UTC.

## Impact

- Merchant impact lasted **1 hour 47 minutes**, from 17:44 to 19:31 UTC.
- About **41,800 authorisations** were declined or failed, across **1,930
  merchants**. Roughly 70% were payments to the slow issuer, which we could not have
  saved. The other 30% were payments to healthy issuers that failed because our own
  workers were all busy, between 18:02 and 18:21.
- At the worst point, 18:08 to 18:21, the approval rate across all issuers fell from
  its usual 91% to 64%.
- Buyers saw a decline and most could retry with another card. No payment was
  captured twice or lost; no money moved wrongly.

It was a SEV1 because payments were failing for many merchants, not only for the
issuer's cardholders.

## Timeline (UTC)

- **17:42** The issuer begins answering slowly (confirmed later through the acquiring
  bank).
- **17:44** `CAU-1207` rises above 1% of authorisations. Impact starts.
- **17:45** `card-auth` p99 crosses 800 ms.
- **17:55** `CardAuthP99High` fires after 10 minutes over budget; Klaxon pages
  `payments-primary`.
- **17:57** Corinne Aske acknowledges.
- **18:02** On the Lantern dashboard "card-auth overview", declines are now rising for
  every issuer, not just one. Corinne declares a SEV1.
- **18:05** Lukas Brennand takes IC from the IC rota.
- **18:08** Approval rate at 64%. Every `card-auth` worker is busy; most are waiting on
  the slow issuer.
- **18:11** `card-auth` scaled from 18 pods to 40, its maximum, by hand. Autoscaling had
  not reacted: waiting workers use no CPU.
- **18:14** Femi Haldane joins as communications lead.
- **18:19** 3DS step-up sampling lowered with `sb.card-auth.stepup-sampling`, removing
  step-up round trips from the busiest path.
- **18:21** p99 for other issuers back under 800 ms. Approval rate 84%, almost all of
  the shortfall now on the slow issuer.
- **18:24** First Beacon update: Card payments "Partial outage".
- **18:31** Ottilie Marsh, CTO, informed by the IC.
- **18:40** The acquiring bank confirms that the issuer has an incident of its own.
- **18:54, 19:24** Beacon updates.
- **19:31** The issuer recovers. `CAU-1207` back under 0.1%. Impact ends.
- **19:45** Beacon: Monitoring.
- **19:50** Step-up sampling restored to its previous value.
- **20:15** Resolved. `card-auth` allowed to scale back down from 20:30.

## Root cause

The trigger was outside our control: an issuer having a bad evening. What turned one
issuer's problem into everyone's problem was ours.

`card-auth` sent requests for every issuer through one shared pool of workers. A
request to a slow issuer holds a worker until the issuer answers or the 3-second
timeout expires. With nothing limiting how many workers one issuer could hold, the
slow issuer gradually took all of them, and requests for healthy issuers queued
behind it.

Two things made it worse:

- **Autoscaling looked at CPU.** Workers waiting on the network use almost no CPU, so
  `card-auth` stayed at 18 pods while it ran out of capacity.
- **The runbook did not mention the step-up lever.** Corinne found it by reading the
  Switchboard keys. The [card authorisation latency runbook](../payments/card-auth-latency.md)
  now lists it.

## What went well

- The 3-second issuer timeout, lowered from 5 seconds under ENG-3 at the start of the
  month, freed workers sooner. At 5 seconds the pool would have run out roughly
  twice as fast.
- Scaling to 40 pods was quick and safe. We watched for `CAU-1301` while the new pods
  came up, and none appeared.
- The acquiring bank confirmed the issuer's incident within 40 minutes of declaration,
  which let us stop looking for a cause on our side.

## What was difficult

- The first Beacon update went out **22 minutes** after declaration, against a target
  of 15. Femi joined at 18:14 and wrote it from scratch, while the IC was busy with
  the scaling decision.
- Nobody was sure who should tell executives, or when.

## Where we got lucky

The issuer recovered by itself. Had it stayed slow all evening, we had no way to stop
it taking our capacity except by scaling, and 40 pods was the ceiling.

## Actions

| # | Action | Type | Owner | Ticket | Status |
|---|---|---|---|---|---|
| 1 | Per-issuer concurrency limits in `card-auth`, so that one issuer can hold at most a fixed share of workers | Prevent | Corinne Aske | `pir-action` under ENG-3 | Done |
| 2 | Autoscale `card-auth` on in-flight requests as well as CPU | Mitigate | Corinne Aske | `pir-action` under ENG-3 | Done |
| 3 | Draft the first SEV1 Beacon update from a template when the incident is declared | Process | Lukas Brennand | `pir-action` under ENG-13 | Done (2026) |
| 4 | Add executive notification within 30 minutes of a SEV1 to the incident policy | Process | Lukas Brennand | `pir-action` | Done |
| 5 | Add step-up sampling and a per-issuer latency panel to the runbook and dashboard | Mitigate | Nadia Ferreira | `pir-action` under ENG-3 | Done |

Action 3 waited for ENG-13 in 2026; until then, the communications lead kept a copy of
the template pinned in `#team-sre`. See [status page communications](status-page.md)
and [production incident management](incident-management.md) for the resulting
changes.
