---
title: "Merchants reporting fraud"
---

**Owner:** Dorian Pask, T2 lead, with Risk Operations. **Last reviewed:** 2026-06-30.

When a merchant tells us about fraud, the first job is to work out which kind of fraud it is, because each goes to a different place. T1 sorts the report and sends the `fraud-report-received` macro; T2 and Risk Operations take it from there in the `fraud-reports` queue.

## Four kinds of report

| The merchant says | What it probably is | Where it goes | Urgency |
|---|---|---|---|
| "We are seeing lots of small payments from cards we do not recognise" or "orders are being placed with stolen cards" | Card testing or stolen cards used at the merchant's checkout | `fraud-reports`; Risk Operations | P2 while it is going on, P3 afterwards |
| "Someone has changed our bank details" or "there is a user on our account we did not add" | The merchant's own account is compromised | T2 at once, and `security@quillmoor.example` | P2, or P1 if the merchant cannot take payments |
| "We got an email from Quillmoor asking us to log in, and it looks wrong" | Phishing that pretends to be us | `security@quillmoor.example` | P3 |
| "One of our sellers is not shipping goods" or "is selling counterfeits" | A seller defrauding buyers on the marketplace | `fraud-reports`; Risk decides about the seller's payouts | P3 |

Merchants also write to complain that genuine buyers' payments were declined as fraud. That is not a fraud report but a decline review; see "Declined good customers" below.

## Card testing and stolen cards

Fraudsters test stolen card numbers with many small payments, often at night. A merchant who notices it may see dozens of authorisations of very small amounts, mostly declined.

1. Ask for a time range and a few payment references. Do not ask for card numbers, and do not accept them if offered; if a merchant pastes card details into a ticket, redact them with Harbour's **Redact** action at once.
2. Send the report to `fraud-reports` with the references. Risk Operations reviews new reports within one business day, and faster while an attack is going on.
3. Tell the merchant what they can do now: turn on the checkout protections described in the merchant documentation, and make sure 3DS is used where the documentation recommends it.

Do not promise to block cards, buyers or countries, and do not say what the fraud model will do; those decisions belong to Risk. How Risk Operations reviews flagged and declined payments is on [Risk operations: reviewing declined payments](../ml/risk-ops-reviews.md).

## A compromised merchant account

Treat any sign that someone else controls a merchant's account as urgent.

- Escalate to T2 straight away. T2 can freeze payouts on the account while the merchant regains control.
- Email `security@quillmoor.example` with the ticket link.
- If the merchant thinks an API key has been exposed, help them create a new key in Merchant Hub, and leave the old key to Security, who revoke it as described in [Playbook: leaked secret or API key](../security/leaked-secret.md).
- Ask the merchant to review their users and reset their own passwords. Never reset a merchant's password for them, and never send one by email.

## Phishing that pretends to be Quillmoor

Ask the merchant to forward the suspicious email as an attachment to `security@quillmoor.example`, and not to click its links. Reassure them: we never ask for passwords, card details or verification documents by email. If they entered their password, treat it as a compromised account (above).

## Declined good customers

A merchant whose genuine buyers are declined is asking for a review, not reporting fraud. Collect the payment references and send them to `fraud-reports` with the tag `decline-review`. Risk Operations may adjust its rules; support never tells a merchant that a decline came from the fraud model or what score a payment received.

## Disputes that look like fraud

Disputes in the fraud family are handled as disputes first; see [Chargebacks and disputes](chargebacks.md). If a merchant's fraud disputes rise sharply, T2 also sends a note to `fraud-reports`, so that Risk Operations sees the pattern.

## Template

`fraud-report-received`:

> Thank you for letting us know. I have passed the details to our risk team, who review reports like this as a priority. Please do not send card numbers by email or in this conversation; the payment references you have shared are all we need. We will come back to you if we need anything more, and in the meantime our documentation describes the protections you can switch on at your checkout.
