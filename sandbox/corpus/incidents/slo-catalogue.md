---
title: "SLO catalogue"
---

# SLO catalogue

Owner: Lukas Brennand, Site Reliability. Last reviewed: 2026-10-05.

A **service level objective (SLO)** is the reliability we aim for on a service,
expressed as the share of good events over a rolling window. It sits below 100% on
purpose: the gap is the service's **error budget**, which the owning team may spend on
releases, experiments and the occasional bad day. When the budget runs out, the team
spends its time on reliability instead.

This page lists every SLO we have published. Each is measured in Lantern and has its
own panel on the dashboard "SLO overview".

## The catalogue

| Service | SLO | Good event | Window | Error budget per window |
|---|---|---|---|---|
| `card-auth` | **99.95%** | An authorisation request answered with a decision, approve or decline, without a Quillmoor-side error | 28 days, rolling | 0.05% of requests; about 20 minutes of total outage |
| `payout-gateway` | **99.9%** | A payout batch submitted on its 15-minute schedule and acknowledged by the bank without `PGW-5021` | 28 days, rolling | 0.1% of batches; about 40 minutes of total outage |
| `merchant-api` | **99.9%** | A request answered with anything other than a 5xx status; 429 responses count as good | 28 days, rolling | 0.1% of requests; about 40 minutes of total outage |

Notes on the definitions:

- **`card-auth`.** An issuer's own decline is a good event: we answered. A `CAU-1207`
  timeout counts against the budget, even though the issuer caused it, because the
  merchant cannot tell the difference. The SEV1 of
  [2025-09-17](report-2025-09-17-card-auth-latency.md) spent the whole of that window's
  budget in under two hours.
- **Latency.** The `card-auth` p99 budget of 800 ms is a separate commitment, enforced
  by the `CardAuthP99High` alert rather than by this SLO.
- **`payout-gateway`.** A batch held back by the kill switch during an incident is not
  counted either way; a batch that becomes stuck is a bad event, whatever the cause.
- **`merchant-api`.** Measured at our edge, so a merchant's own network problems do not
  count.

## Burn alerts

Error budget burn alerts came with ENG-12, SLO dashboards in Lantern, in ENG Sprints 12
to 19. Each SLO has two:

| Alert | Fires when | Action |
|---|---|---|
| Fast burn | 2% of the window's budget is spent in 1 hour | Pages the owning team's on-call |
| Slow burn | 10% of the budget is spent in 3 days | Ticket for the owning team, raised in its channel |

A fast burn alert is often the first sign of an incident; treat it as you would any
other page under the [on-call policy](on-call.md).

## When the budget runs out

If a service has spent its whole budget for the current window:

1. The owning team pauses releases that add features to that service. Fixes,
   security patches and reliability work continue.
2. The team lead posts in `#team-sre` what spent the budget and what is being done.
3. The pause ends when the rolling window recovers, or earlier with the agreement of
   the head of the owning department.

This has happened twice: to `card-auth` after the SEV1 of September 2025, and to
`merchant-api` for nine days in March 2026.

## What is not here yet

`ledger`, `fx-quote`, `notify` and `merchant-hub` have no published SLO. The ledger is
judged by its reconciliation rather than its availability; the others have proposals
under discussion in `#team-sre`. A team that wants to add an SLO writes it up with a
good-event definition and a quarter of history, and Site Reliability adds it here.

## These are internal figures

Never quote a figure from this page to a merchant or put it in a contract. Merchant
contracts carry their own, looser commitments, which belong to Legal; see the
[MSA clause guide](../legal/msa-clause-guide.md).
