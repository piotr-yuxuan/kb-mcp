---
title: "Payments platform architecture"
---

- **Owner:** Nadia Ferreira, head of payments engineering
- **Reviewers:** Kwabena Stroud (Ledger), Yusuf Achterberg (Payouts)
- **Last reviewed:** 2026-10-06

This page describes how Quillmoor Pay and Quillmoor Payouts fit together: which service does what, where card data may live, and how money moves through the ledger. It is the starting point for new payments engineers and for anyone reviewing a design that touches a card or payout flow. It deliberately stays at the level of services and contracts; the runbooks linked at the end cover what to do when something breaks.

## Two terms used throughout

Two acronyms recur across the payments pages. They are defined here, once, and the other pages use them bare.

- **PAN**, the primary account number: the long number printed or embossed on a card, which identifies the card account at the issuer. A PAN is cardholder data under PCI DSS and is the most tightly controlled value we handle.
- **3DS**, 3-D Secure: the card schemes' protocol by which the issuer authenticates the cardholder before an authorisation. Most 3DS checks are frictionless and invisible to the buyer. When the issuer, or our own risk rules, want more assurance, the buyer gets a **step-up**: a challenge such as an approval in their banking app.

## Services

| Service | Owner | What it does |
|---|---|---|
| `card-auth` | Payments Core | Card authorisation; p99 budget 800 ms |
| `payout-gateway` | Payouts | Sends payouts to sellers in batches every 15 minutes |
| `ledger` | Ledger | Double-entry ledger on PostgreSQL |
| `fx-quote` | Payments Core | Currency quotes, valid for 30 seconds |
| `settlement-batcher` | Payouts | Builds settlement files for our settlement bank |
| `merchant-api` | Merchant Experience | The public API |
| `merchant-hub` | Merchant Experience | The dashboard's web front end |
| `risk-scorer` | Risk ML | Serves the fraud model's scores |
| `notify` | Merchant Experience | Merchant emails and webhooks |

The first five belong to payments engineering; [Payments engineering teams](teams.md) says who leads each team and where to find them. The other four belong to neighbouring teams but sit on the path of every payment, so they appear in the flows below. Each service owns its own database, as [ADR-012](../architecture/adr-012-database-per-service.md) requires, and no service reads another's tables.

## The card data environment

PANs never leave the card data environment. This is the single most important rule on this page, and most of the shape of the platform follows from it.

The card data environment is a separately segmented part of our Kubernetes estate, with its own network policies, its own node pool and its own, much shorter, list of people with production access. It contains:

- the tokenisation component of `card-auth`, which exchanges a PAN for a token (`tok_` followed by 24 characters) and back;
- the connections to the hardware security modules that hold our card keys;
- the outbound link to the acquiring bank.

The buyer's card details travel from the hosted payment form straight to the card data environment's ingress at `pay.quillmoor.example`. Neither `merchant-api` nor `merchant-hub` ever sees them. Everything outside the environment works with the token, the card's last four digits, its expiry month and the card scheme, and nothing else.

Rules that follow:

1. No service outside the card data environment receives, stores or logs a PAN, even briefly, even in a test. Tokens and last four digits only.
2. An operation that needs the PAN, such as an authorisation or a refund to the original card, is requested by token; `card-auth` detokenises inside the environment and the PAN goes no further than the acquiring bank.
3. The log collector inside the environment drops any line that matches a PAN pattern before shipping it to Lantern. If you find your log lines missing, that is usually why.
4. Adding a component inside the card data environment widens our PCI DSS scope. It needs an ADR and a review by Security before any code is written.
5. Test card numbers follow the same rules as real ones on this wiki: see [Test merchants and test cards](test-merchants.md).

## A card payment, end to end

```text
buyer's browser
   |  card details, posted straight to the card data environment
   v
card-auth tokeniser  -->  token returned to the merchant's checkout
                                   |
                                   v
merchant-api  -->  card-auth  -->  risk-scorer (score)
                      |  \-->  3DS, when a step-up is needed
                      |  \-->  fx-quote, when the buyer pays in another currency
                      v
               acquiring bank  -->  card schemes  -->  issuer
                      |
                      v  approved or declined
                   ledger (authorisation journal)
                      |
                      v
               event log  -->  notify  -->  merchant webhook
```

The `card-auth` p99 budget is 800 ms, measured from the moment `merchant-api` calls it to the moment it answers. The issuer's response is the largest and least controllable part of that budget, so everything we do control (the risk score, the quote, the call to the hardware security modules, our own processing) has to be fast and predictable. `card-auth` is written in Go, following [ADR-003](../architecture/adr-003-go-latency-critical.md), largely for that reason. When the budget is breached, follow [Runbook: card authorisation latency](card-auth-latency.md).

An authorisation only reserves funds on the buyer's card. The merchant then **captures** the payment, usually when the order ships, and the captured amount is settled to us by the acquiring bank in a later settlement cycle. The [Payments glossary](glossary.md) explains authorisation, capture and settlement in plain words for readers outside engineering.

3DS sits on the authorisation path only when a step-up is needed. The share of risk-flagged transactions that we send to step-up is controlled by a Switchboard flag, so that we can lower it when 3DS itself becomes slow; the latency runbook explains when that is acceptable.

## A payout, end to end

Quillmoor Payouts pays marketplace sellers in GBP and EUR.

```text
ledger: seller balance becomes payable
   |
   v
payout-gateway: payout queued (held first if the seller is new)
   |
   v  every 15 minutes, the scheduler cuts batches per marketplace and currency
payout-gateway: batch
   |
   v
settlement-batcher: renders the batch as a file in our settlement bank's format
   |
   v
our settlement bank  --> acknowledgement back to payout-gateway
   |
   v
ledger: payout journal marked settled  --> event log --> notify (payout.paid)
```

`payout-gateway` batches payouts every 15 minutes; it owns the life of each batch, from cutting it to recording the bank's acknowledgement. `settlement-batcher` owns the file formats, including the ISO 20022 credit transfer files used for SEPA, and the per-currency cut-off calendars. Whether a batch settles today or on the next business day depends on the time the bank accepts it: see [Settlement windows and cut-off times](settlement-cutoffs.md). New sellers' payouts are held before they enter a batch; see [Payout holds and releases](payout-holds.md).

When a batch is not acknowledged, `payout-gateway` raises an error code and the Payouts team's runbook takes over: [Runbook: rolling back payout-gateway](payout-gateway-rollback.md) covers the error codes, the backlog alert and the safe order of operations.

## The ledger

The ledger is a double-entry ledger on PostgreSQL. It is the source of truth for every balance at Quillmoor: merchant balances, seller balances, amounts receivable from the card schemes, our bank accounts, fees and the suspense account. Other services ask the ledger for a balance; they never compute one themselves.

Its model is small:

| Concept | Meaning |
|---|---|
| Account | A named bucket of value in one currency, such as a seller's GBP balance |
| Posting | One debit or one credit to one account |
| Journal | A set of postings recorded together, whose debits equal its credits |
| Entry date | The business date a journal belongs to, in UTC |

Every money movement, without exception, is a journal. Amounts are integer minor units ([ADR-017](../architecture/adr-017-money-minor-units.md)): pence and cents, never floating point. Every write carries an idempotency key ([ADR-008](../architecture/adr-008-idempotency-keys.md)), so a retried request posts nothing twice. The ledger runs on PostgreSQL, our default database ([ADR-004](../architecture/adr-004-postgresql.md)), with a synchronous standby and a read replica that reconciliation and reporting queries use.

Every night the ledger is reconciled against our settlement bank's statement. When the two disagree, the result is a break, and [Runbook: ledger reconciliation breaks](ledger-reconciliation.md) explains each kind.

Schema changes to the ledger go through `shipwright migrate` like any other service's, but they constrain the rest of payments: a release of `payout-gateway` or `card-auth` built before a ledger schema migration may not be able to write to the ledger after it. Anyone rolling back a payments service must check for one first.

## Currency quotes

`fx-quote` gives other services a rate to convert between currencies, and a quote is valid for 30 seconds. A caller asks for a quote, receives an identifier and an expiry, and passes the identifier when it books the conversion; the ledger rejects a conversion whose quote has expired. `card-auth` asks for a quote when a buyer pays in a currency the merchant does not settle in, and `payout-gateway` asks for one when a seller's balance is in one currency and their bank account in the other. The service page, [fx-quote service](fx-quote-service.md), covers its error codes and its rate feed.

## Events and data

Payments services publish domain events (`payment.authorised`, `payment.captured`, `payout.batched`, `payout.paid`, `journal.posted` and others) to the replicated event log decided in [ADR-019](../architecture/adr-019-replicated-event-log.md). `notify` turns some of them into merchant webhooks; the data platform turns others into warehouse tables such as the one behind the [payouts_hourly pipeline](../data/pipeline-payouts-hourly.md). Events carry tokens, never PANs, and amounts in minor units with an ISO 4217 currency code.

Consumers must tolerate events arriving more than once and out of order. The idempotency rule applies to consumers as much as to APIs: key on the event identifier, not on the payload.

## Regions and resilience

All payments services run in the primary region with a warm standby in the secondary region, as [ADR-021](../architecture/adr-021-active-passive-regions.md) sets out. The card data environment exists in both regions, with its own hardware security modules in each. Failover is a declared incident, never an automatic one.

Inside a region, every payments service exposes its risky behaviour through Switchboard, so that on-call engineers can act without a deploy. The two that matter most:

| Switchboard key | Effect |
|---|---|
| `ks.payout-gateway.batch-scheduler` | Stops `payout-gateway` from cutting new batches; payouts keep queueing |
| `sb.card-auth.stepup-sampling` | Sets the share of risk-flagged transactions sent to a 3DS step-up |

Metrics, traces and dashboards live in Lantern at `lantern.quillmoor.example`; traces are emitted with OpenTelemetry ([ADR-011](../architecture/adr-011-opentelemetry.md)).

## Design rules for payments services

These apply to any new service or major change in payments. A design review that departs from one should say so and say why.

1. Money is integer minor units plus a currency code, everywhere: storage, APIs, events, logs.
2. Every write API takes an idempotency key, and every consumer deduplicates.
3. No PAN outside the card data environment, as above.
4. Every movement of money is a ledger journal, posted by the service that caused it, with a reference that lets reconciliation find it.
5. Store times in UTC. Local time appears only where a counterparty works in local time, such as a bank's cut-off, and then with an explicit time zone.
6. Anything that sends money out of Quillmoor can be paused with a kill switch, without a deploy.
7. A latency-critical service publishes its budget and a Lantern panel that shows it.
8. A new dependency on the authorisation path needs Payments Core's agreement, because it spends part of the 800 ms.

## Where to go next

- [Runbook: rolling back payout-gateway](payout-gateway-rollback.md)
- [Runbook: ledger reconciliation breaks](ledger-reconciliation.md)
- [Runbook: card authorisation latency](card-auth-latency.md)
- [Settlement windows and cut-off times](settlement-cutoffs.md)
- [Payments glossary](glossary.md)
- [On-call rota and paging policy](../incidents/on-call.md), for how the payments rotas are paged

## Change history

| Date | Change | By |
|---|---|---|
| 2025-03-10 | First version, replacing the 2022 architecture slides | Nadia Ferreira |
| 2025-09-01 | Payout flow redrawn after the payout-gateway resilience work (ENG-1) | Yusuf Achterberg |
| 2026-03-23 | EUR payouts through SEPA added after ENG-4 | Yusuf Achterberg |
| 2026-05-18 | Currency quotes section rewritten after the fx-quote rewrite (ENG-5) | Nadia Ferreira |
| 2026-10-06 | Annual review; events section updated for the replicated event log (ENG-29) | Nadia Ferreira |
