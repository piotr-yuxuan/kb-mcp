---
title: "Product brief: instant payouts"
---

**Status:** discovery. No epic in ENG yet; nothing is committed beyond the decision.
**Owner:** Oskar Ngata, product manager, payouts.
**Working group:** Yusuf Achterberg (Payouts), Kwabena Stroud (Ledger), Mireille Okonkwo (Risk ML), Arjun Pelletier (finance), Saoirse Lindqvist (legal).
**Decision:** a go or no-go recommendation to the leadership team by the end of November 2026, as a [Q4 2026 key result](okrs-2026-q4.md).
**Last reviewed:** 2026-10-08.

## The bet

Sellers on our merchants' marketplaces get paid on the marketplace's payout schedule, usually daily or weekly. If a seller could ask for their available balance and have it in their bank account within minutes, at any hour, marketplaces would keep sellers who now leave for platforms that pay faster, and we would earn a fee on each instant payout.

Unlike most of this year's roadmap, instant payouts did not start on the ideas board. It came out of the 2026 strategy review as a deliberate bet, which is why its discovery is tracked on this page and in the Q3 and Q4 OKRs.

## What we know

- In the [May 2026 merchant interviews](merchant-interviews-2026-05.md), nine of fourteen merchants said their sellers ask for faster access to their money, and two named a competitor that already offers instant payouts to sellers.
- In seventeen further interviews in Q3, mostly with sellers introduced by four marketplaces, the strongest demand came from sellers with thin margins and their own suppliers to pay: second-hand goods dealers, small craft businesses and event ticket resellers.
- Sellers do not want every payout instant. They want the option when they need it, and most said they would pay a fee for it.
- Payout delay is also one of the most frequent reasons merchants contact support; see [Payout delays: what to tell merchants](../support/payout-delay-faq.md).

## What we do not know yet

- How much working capital we would need. An instant payout leaves before the card money behind it has settled to us, so we would be paying sellers out of our own funds in between.
- How fraud would change. Fast, irrevocable payouts on request are attractive to anyone who has taken over a seller's account.
- Whether marketplaces want to offer it under their own brand, or would rather we never appear to their sellers at all.

## The proposal under discovery

- A seller, through their marketplace, requests an instant payout of some or all of their available balance.
- The payout arrives within minutes, at any time, including weekends and bank holidays.
- Pounds first, through the UK's instant domestic payment rail; euros later, through SEPA instant credit transfers.
- Marketplaces opt in, choose which sellers are eligible, and can add their own fee on top of ours.
- The Merchant API exposes it; Merchant Hub shows instant payouts alongside scheduled ones.

## Non-goals

- Replacing scheduled payouts. They stay the default and stay cheaper.
- Paying out funds that are on hold. Held payouts follow [Payout holds and releases](../payments/payout-holds.md), with no instant route around the hold.
- Payouts to cards. Possible later; a different set of scheme rules.
- Currencies other than pounds and euros.

## Economics, first cut

| Item | Working assumption |
|---|---|
| Fee to the marketplace | 1% of the payout, minimum £0.50 or €0.50 |
| Expected uptake | 5% to 8% of payout value from opted-in marketplaces |
| Per-seller limit | £5,000 or €5,000 a day at launch |
| Funding | A pre-funded balance at our settlement bank, size to be set by finance |

The fee is not on the [pricing overview](pricing.md) because we do not offer the product. Idris Kallenberg's team is modelling the cost of the pre-funded balance against the fee; that model decides more than anything else whether this is a go.

## Risks and how discovery addresses them

| Risk | What we are doing about it |
|---|---|
| Working capital cost exceeds fee income | Finance model, reviewed with Idris Kallenberg before the decision |
| Account takeover leads to fraudulent instant payouts | Mireille Okonkwo's team is sizing a check on each request by `risk-scorer`, with a step-up for changed bank details |
| Ledger cannot post in real time at the volumes needed | Kwabena Stroud to confirm from ENG-6's real-time refund postings, which use the same pattern |
| Payouts must run every hour of every day | Payouts would need a heavier on-call rota; Yusuf Achterberg to cost it against the current [on-call policy](../incidents/on-call.md) |
| Contract terms with marketplaces | Saoirse Lindqvist to review whether the MSA needs an addendum |

## Discovery plan

| When | Activity | Status |
|---|---|---|
| May 2026 | Merchant interviews | Done |
| Q3 2026 | Seventeen seller and merchant interviews | Done; target was twenty |
| Q3 2026 | Technical spike on the domestic instant rail with our settlement bank | Done; feasible |
| October 2026 | Finance model; fraud sizing; pilot design with five marketplaces | In progress |
| By end of November 2026 | Recommendation to the leadership team | Planned |

If the answer is go, an epic would be planned in the Q1 2027 round, starting with a pounds-only pilot. If it is no-go, this page records why, so that the next person to propose it starts from here.
