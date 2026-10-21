---
title: "Escalation contacts for incidents"
---

# Escalation contacts for incidents

Who to bring in, in what order, when an incident needs more than the on-call. Kept by
Site Reliability; each team checks its own row at the quarterly access review. Last
reviewed: 2026-10-12, after the October access review.

> [!TIP]
> Phone numbers are not on this page on purpose. Every person and rota below has a
> contact card in Klaxon, which is kept up to date from Haven. Page through Klaxon
> whenever you can, so that the page is logged.

## By area

| Area | First | Then | Head of area |
|---|---|---|---|
| Card payments: `card-auth`, `fx-quote` | `payments-primary` in Klaxon, or payments-oncall@quillmoor.example | `payments-secondary` | Nadia Ferreira |
| Payouts and settlement: `payout-gateway`, `settlement-batcher` | `payments-primary` | `payouts` rota | Yusuf Achterberg, then Nadia Ferreira |
| Ledger and reconciliation | `payments-primary` | `ledger` rota | Kwabena Stroud, then Nadia Ferreira |
| Merchant Hub, Merchant API, merchant emails and webhooks | `merchant-exp-primary` | `merchant-exp-secondary` | The Merchant Experience team lead, in `#team-merchant-hub` |
| Kubernetes, Shipwright, Switchboard, Apache Kafka | `platform-primary` | `platform-secondary` | Bram Oyelaran |
| Lantern, Klaxon, anything without an owner | `sre-primary` | `sre-secondary` | Lukas Brennand |
| Fraud model and `risk-scorer` | `risk-ml-primary` | Risk ML team channel | Mireille Okonkwo |
| Warehouse and pipelines | `data-primary` | Data Platform team channel | Tomasz Wilde |
| Suspected security incident | `security-oncall`, or security@quillmoor.example | The SIRT | Callum Ibe |
| Personal data involved | privacy@quillmoor.example | Beatrix Sallow, DPO | Saoirse Lindqvist |
| Merchants and Support | `comms-lead` | Support team leads | Femi Haldane; Inès Moreau for French-speaking merchants |

For the fraud model, the on-call can act alone: see
[rolling back a model in production](../ml/model-rollback.md).

## Executives

| When | Who | How |
|---|---|---|
| Every SEV1, within 30 minutes | Ottilie Marsh, CTO | The IC, by Klaxon page and a message in the channel |
| SEV1 lasting more than an hour, or in the press | Hollis Varga, chief executive | Ottilie Marsh calls; nobody else needs to |
| Money paid or priced wrongly, above £10,000 | Idris Kallenberg, CFO | Arjun Pelletier, finance director, after a first estimate |
| A merchant contract or a regulator involved | Saoirse Lindqvist, general counsel | legal@quillmoor.example, then a call |

## Outside Quillmoor

We do not contact banks or card schemes casually during an incident. Each relationship
has one owner, who makes the call:

| Counterparty | Who calls | Notes |
|---|---|---|
| Our settlement bank's operations desk | The `payouts` rota, or Yusuf Achterberg | For stuck batches and throttling. The desk answers around the clock |
| The acquiring bank's incident desk | The payments on-call, or Nadia Ferreira | The route for anything involving an issuer; we never contact issuers directly |
| The card schemes | Nadia Ferreira only | Rare; the acquiring bank usually handles it |
| The FX rate feed provider | Payments Core | Support line in the provider's Klaxon contact card |
| Merchants | Merchant Support only | Engineers do not contact merchants during an incident |

## Shared addresses

| Address | Goes to |
|---|---|
| payments-oncall@quillmoor.example | A Klaxon page to the payments on-call |
| security@quillmoor.example | The security on-call |
| privacy@quillmoor.example | The privacy team and the DPO |
| legal@quillmoor.example | The Legal team's shared inbox |
| finance@quillmoor.example | The Finance team's shared inbox |
| workplace@quillmoor.example | Workplace, for building access outside office hours |

## When nobody answers

Klaxon escalates on its own along the chains in the [on-call policy](on-call.md). If a
whole chain is silent, page `sre-primary`: Site Reliability will find someone. And if
it is a SEV1, the IC may call any head of area directly, at any hour.
