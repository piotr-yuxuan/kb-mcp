---
title: "Cost centre list"
---

# Cost centre list

Maintained by Leontine Barrow, financial planning lead. Last reviewed 2026-09-01.

Every cost at Quillmoor is charged to a cost centre: salaries, expenses, purchase orders
and cloud resources alike. A cost centre code is `CC-` followed by four digits. Use the
code in Tally, on purchase orders and in the `cost-centre` tag on cloud resources (see
[cloud cost allocation and tagging](cloud-cost-allocation.md)).

## Current cost centres

| Code | Name | Budget holder |
|---|---|---|
| `CC-1000` | Executive office | Hollis Varga |
| `CC-1100` | Finance | Arjun Pelletier |
| `CC-1200` | Legal | Saoirse Lindqvist |
| `CC-1300` | People | Rhiannon Dace |
| `CC-1400` | Workplace, London | Gwen Talbot |
| `CC-1410` | Workplace, Paris | Élodie Vasseur |
| `CC-2000` | Product | Ama Rowntree |
| `CC-3000` | Engineering management | Ottilie Marsh |
| `CC-3100` | Payments Core | Nadia Ferreira |
| `CC-3200` | Payouts | Yusuf Achterberg |
| `CC-3300` | Ledger | Kwabena Stroud |
| `CC-3400` | Platform | Bram Oyelaran |
| `CC-3500` | Site Reliability | Lukas Brennand |
| `CC-3600` | Security | Callum Ibe |
| `CC-3700` | Data Platform | Tomasz Wilde |
| `CC-3800` | Risk ML | Mireille Okonkwo |
| `CC-3900` | Design System | Priya Castellane |
| `CC-4000` | Merchant Experience | Ottilie Marsh |
| `CC-5000` | Merchant Support | Femi Haldane |
| `CC-9000` | Unallocated | The FinOps working group |

## Rules

- **Charge the cost centre that benefits.** If your team buys something for another
  team, use their code, with their budget holder's agreement noted in Tally.
- **`CC-9000` Unallocated is not for manual use.** It collects cloud costs that cannot
  be traced to an owner, and it has no budget. Tally rejects expenses and purchase
  orders coded to it.
- **Engineering management, `CC-3000`,** holds engineering-wide costs such as the
  engineering offsite and shared developer tooling that no single team owns.
- **The Paris office** has its own Workplace cost centre so that office costs in euros
  can be reported separately. People who work in Paris are charged to their team's cost
  centre, not to `CC-1410`.

## Changing the list

New cost centres, renamed ones and changes of budget holder are agreed with financial
planning and approved by the finance director. Changes take effect on the first day of a
month, so that no month is split between two codes. Retired codes stay in the accounting
system for reporting but stop accepting new costs.

Most changes happen at the start of the fiscal year, alongside the
[annual budget cycle](budget-cycle.md). Ask in `#ask-finance` if you think your team
needs its own cost centre.
