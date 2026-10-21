---
title: "Answering KYC queries"
---

Owner: Dorian Pask, T2 lead, agreed with Risk. Last reviewed 2026-05-27.

## What KYC means here

KYC stands for "know your customer": the checks we make to confirm who a merchant is, who owns and controls it, and what business it does. We must make them before a merchant can take payments, and again from time to time while the account is open. For marketplaces, sellers who receive payouts through Quillmoor Payouts are checked too.

Risk carries out KYC reviews and decides on them. Merchant Support does not review documents, does not decide whether a merchant passes, and does not overrule a decision. Our part is to explain the process, help the merchant send what Risk asks for, and keep them informed.

## When merchants contact us

| The merchant says | What is usually happening | Answer with |
|---|---|---|
| "Why are you asking for documents again?" | A periodic review, or a change on the account: new owner, new director, new bank account, a large rise in volume | `kyc-documents-request`, adapted |
| "Which documents do you need?" | The request in Merchant Hub lists them | Point to the **Verification** page in Merchant Hub |
| "We sent everything a week ago" | Documents incomplete, unreadable or expired; or the review is still in progress | `kyc-status-check` |
| "Why are our payouts paused?" | Payouts can be held until a review is complete | `kyc-status-check`, and see [Payout delays: what to tell merchants](payout-delay-faq.md) |
| "Why was our account restricted?" | Possibly a KYC finding; possibly something we cannot discuss | Escalate to T2; see "What not to say" |

Risk aims to complete a review within 2 business days of receiving a complete set of documents. Do not promise a date; say that the review is under way and that the merchant will be told by email as soon as it is finished.

## Documents

- Merchants upload documents only on the **Verification** page in Merchant Hub. Never accept identity documents, bank statements or company papers by email or chat, and never forward them from a ticket. If a merchant attaches them to a ticket, delete the attachment from the ticket (Harbour's **Redact** action), tell the merchant why, and ask them to use Merchant Hub.
- We cannot tell merchants which document will "pass". We can repeat what Risk asked for, word for word, from the request.
- A document in a language other than English or French may need a certified translation. Risk says so in the request when it does.

## What not to say

Some restrictions follow checks that we are not allowed to discuss with the merchant. If the back office marks an account restriction as **confidential**, say only that the account is under review and that the merchant will be contacted. Do not guess, do not hint, and do not say what the review is looking for. Escalate to T2, who will ask Risk what, if anything, can be shared.

Never tell a merchant that a review was caused by a particular payment, buyer or seller.

## Escalation

Escalate to T2, through the `kyc` queue, when a merchant disputes a KYC decision, when a review has taken more than 5 business days since the merchant's documents were complete, or when a strategic merchant is affected (see [Strategic merchants](strategic-merchants.md)). T2 raises it with Risk; support never contacts individual Risk reviewers directly.

## Templates

`kyc-documents-request`:

> As part of our regular checks, we need to confirm some details about your business. You will find the list of documents we need on the **Verification** page in Merchant Hub, where you can also upload them securely. Please do not send them by email. Once we have everything, our team usually completes the review within a few business days.

`kyc-status-check`:

> Thank you for checking. Your verification is in progress with our team, and you will receive an email as soon as it is complete. If we need anything else from you, it will appear on the **Verification** page in Merchant Hub.
