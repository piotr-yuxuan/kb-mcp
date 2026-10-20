---
title: "Flag clean-up report Q3 2026"
---

# Flag clean-up report Q3 2026

Prepared by release engineering (Platform) for the engineering leads. Period: 1 July to 30 September 2026 (calendar quarter). Published and last reviewed: 2026-10-05.

This is the quarterly count of Switchboard release flags and of how far each team is behind on removing them. The rules, including when a flag becomes overdue, are on [Feature flags and kill switches](feature-flags.md).

## Summary

- **Release flags live:** 168 on 1 July, 146 on 30 September.
- **Created** during the quarter: 41. **Removed:** 63.
- **Overdue** flags: 29 on 1 July, 12 on 30 September. This is the lowest figure since the report began in 2025.
- **Kill switches:** 37, unchanged. They are not subject to removal. 35 of them were exercised in `staging-eu` this quarter; the two that were not belong to `risk-scorer` and are scheduled for October.
- **Operational flags:** 19, all with a written reason. Three were reviewed this quarter and kept.

## Overdue flags by team

| Team | 1 July | 30 September | Change |
|---|---|---|---|
| Payments Core | 7 | 4 | -3 |
| Payouts | 5 | 1 | -4 |
| Ledger | 3 | 0 | -3 |
| Merchant Experience | 11 | 6 | -5 |
| Risk ML | 3 | 1 | -2 |
| **Total** | **29** | **12** | **-17** |

Ledger cleared everything, including the two flags left over from the 2026 ledger schema migration, `sb.ledger.dual-write-journal-lines` and `sb.ledger.partitioned-journal-reads` ([Raising a change ticket](change-tickets.md) has the story of `CHG-2291`). Payouts removed four in one release in August.

## Flags worth a mention

| Flag | Team | At full rollout since | Overdue since | Status |
|---|---|---|---|---|
| `sb.merchant-hub.legacy-csv-export` | Merchant Experience | 2025-11-18 | 2026-02-16 | Two strategic merchants still use the old export; removal agreed with them for the first sprint after their contract renewal |
| `sb.fx-quote.v2-engine` | Payments Core | 2026-05-06 | 2026-08-04 | Left over from the fx-quote rewrite (ENG-5); removal ticket in ENG Sprint 40 |
| `sb.payout-gateway.async-acks` | Payouts | 2026-06-02 | 2026-08-31 | Removal merged, waiting for the next release |
| `sb.risk-scorer.batch-scoring-endpoint` | Risk ML | 2026-05-20 | 2026-08-18 | Blocked on a consumer in Data Platform |

`sb.merchant-hub.legacy-csv-export` is now the oldest overdue flag in the company, by a distance.

## Not counted

Flags that have not reached full rollout are not on the clock, however old they are:

- `sb.merchant-hub.dark-mode` is at 25% of merchants while epic ENG-26 continues.
- `sb.merchant-api.date-versioning` is on for an allow-list of merchants while epic ENG-30 continues.

Both will start counting on the day they reach 100% with no allow-list.

## Actions for Q4

1. Merchant Experience removes `sb.merchant-hub.legacy-csv-export` and at least three other overdue flags. Owner: the Merchant Experience lead.
2. Payments Core removes `sb.fx-quote.v2-engine` in ENG Sprint 40 and brings its overdue count to zero. Owner: Nadia Ferreira.
3. Release engineering makes the Monday overdue list in team channels include the name of the engineer who created each flag. Owner: Bram Oyelaran.
4. Risk ML exercises its two kill switches in `staging-eu` in October.

The next report will cover October to December 2026.
