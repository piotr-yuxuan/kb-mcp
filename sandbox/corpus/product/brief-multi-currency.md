---
title: "Product brief: multi-currency settlement"
---

> [!NOTE]
> This brief is kept as a record. The feature shipped on 9 March 2026; questions about how settlement works today belong on the payments pages linked below.

- **Owner:** Oskar Ngata, product manager, payouts
- **Epic:** ENG-4 Multi-currency settlement, ENG Sprint 15 to ENG Sprint 24 (27 October 2025 to 15 March 2026)
- **Engineering:** Payouts, led by Yusuf Achterberg, which owns `settlement-batcher`; Ledger, led by Kwabena Stroud; Payments Core for `fx-quote`
- **Commercial and support partners:** the account managers for French merchants, and Inès Moreau's support team in Paris
- **Last reviewed:** 2026-09-07

## Summary

Merchants with a euro bank account settle euro card payments in euros, through SEPA, instead of having them converted to pounds and, often, converted back to euros to pay their sellers.

## Background

Until March 2026 every merchant settled in pounds. A French marketplace selling in euros had each day's euro takings converted to sterling at our rate, settled to a sterling account, and then, to pay its sellers in euros through Quillmoor Payouts, converted back. The merchant paid for two conversions and its finance team reconciled three amounts for every payment.

In our 2025 account reviews, settling euros in euros was the most frequent request from European merchants, and we lost two marketplaces in the second half of 2025 to a competitor that offered it. Inès Moreau's team reported that about one ticket in five from French merchants concerned conversion: rates, rounding or the difference between what the buyer paid and what arrived.

## Goals

1. Settle euro card payments in euros to a merchant's euro bank account, through SEPA.
2. Pay sellers in euros from euro balances, without conversion.
3. Show separate settlement reports per currency in Merchant Hub.
4. Keep a separate ledger balance per merchant and currency, so a euro balance never silently becomes a sterling one.

## Non-goals

- Settlement in other currencies. Dollars and Swiss francs came up, each with a handful of merchants; we will look again when one currency has real demand.
- Changes to sterling settlement. Sterling merchants see no difference.
- Presenting prices to buyers in their own currency at checkout. That is a different product.
- Choosing the settlement currency per payment. A merchant settles each currency to the account set for it.

## How it works

The services involved are described on [Payments platform architecture](../payments/platform-architecture.md). In short:

- `card-auth` and capture are unchanged; payments already carried their currency.
- The `ledger` holds a balance per merchant per currency. ENG-4 added euro settlement accounts and the postings between them.
- `settlement-batcher` builds a separate euro settlement file for our settlement bank, sent through SEPA.
- `payout-gateway` pays sellers in euros from euro balances.
- `fx-quote` is used only where a merchant still settles a currency to an account in another one.

Each currency has its own settlement window and cut-off. They are documented, and kept current, on [Settlement windows and cut-off times](../payments/settlement-cutoffs.md); please link there rather than copying times into other pages.

## Rollout

| Date | Step |
|---|---|
| November and December 2025 | Ledger accounts per currency; euro settlement file format agreed with our settlement bank |
| January 2026 | Pilot with eight French marketplaces |
| February 2026 | Pilot extended to twenty merchants in France, Belgium and the Netherlands |
| 9 March 2026 | General availability, announced in the [release notes](merchant-hub-release-notes-2026.md) |

## Outcomes

| Measure | Before | After (August 2026) |
|---|---|---|
| Merchants settling in euros | 0 | 46 |
| Share of euro volume from European merchants settled in euros | 0% | 83% |
| Conversion-related tickets from French merchants per month | about 120 | about 35 |
| European marketplaces signed since launch | | 9 |

In the [May 2026 interviews](merchant-interviews-2026-05.md), merchants who had moved to euro settlement were positive about the feature and critical of the reports, which did not separate settlement date from payout date. The reports were fixed in May.

## Since launch

The Payments weekly sync has reviewed euro settlement several times since March. Changes to the euro window are decided there and recorded in its notes, for example the [sync of 1 September 2026](../payments/weekly-sync-2026-09-01.md), and reflected on the settlement windows page.

## Lessons

- Pilots by country caught a bank holiday calendar difference that testing had not.
- Support was ready because Inès Moreau's team helped write the merchant guide, in French, before the pilot.
- We underestimated reporting. Merchants judge a settlement feature by the report, not by the money arriving.
