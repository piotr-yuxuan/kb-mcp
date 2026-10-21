---
title: "Payments engineering teams"
---

Payments engineering is three teams under Nadia Ferreira, head of payments engineering. Between them they own the services that take card payments, pay sellers and keep the books. Last reviewed 2026-10-01 by Nadia Ferreira.

## Who does what

| Team | Lead | Chat channel | Services | Klaxon rota |
|---|---|---|---|---|
| Payments Core | Nadia Ferreira | `#team-payments-core` | `card-auth`, `fx-quote` | `payments-core` |
| Payouts | Yusuf Achterberg | `#team-payouts` | `payout-gateway`, `settlement-batcher` | `payouts` |
| Ledger | Kwabena Stroud | `#team-ledger` | `ledger`, the nightly reconciliation | `ledger` |

Payments Core has no separate team lead; Nadia leads it directly, alongside her role as head of the group. Oskar Ngata, product manager for payouts, works with the Payouts team day to day and joins the weekly sync.

### Payments Core

Card authorisation and currency quotes: everything on the path between a merchant's checkout and the issuer's answer. The team guards the `card-auth` latency budget and the boundary of the card data environment, and decides what may be added to the authorisation path. Its runbook is [Runbook: card authorisation latency](card-auth-latency.md).

### Payouts

Payouts to marketplace sellers in GBP and EUR, from the moment a balance becomes payable to the moment our settlement bank confirms the payment. The team also holds the day-to-day relationship with the settlement bank's operations desk. Its runbook is [Runbook: rolling back payout-gateway](payout-gateway-rollback.md).

### Ledger

The double-entry ledger and its reconciliation against the bank. The team reviews every change that posts journals, wherever it comes from, and works with Finance on month-end. Its runbook is [Runbook: ledger reconciliation breaks](ledger-reconciliation.md).

## How to reach us

- **Something is broken now:** page the payments on-call through Klaxon, or email `payments-oncall@quillmoor.example` if you cannot use Klaxon. Incidents run in `#inc-payments`. How the rotas page and hand over is in [On-call rota and paging policy](../incidents/on-call.md).
- **A question for one team:** its channel above. Tag the team rather than a person; whoever is on support duty that week answers.
- **A question for all three, or you do not know which:** `#team-payments-core`, and we will route it.
- **A design that touches payments:** book a slot in the Thursday payments design review through the channel, at least a week ahead, with a written proposal.

## Rituals

| Ritual | When | Who |
|---|---|---|
| Payments weekly sync | Tuesdays, 10:30 UK time | Leads, product, Site Reliability; open to anyone |
| Payments design review | Thursdays, 14:00 UK time | Anyone with a proposal, plus one engineer from each team |
| Suspense account review | Mondays | Ledger |
| Sprint planning | First Monday of each ENG sprint | Each team separately |

Notes from the weekly sync are published on the wiki; the most recent is [Payments weekly sync 2026-09-15](weekly-sync-2026-09-15.md).

## Neighbours

The payments teams depend on services owned elsewhere: `merchant-api`, `merchant-hub` and `notify` (Merchant Experience, `#team-merchant-hub`) and `risk-scorer` (Risk ML, `#team-risk-ml`). Site Reliability (`#team-sre`, lead Lukas Brennand) runs the platform beneath all of them and joins payments incidents of any size.
