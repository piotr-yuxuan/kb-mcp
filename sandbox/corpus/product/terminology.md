---
title: "Product terminology"
---

Owner: Ama Rowntree. Last reviewed: 2026-03-24.

The words product uses in briefs, in Merchant Hub and in anything merchants read. Payments terms such as authorisation, capture, settlement, payout, interchange and chargeback are defined once, on the [Payments glossary](../payments/glossary.md); this page does not redefine them. For tone, capitalisation and spelling, follow the [Content style guide](../design/content-style.md).

## Product names

| Use | Not | Notes |
|---|---|---|
| Quillmoor Pay | QM Pay, Pay | Card acceptance for marketplaces |
| Quillmoor Payouts | Payouts alone, in merchant copy | Paying marketplace sellers, in pounds and euros. Inside the company, "Payouts" is also a team |
| Merchant Hub | the portal, the merchant dashboard, the console | "Hub" alone is fine on second mention inside Merchant Hub itself |
| Merchant API | the public API, the Quillmoor API | Versioned by date |

## Who is who

**Merchant.** The marketplace business that holds a contract with Quillmoor. Never "customer" on its own, because a merchant has customers of its own.

**Seller.** A person or business that sells on a merchant's marketplace and receives payouts. Sellers do not have a contract with us and do not log in to Merchant Hub.

**Buyer.** The person who pays by card on a marketplace. Prefer "buyer" to "cardholder" in merchant copy; "cardholder" is for scheme and compliance documents.

**User.** A person who signs in to Merchant Hub on a merchant's behalf. Users have one of the team roles: owner, administrator, finance, support, developer or read-only.

## Balances

**Available balance.** Money a merchant or seller can be paid now.

**Pending balance.** Money from payments that have not yet settled to us, or that are held.

**Held.** A payout that will not be sent until it is released. The reasons and who releases a hold are on [Payout holds and releases](../payments/payout-holds.md). Do not say "frozen" or "blocked".

## Release stages

Every launch is at one of three stages. Release notes and the launch checklist use exactly these words.

| Stage | Who has it | Promise |
|---|---|---|
| Pilot | Named merchants, by invitation | May change or be withdrawn; supported directly by the product team |
| Preview | Any merchant who opts in | May change; supported by Merchant Support on a best-effort basis |
| Generally available | Every merchant, by default or by setting | Supported, documented, covered by the service's SLO |

We do not use "beta" or "early access" in merchant copy.

## Words to use with care

- **Instant.** Only for instant payouts, if we launch them. A payment that settles the same day is not instant.
- **Refund** and **dispute.** A refund is something the merchant chooses to give. A dispute is raised by the buyer through their card issuer and may end in a chargeback. Never call a chargeback a refund.
- **Self-serve.** Something a merchant can do in Hub or the API without contacting us. Not "automatic".
- **Free.** Only for things that are free in every case. "Included" is usually more accurate.
- **Guaranteed.** Never, unless Legal has approved the sentence.
