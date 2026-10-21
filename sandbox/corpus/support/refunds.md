---
title: "Handling merchant refund requests"
---

> [!NOTE]
> Owned by Dorian Pask (T2 lead). Last reviewed 2026-08-24, after the self-serve refunds API went live. This page is for merchants who write to us in English. French-speaking merchants are looked after by the Paris team, whose own guide is [Traiter une demande de remboursement (marchands français)](remboursements-marchands.md).

Refund tickets are among the commonest we receive: roughly one in eight. Most are not requests for us to refund anything. They are merchants asking how to do it, asking why a buyer has not seen the money, or asking us to approve a large one. This page covers all three, plus the awkward cases.

## Rules at a glance

| Rule | What it means |
|---|---|
| Refund window | A payment can be refunded within 180 days of the payment. After that, it cannot be refunded through Quillmoor at all. |
| Partial refunds | Allowed. A payment can take several partial refunds, until their total reaches the captured amount. |
| Approval | Refunds over £10,000 need T2 approval before they are sent. |
| Who starts a refund | The merchant, in Merchant Hub or through the Merchant API. Support starts one only in the two cases described below. |
| Currency | The original payment's currency, back to the card that was used. |
| Funding | The merchant's Quillmoor balance. |

## Who refunds

Merchants refund their own buyers. In Merchant Hub, a user with the Payments role opens the payment, chooses **Refund**, enters the amount and a reason, and confirms. Since ENG-6 finished in August 2026, merchants can also refund from their own systems through the self-serve refunds API; the product background is on [Product brief: self-serve refunds API](../product/brief-self-serve-refunds.md). Whichever route they use, the same rules apply.

Support starts a refund on a merchant's behalf only when:

1. Merchant Hub and the Merchant API are both unavailable to the merchant, for example during an incident, and the refund cannot wait; or
2. every administrator on the merchant's account is locked out, and the refund is time-critical for the merchant.

In both cases we need a written request on the ticket from an administrator of the account, naming the payment and the amount. T1 drafts the refund in the back office and a T2 sends it. If the amount is over £10,000, a second T2 approves it: whoever drafts a refund never approves it.

We never refund at a cardholder's request. A cardholder who writes to us is redirected, politely, to the merchant they bought from: we cannot judge a dispute about goods or services we did not sell.

## Working a refund ticket

Before you answer, check five things in the back office. It takes a minute and avoids most second replies.

1. **The payment.** Find it by its Quillmoor reference. If the merchant gave only their own order number, ask for the payment reference or the date, amount and last four digits of the card.
2. **The date.** Is the payment within 180 days? Count from the payment date shown in Merchant Hub.
3. **The state.** A payment that was authorised but never captured is cancelled, not refunded: the buyer's issuer releases the hold and no money moves. A payment with an open dispute cannot be refunded (see "Edge cases").
4. **What is left to refund.** The captured amount minus any earlier refunds.
5. **The amount asked for.** Over £10,000 means T2 approval.

Then use this table.

| Situation | What to do | Macro |
|---|---|---|
| The merchant asks how to refund | Explain the Merchant Hub steps, or point the developer to the API | `refund-how-to` |
| The payment is more than 180 days old | Explain that we cannot refund it, and that the merchant must repay the buyer another way | `refund-out-of-window` |
| A refund over £10,000 shows "Pending approval" | Check it is in `refund-approvals`; tell the merchant when to expect a decision | `refund-approval-pending` |
| The payment was never captured | Explain that cancelling releases the hold; show where to cancel | `refund-how-to`, adapted |
| The payment has an open dispute | Do not refund; explain the dispute process | see [Chargebacks and disputes](chargebacks.md) |
| The refund shows "Succeeded" but the buyer has not seen it | Give the acquirer reference and the usual timing | `refund-in-transit` |
| The refund shows "Failed" | Check the reason; see "Edge cases" | none; write it |
| A cardholder writes to us | Redirect to the merchant | `refund-cardholder-redirect` |

## Partial refunds

A partial refund returns part of a payment, typically for one item of a basket or for a delivery charge. Merchants can make as many partial refunds on a payment as they need, each with its own reference, until their total equals the captured amount. After that, the **Refund** button disappears for that payment.

A worked example: a buyer pays £240 for three items. The merchant refunds £60 when one item is out of stock, then £180 when the buyer returns the rest. The payment is now fully refunded; a third refund is refused.

Points that confuse merchants:

- A partial refund does not reopen the 180-day window. Every refund on the payment, partial or not, must be made within 180 days of the original payment.
- Partial refunds appear as separate lines in the payout report, each on the day it was processed, not on the day of the payment.
- How fees are treated on a refund is a pricing matter; send merchants to the published pricing rather than quoting a figure in the ticket. Internally, see [Pricing overview](../product/pricing.md).

## Refunds over £10,000

Any refund over £10,000 waits for T2 approval before it is sent, whether it is full or partial, and whether it comes from Merchant Hub, from the API or from support. In Merchant Hub and in the API the refund shows the status **Pending approval**; in Harbour it creates a ticket in the `refund-approvals` queue, linked to the merchant's account. This is the second approval that ENG-6 built into the self-serve refunds API: for every refund over the threshold, the second approver is a T2 specialist.

"Over" means more than £10,000: a refund of exactly £10,000.00 goes straight through.

### What T2 checks

- The payment exists, was captured, and is within 180 days.
- The amount does not exceed what is left to refund.
- No dispute is open on the payment.
- The user who asked for the refund is an active user of the merchant's account with the Payments role, and the request came from the merchant's usual channel (their Merchant Hub session or their API credentials, not a new email address).
- The merchant's balance covers the refund, or will within the funding period (see "Edge cases").
- Nothing about the pattern is odd: several large refunds soon after several large payments, refunds on payments from a new seller, or a refund asked for by a user who was added to the account in the last few days. If something is odd, T2 holds the refund and tells Risk Operations through the `fraud-reports` queue before deciding. See [Merchants reporting fraud](merchant-fraud-reports.md).

T2 approves or declines in Harbour. Approval sends the refund at once; the approver's name and time are recorded on the refund and visible to the merchant in Merchant Hub. The target is a decision within 4 business hours of the refund arriving in the queue. Approvals happen only in business hours: a large refund requested on Friday evening is decided on Monday morning, and the `refund-approval-pending` macro says so.

### Splitting to avoid approval

Harbour flags a payment when several partial refunds on it add up to more than £10,000 within 24 hours, even if each is under the threshold. Treat the set as one refund over £10,000: hold the later ones and send them through approval. If a merchant asks how to avoid the approval step, the answer is that they cannot; the step exists to protect them from a compromised account as much as anything.

## Edge cases

**The balance does not cover the refund.** A refund is funded from the merchant's Quillmoor balance. If the balance is too low, the refund waits with the status **Pending funds** until incoming payments cover it. If it is still not covered after 5 business days, the refund fails and the merchant is told by email. Merchants with large returns seasons should keep a buffer; T2 can explain the options.

**The buyer has not seen the refund.** Once a refund shows **Succeeded**, we have sent it to the acquiring bank, and it travels through the card scheme to the issuer. Issuers usually post it to the cardholder's account within 5 to 10 business days. Give the merchant the acquirer reference shown on the refund: the buyer can quote it to their bank, which can trace the credit. We cannot speed up an issuer.

**The card has expired or been replaced.** The issuer usually credits the buyer's account or new card anyway. If the issuer returns the refund, its status changes to **Failed**, the money goes back to the merchant's balance, and the merchant must repay the buyer another way, such as a bank transfer they arrange themselves.

**The payment is under dispute.** Once a dispute opens, refunds on that payment are blocked, because the buyer would otherwise be credited twice: once by the merchant and once through the dispute. The merchant can accept the dispute instead. Everything else about disputes is on [Chargebacks and disputes](chargebacks.md).

**The merchant refunded twice by mistake.** A refund that has been sent cannot be recalled. The merchant must ask the buyer to pay the extra back directly. Only a refund still **Pending approval** or **Pending funds** can be cancelled, from Merchant Hub.

**A refund in another currency.** The refund is made in the payment's original currency. The merchant's balance is debited in their settlement currency at the rate of the day of the refund, so the amount debited can differ from what the original payment credited. That is expected; T2 can show the rates used.

**A refund to a different card or account.** Not possible. A refund always goes back to the card that paid.

**Test mode.** Refunds in the sandbox behave like live ones, approvals included, but no money moves. Questions about test accounts belong to [Test merchants and test cards](../payments/test-merchants.md).

## Reply templates

Adapt every template to the ticket before sending; the full list of macros is on [Support macros](macros.md).

`refund-how-to`:

> To refund a payment, open it in Merchant Hub under **Payments**, choose **Refund**, enter the amount (the full amount or part of it) and a short reason, then confirm. Your buyer's bank usually shows the refund within 5 to 10 business days. If your developers prefer to refund from your own systems, our API documentation at `docs.quillmoor.example` covers the refunds endpoint.

`refund-out-of-window`:

> I am sorry, but this payment was made on {{payment.date}}, which is more than 180 days ago, and card payments can only be refunded through Quillmoor within 180 days of the payment. If you wish to repay your buyer, you will need to do so directly, for example by bank transfer.

`refund-approval-pending`:

> Your refund of {{refund.amount}} is waiting for a second approval, which we apply to every refund over £10,000 to protect your account. Our payments specialists review these during business hours and usually decide within 4 business hours; you will see the status change in Merchant Hub as soon as it is approved.

`refund-cardholder-redirect`:

> Thank you for getting in touch. Quillmoor processes card payments on behalf of the business you bought from, but we cannot decide on refunds for their goods or services. Please contact the seller directly; your card statement shows their name. If you cannot reach them, your card issuer can advise you.

## FAQ

**Can we extend the 180-day window for a good reason?** No, not for any merchant, strategic merchants included. The limit comes from how refunds travel through the card schemes, not from our policy alone.

**Does the window start at authorisation or at capture?** At the payment date shown in Merchant Hub. For almost every payment, the two fall on the same day.

**Who approves refunds over £10,000 when no T2 is working?** Nobody: they wait for business hours. The support duty agent does not approve refunds.

**Can a merchant cancel a refund?** Only while it is **Pending approval** or **Pending funds**.

**A merchant's daily statement is missing a refund that settled just after midnight.** It appears on the next day's statement. If it is on neither, escalate to T2.
