---
title: "Payout holds and releases"
---

Owned by Payouts (`#team-payouts`), with Risk deciding on releases. Last reviewed 2026-07-14 by Yusuf Achterberg and Oskar Ngata.

A **hold** stops a seller's payouts from entering a batch. The money stays in the seller's balance in the ledger; nothing is cancelled or returned. When the hold ends, the waiting payouts join the next 15-minute batch as if they had just been created.

## The new-seller hold

New sellers' payouts are held 7 days. When a seller's first payout is created, `payout-gateway` places a new-seller hold on that seller. Every payout created for the seller during the hold waits under it, and the hold ends 7 days after the first payout was created. At that point all the waiting payouts are released together and the seller is no longer new.

Seven days is a balance struck by Risk: long enough for most fraudulent sellers to show themselves through chargebacks and complaints, short enough that honest sellers do not leave the marketplace. It applies to every marketplace, and marketplaces cannot opt out.

Example: a seller's first payout is created on a Monday at 10:00. Further payouts on Wednesday and Friday wait with it. All three are released the following Monday at 10:00 and go out in the 10:00 or 10:15 batch. From then on the seller's payouts are batched normally.

## Other holds

| Hold | Placed by | Ends |
|---|---|---|
| New seller | `payout-gateway`, automatically | After 7 days, or when Risk releases it |
| Risk review | Risk Operations, by hand, often after a `risk-scorer` alert on the marketplace | When Risk releases it |
| KYC incomplete | `payout-gateway`, when the marketplace reports missing KYC details | When the details are complete; see [Answering KYC queries](../support/kyc-queries.md) |

A seller can be under more than one hold. Payouts move only when every hold has ended.

## Who releases holds

Risk releases holds. Only Risk Operations can end a hold early or extend one, and every release records who did it and why. Payouts engineers do not release holds, including in an incident and including when a large merchant is pressing; send the request to Risk instead.

Risk Operations release a hold with:

```bash
shipwright exec payout-gateway -- pgw-admin holds release \
  --seller-id sel_3Hn20cWa --hold new_seller \
  --reason "Marketplace verified seller in person, Harbour ticket 48213"
```

The command is restricted to the risk operations role; anyone else gets a permission error.

Support asks for a release through a Harbour ticket assigned to Risk, with the seller identifier and the merchant's reason. Risk aims to answer within one business day.

## Seeing holds

```bash
shipwright exec payout-gateway -- pgw-admin holds list --seller-id sel_3Hn20cWa
```

```text
hold         placed               ends                 by
new_seller   2026-07-06T10:00Z    2026-07-13T10:00Z    payout-gateway
payouts waiting: 3 (1,240.50 GBP)
```

Held payouts are counted in the metric `pgw_payouts_held`, separately from the payout queue, so they never trigger the backlog alert.

## Questions from merchants and colleagues

**Can a marketplace vouch for a seller to skip the hold?** It can ask, and Risk decides. A marketplace that has met the seller, or that already holds funds of its own against them, has a good case; Risk usually releases within the business day. The request goes through Support, never directly to an engineer.

**Does the hold restart if a seller is inactive for months?** No. A seller is new only once. A seller who returns after a long gap may attract a risk review hold instead, if `risk-scorer` flags the marketplace's activity, but that is a different hold with a different owner.

**Does a hold change the amount paid?** No. A hold delays a payout; it never changes its amount. A held payout is paid in full when it is released.

**What if the seller changes their bank account during the hold?** The payouts wait, and are paid to the account on file at the moment of release. Risk sees bank account changes during a new-seller hold on their review list, because they are a common sign of account takeover.

**Can a hold be placed on a single payout?** Not today. Holds apply to a seller, and every payout for that seller waits under them. Product have a request open for per-payout holds; it is not scheduled.

**Is the 7 days counted in business days?** No, calendar days, to the minute. A hold placed on a Friday at 16:20 ends the following Friday at 16:20, and the payouts then wait for Monday's settlement in the usual way.

## After the release

Released payouts are batched like any other, and the currency's cut-off decides whether they settle that business day or the next: see [Settlement windows and cut-off times](settlement-cutoffs.md). Support answers sellers' questions about held payouts from [Payout delays: what to tell merchants](../support/payout-delay-faq.md).
