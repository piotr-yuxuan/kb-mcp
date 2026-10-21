---
title: "Product brief: self-serve refunds API"
---

| | |
|---|---|
| Status | Shipped: generally available on 28 July 2026 |
| Epic | ENG-6 Self-serve refunds API, ENG Sprint 26 to ENG Sprint 34 (30 March to 2 August 2026) |
| Product manager | Linnea Ashdown |
| Engineering | Payments Core, led by Nadia Ferreira; Ledger (Kwabena Stroud) for ledger entries; Merchant Experience for the Hub screens |
| Support partner | Femi Haldane |
| Last reviewed | 2026-08-11 |

## Problem

Until July 2026, a merchant who wanted to refund a buyer had to raise a ticket in Harbour. A support agent checked the payment, issued the refund from an internal tool and replied. In Q1 2026 that meant about 410 refund tickets a week, a median of 22 hours from ticket to refund, and a refund backlog every Monday after the weekend.

Marketplaces worked around us. Several told us they refunded buyers from their own funds straight away and then waited for our refund to reimburse them. One said refunds were the main reason their operations team kept a support login open all day. In the [May 2026 interviews](merchant-interviews-2026-05.md), refunds were the first complaint of nine merchants out of fourteen.

## Goals

1. Merchants issue full and partial refunds themselves, from the Merchant API and from Merchant Hub.
2. A refund is written to the ledger the moment it is accepted, so the merchant's balance is right immediately.
3. A retried request never refunds twice.
4. Support handles exceptions only: refunds outside the rules, disputes, and merchants who ask for help.

## Non-goals

- **Disputes and chargebacks.** They follow the card schemes' process and were handled by ENG-28; see [Chargebacks and disputes](../support/chargebacks.md).
- **Refunds outside the refund window**, and the approval of exceptional refunds by support. The rules stay where they are, on [Handling merchant refund requests](../support/refunds.md).
- **Bulk refunds from an uploaded file.** Asked for often; on the roadmap as a "next" item.
- **Refunds to a different card or bank account** than the one that paid.

## What we built

- `POST` and `GET` endpoints for refunds on the Merchant API, with an idempotency key on every write, as [ADR-008](../architecture/adr-008-idempotency-keys.md) requires.
- A "Refund" button on the payment page in Merchant Hub, with an amount field that defaults to the remaining refundable amount.
- Refund states: requested, pending approval, submitted, succeeded, failed.
- A second-approver step for large refunds (one of the epic's stories). The threshold matches the one support already applied, so merchants see the same rule whichever way they refund; it is documented on the support page linked above, not here.
- A refund permission in team roles, so a merchant can choose who may request refunds.
- Webhooks for refund events, sent by `notify`.

### Decisions worth recording

**Ledger first, then the scheme.** We write the refund to the ledger as a pending debit when it is accepted, not when the card scheme confirms it. That keeps the merchant's available balance honest and prevents two refunds of the same remaining amount racing each other. Kwabena Stroud's team reviewed the double-entry model; failed refunds post a reversing entry.

**No new limits in the API.** We considered a separate daily refund limit for API refunds and rejected it: the existing rules plus the second approver were enough, and two sets of limits would confuse support.

**Same rules in Hub and in the API.** The Hub screens call the public API. Nothing a merchant can do in Hub is impossible through the API.

## Metrics

| Metric | Baseline (Q1 2026) | Target | Where it is measured |
|---|---|---|---|
| Share of refunds issued without a ticket | 0% | 60% by end of Q3, 70% by end of Q4 | Lantern, refunds dashboard |
| Refund-related tickets per week | 410 | 250 by end of Q3 | Harbour reports |
| Median time from request to submission | 22 hours | Under 1 minute for refunds without approval | Lantern |
| Refunds paid twice | 0 | 0 | Ledger reconciliation |

## Rollout

| When | Step |
|---|---|
| ENG Sprint 26 to 30 | API design, ledger model, idempotency, approval step |
| June 2026 | Pilot with twenty merchants chosen from the heaviest refund ticket raisers |
| 28 July 2026 | General availability in the API and in Hub, announced in the [release notes](merchant-hub-release-notes-2026.md) |
| August 2026 | Support macros updated to point merchants to self-serve |

The launch followed the [launch checklist](launch-checklist.md). The feature sat behind a Switchboard flag for the pilot, removed after general availability.

## Results so far

In the two weeks after general availability, 41% of refunds were issued without a ticket and refund tickets fell to about 300 a week. No refund has been paid twice. The most common reason merchants still raise a ticket is a refund outside the window, which is expected.

## Open questions

- Should support be able to issue a refund on the merchant's behalf through the same API, so all refunds share one path? Femi Haldane and Linnea Ashdown to decide in Q4.
- Do marketplaces want sellers, rather than the marketplace, to trigger refunds? Two pilot merchants asked; not in scope for 2026.
