---
title: "Support macros"
---

Owner: Ewan Mabry, T1 team lead. Last reviewed 2026-10-06.

Macros are the saved replies in Harbour. They keep our answers consistent and save typing, but a macro is a starting point, never the whole reply: read the ticket, fill in the placeholders, cut what does not apply, and answer the question the merchant actually asked. An unedited macro does not count as a first response (see [Ticket priorities and SLAs](priorities-and-slas.md)).

## Using a macro

1. In the reply box, type `/` and the start of the macro's name, or pick it from the **Macros** menu.
2. Harbour fills placeholders such as `{{merchant.first_name}}` and `{{payment.reference}}` from the ticket's linked records. A placeholder it cannot fill stays visible in yellow; Harbour will not send a reply that still has one.
3. Some macros also set fields: a tag, a status, or a queue. The macro's description in Harbour lists what it changes. Check before you send.

## The catalogue

English macros. French macros start with `fr-` and are listed separately below.

| Macro | Use it when | Sets | Policy page |
|---|---|---|---|
| `ack-p1` | First response to a P1 | Tag `p1-ack` | [Support escalation playbook](escalation.md) |
| `escalated-to-t2` | You have escalated a ticket to T2 | Follower on the ticket | [Support escalation playbook](escalation.md) |
| `incident-known-issue` | A merchant writes about an ongoing incident | Asks for the `inc-` tag | [Support escalation playbook](escalation.md) |
| `refund-how-to` | A merchant asks how to refund | None | [Handling merchant refund requests](refunds.md) |
| `refund-out-of-window` | The payment is too old to refund | None | [Handling merchant refund requests](refunds.md) |
| `refund-approval-pending` | A large refund waits for T2 approval | None | [Handling merchant refund requests](refunds.md) |
| `refund-in-transit` | The refund succeeded but the buyer has not seen it | None | [Handling merchant refund requests](refunds.md) |
| `refund-cardholder-redirect` | A cardholder asks us for a refund | Status Solved | [Handling merchant refund requests](refunds.md) |
| `dispute-opened` | Explaining a new dispute | Queue `disputes` | [Chargebacks and disputes](chargebacks.md) |
| `dispute-evidence-reminder` | No evidence two days before submission | None | [Chargebacks and disputes](chargebacks.md) |
| `dispute-outcome-won` | The issuer decided for the merchant | Status Solved | [Chargebacks and disputes](chargebacks.md) |
| `dispute-outcome-lost` | The issuer decided for the cardholder | Status Solved | [Chargebacks and disputes](chargebacks.md) |
| `payout-delay-cutoff` | A payout missed the day's cut-off | None | [Payout delays: what to tell merchants](payout-delay-faq.md) |
| `payout-hold-new-seller` | A new seller's payout is held | None | [Payout delays: what to tell merchants](payout-delay-faq.md) |
| `payout-bank-rejected` | The seller's bank returned a payout | None | [Payout delays: what to tell merchants](payout-delay-faq.md) |
| `kyc-documents-request` | Risk needs documents from the merchant | Status Pending merchant | [Answering KYC queries](kyc-queries.md) |
| `kyc-status-check` | The merchant asks where their review stands | None | [Answering KYC queries](kyc-queries.md) |
| `dsar-forwarded` | You forwarded a request to the privacy team | Tag `dsar`, status On hold | [Forwarding data subject requests](data-subject-requests.md) |
| `fraud-report-received` | A merchant reports fraud | Queue `fraud-reports` | [Merchants reporting fraud](merchant-fraud-reports.md) |
| `survey-follow-up` | Following up a low survey rating | None | [Customer satisfaction surveys](csat.md) |

### French macros

| Macro | Use it when |
|---|---|
| `fr-p1-accuse-reception` | First response to a P1 from a French-speaking merchant, including out of hours |
| `fr-remboursement-procedure` | A merchant asks how to refund |
| `fr-remboursement-hors-delai` | The payment is too old to refund |
| `fr-remboursement-validation-t2` | A large refund waits for T2 approval |
| `fr-remboursement-en-cours` | The refund succeeded but the buyer has not seen it |
| `fr-remboursement-porteur` | A cardholder asks us for a refund |
| `fr-versement-retard` | A payout is late |

French macros are written by the Paris team, not translated from the English ones, and follow the conventions on [Supporting French-speaking merchants](french-speaking-merchants.md).

## Writing and changing macros

- **Propose** a new macro or a change in `#team-support`, with the text and two or three tickets where it would have helped. Ewan Mabry or Inès Moreau decides within a week.
- **Policy figures.** A macro that states a figure from a policy page, such as a deadline or a threshold, names that page in its internal description. When the policy page changes, its owner checks the macros that cite it; Harbour's macro search by page makes this a two-minute job.
- **Tone.** Plain, polite British English: say what happened, what we will do and when. No exclamation marks, no "unfortunately" at the start of a sentence, no internal names (no tool names, error codes or team channels).
- **Length.** If a macro needs scrolling on a phone, it is too long. Link to the merchant documentation at `docs.quillmoor.example` instead.
- **Retiring.** Harbour reports macros unused for 90 days each quarter; the owner retires them unless someone argues for keeping them.

## Common mistakes

- Sending `refund-how-to` to a merchant who has already tried and hit an error. Read the ticket first.
- Using `incident-known-issue` when no incident is declared. Only the support liaison decides that a ticket belongs to an incident.
- Leaving the default status a macro sets when it does not fit: `dispute-outcome-won` solves the ticket, which is wrong if the merchant has another question in the same thread.
