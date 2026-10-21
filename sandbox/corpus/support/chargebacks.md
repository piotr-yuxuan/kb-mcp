---
title: "Chargebacks and disputes"
---

*Owner: Dorian Pask, T2 lead, with Merchant Experience for the evidence automation. Last reviewed 2026-09-03.*

A dispute starts when a cardholder asks their issuer to reverse a card payment. The issuer raises a chargeback through the card scheme, our acquiring bank passes it to us, and we take the disputed amount from the merchant's balance while the merchant decides whether to contest it. Support's job is to make sure the merchant understands what happened, sends the right evidence in time, and hears the outcome. Payments terms such as "chargeback" and "settlement" are defined in the [Payments glossary](../payments/glossary.md).

Disputes are handled by T2. T1 answers first questions with the macros below and moves anything that needs judgement to the `disputes` queue.

## The two rules that matter most

1. **We submit evidence at least 7 calendar days before the scheme's deadline.** Never later, whatever the merchant asks.
2. **A dispute fee of £15 is charged for each chargeback.** It is charged when the chargeback arrives, and it is not returned whatever the outcome.

Both are explained further down.

## The life of a dispute

1. **Inquiry (sometimes).** Some issuers first ask for information about a payment before raising a chargeback. No money moves and no fee is charged. The merchant sees an inquiry in Merchant Hub with a "Respond by" date. A quick, complete answer often prevents the chargeback altogether, so treat inquiries as seriously as chargebacks.
2. **Chargeback.** The acquiring bank notifies us. The disputed amount is debited from the merchant's balance and the £15 dispute fee is charged. `notify` sends the merchant an email and a webhook, Merchant Hub shows the dispute with its reason and "Respond by" date, and Harbour opens a ticket in the `disputes` queue.
3. **Evidence.** The merchant uploads evidence in Merchant Hub, on the dispute's page, and can add a short written statement. T2 reviews it and asks for more if needed.
4. **Submission.** On our submission date, the evidence goes to the acquiring bank and on to the issuer. Since ENG-28, the submission is automatic (see below).
5. **Decision.** The issuer decides. Most decisions arrive within a few weeks, some take longer; Merchant Hub shows the status throughout.
6. **Pre-arbitration (rare).** If the issuer rejects the evidence and the merchant still disagrees, or the cardholder disputes again, the case can go to a second cycle. T2 handles these individually with the merchant, and only after explaining the costs that the card schemes charge for arbitration.

## Dates, and why 7 days

Each chargeback carries a deadline set by the card scheme for its reason code. Harbour shows it on the ticket as **Scheme deadline**. From it, we derive two dates of our own:

| Date | When | Who sees it |
|---|---|---|
| Scheme deadline | Set by the card scheme | Harbour only |
| Submission date | At least 7 calendar days before the scheme deadline | Harbour; the date ENG-28's automation submits |
| Respond by | 3 calendar days before the submission date | The merchant, in Merchant Hub and in our emails |

For example, if the scheme's deadline falls on the 30th of a month, we submit by the 23rd at the latest, and we ask the merchant for their evidence by the 20th. Those three days let T2 review what the merchant has sent and ask for anything missing.

We hold to 7 calendar days because evidence that reaches the issuer late is lost by default, with no review at all. The acquiring bank needs time to forward the file, scheme systems slow down as deadlines approach, and a rejected upload close to the deadline cannot be fixed. Before the rule, several disputes a quarter were lost only because the evidence arrived a day or two late.

### What ENG-28 changed

Until the end of August 2026, a T2 specialist submitted every dispute's evidence by hand. ENG-28 then automated it: on the submission date, the evidence attached to the dispute is packaged and submitted without anyone pressing a button. T2 still reviews the evidence beforehand, and can submit earlier by hand when the file is complete.

The automation submits whatever is attached on the submission date. If the merchant has uploaded nothing, it submits nothing and the dispute is treated as accepted. T2 gets a Harbour reminder two days before the submission date for every dispute with no evidence, and sends the `dispute-evidence-reminder` macro.

### Late evidence

- Evidence that arrives after "Respond by" but before the submission date: T2 still reviews and includes it if at all possible.
- Evidence that arrives after the submission date: it cannot be added. Tell the merchant plainly, and keep it on the ticket in case the case goes to pre-arbitration.
- A merchant who asks us to wait for one more document beyond the submission date: we cannot. The 7-day rule is not negotiable, for any merchant.

## The dispute fee

| Question | Answer |
|---|---|
| How much? | £15 per chargeback |
| When is it charged? | When the chargeback arrives, as a separate line in the balance and the payout report |
| Is it charged for inquiries? | No; only when a chargeback is raised |
| Is it returned if the merchant wins? | No. It covers our handling of the case, whatever the outcome |
| Can support waive it? | No. If a chargeback was recorded twice by mistake, T2 asks Finance to correct it; that is a correction, not a waiver |

Merchants often ask why they pay a fee for a dispute they won. The honest answer is that the work is the same whether they win or lose: receiving the case, holding the funds, preparing and submitting the evidence.

## Evidence by reason

The card schemes use many reason codes. We group them into five families, shown on the dispute in Merchant Hub, and ask for evidence by family.

| Family | The cardholder says | Evidence that helps |
|---|---|---|
| Fraud | "I did not make this payment" | The 3DS result if the payment was authenticated; delivery to the cardholder's billing address; earlier undisputed orders by the same buyer; correspondence with the buyer; device and network details the marketplace holds |
| Not received | "I never got the goods or service" | Proof of delivery with a date and address; tracking; for services, proof of use or access |
| Not as described | "It was not what I ordered" or "it was faulty" | The listing as it appeared at the time of purchase; photographs; the buyer's messages; the merchant's returns policy and any offer made to the buyer |
| Duplicate or wrong amount | "I was charged twice" or "for the wrong amount" | Evidence that each payment was a separate order; the order details and totals |
| Credit not processed | "I returned it and was never refunded" | The refund's reference if one was made; the returns policy; proof the item was never returned |

For fraud disputes, T2 checks the 3DS result first. A payment that was authenticated with 3DS usually moves the fraud liability to the issuer, and the authentication data may be enough to win without anything from the merchant. Tell the merchant before asking them for work they may not need to do.

Good evidence is specific, dated and brief. Ten pages of order history do less than one delivery confirmation with the cardholder's address on it. Ask merchants to explain in two or three sentences, in their statement, why the cardholder's claim is wrong.

## Before submission: the T2 checklist

- The evidence matches the dispute's reason family.
- The documents are readable, in a supported format, and within the upload size shown in Merchant Hub.
- Personal data beyond what the case needs has been removed, such as other customers' names in a screenshot.
- The merchant's statement is factual and polite; issuers read it.
- The submission date in Harbour is still at least 7 calendar days before the scheme deadline.

## Accept or contest

Merchants may accept a dispute instead of contesting it. The disputed amount and the fee stay debited, and the case closes. Accepting makes sense when the merchant agrees with the cardholder, or when the evidence is weak and the amount small. T2 can say whether the evidence looks strong, but the decision is the merchant's.

A merchant who wants to refund the buyer once a dispute is open cannot: refunds on a disputed payment are blocked, because the buyer would be credited twice. Accepting the dispute is the equivalent. How refunds work otherwise is on [Handling merchant refund requests](refunds.md).

## Outcomes

- **Won.** The disputed amount returns to the merchant's balance. The fee does not.
- **Lost.** The disputed amount stays debited.
- **Pre-arbitration.** See "The life of a dispute". T2 decides with the merchant whether to continue.

Harbour updates the ticket with the outcome, and T1 or T2 sends the matching macro.

## When disputes point to fraud

Fraud disputes are also signals. Every chargeback in the fraud family feeds the labels used to train the fraud model, as described on [Labelling fraud from chargebacks](../ml/chargeback-labels.md). If a merchant's disputes rise sharply, or many come from buyers the merchant does not recognise, T2 tells Risk Operations through the `fraud-reports` queue; see [Merchants reporting fraud](merchant-fraud-reports.md). The card schemes also monitor merchants whose dispute rates are high, and a merchant who enters one of those programmes will need help from T2 and Risk together.

## Reply templates

`dispute-opened`:

> A cardholder has disputed payment {{payment.reference}} of {{payment.amount}}, for the reason "{{dispute.reason}}". The disputed amount has been held from your balance, and a dispute fee of £15 applies. If you wish to contest it, please upload your evidence in Merchant Hub by {{dispute.respond_by}}. The dispute page lists the documents that help most for this reason.

`dispute-evidence-reminder`:

> We have not yet received any evidence for the dispute on payment {{payment.reference}}. Your evidence must be uploaded in Merchant Hub by {{dispute.respond_by}} so that we can submit it in time. If you prefer not to contest this dispute, you can accept it from the same page.

`dispute-outcome-won`:

> Good news: the issuer has decided the dispute on payment {{payment.reference}} in your favour, and {{payment.amount}} has been returned to your balance. The dispute fee is not refunded, as it covers the handling of the case.

`dispute-outcome-lost`:

> The issuer has decided the dispute on payment {{payment.reference}} in the cardholder's favour, so the disputed amount will not be returned. If you believe the decision is wrong and have new evidence, reply to this message and our payments specialists will tell you whether a second review is possible.

## FAQ

**Can the merchant contact the cardholder?** Yes, and it often helps. If the cardholder agrees to withdraw the dispute, they must tell their issuer; the merchant should still upload evidence, including the cardholder's message, in case the withdrawal does not arrive in time.

**Can we submit on the deadline day if the merchant is late?** No. The submission date is at least 7 calendar days before the scheme deadline.

**Does a dispute delay payouts?** The held amount and the fee are taken from the balance, so the next payout is lower by that amount. The payout itself is not delayed.

**Can the merchant see the scheme deadline?** No; they see "Respond by", which is the date that matters to them.
