---
title: "Using Harbour"
---

*Owner: Ewan Mabry, T1 team lead. Last reviewed 2026-06-18. New agents: read this in your first week, alongside [Support macros](macros.md).*

Harbour is our support desk. Every conversation with a merchant, whether it starts by email, through the contact form in Merchant Hub or in a chat, becomes a Harbour ticket, and every ticket carries its own history, priority and clock.

## Getting access

You get Harbour access on your first day, with your Quillmoor account; there is no separate password. The role you start with is **Agent (T1)**. T2 roles, the ability to approve refunds, and access to the `strategic` queue are granted by the T2 lead. Harbour access is certified in every quarterly access review, like any other system; see [Quarterly access reviews](../security/access-reviews.md).

## Queues

| Queue | What lands there | Worked by |
|---|---|---|
| `general` | Every new English-language ticket that no rule routes elsewhere | T1, London |
| `fr-marchands` | Tickets from merchants whose account language is French | T1 and T2, Paris |
| `payouts` | Tickets the contact form tags as payout questions | T1, with T2 support |
| `kyc` | Verification questions and document requests | T1; decisions by Risk |
| `disputes` | Inquiries and chargebacks, created automatically | T2 |
| `refund-approvals` | Refunds over the approval threshold, created automatically | T2 |
| `t2-investigations` | Tickets escalated by T1 | T2 |
| `fraud-reports` | Merchants reporting fraud, and refunds T2 has held | T2 and Risk Operations |
| `strategic` | Every ticket from a strategic merchant | Named T2 owners |

Work your queue by due time, oldest first, not by arrival. The **My due soon** view shows every ticket you own that turns amber in the next two hours.

## Anatomy of a ticket

- **Requester and account.** Harbour links the sender to a merchant account by email address. If it cannot, link the account by hand before replying; placeholders in macros will not fill otherwise.
- **Priority.** P3 by default until someone triages it. Set it on first read; the scale is on [Ticket priorities and SLAs](priorities-and-slas.md).
- **Product.** Quillmoor Pay, Quillmoor Payouts, Merchant Hub or Merchant API. Reports use it, so set it even when it seems obvious.
- **Status.** New, Open, Pending merchant, On hold, Solved, Closed. Pending merchant means the ball is in their court; On hold means we are waiting for someone inside Quillmoor. A Solved ticket closes by itself after seven days without a reply.
- **Side panel.** Shows the merchant's recent payments and payouts, linked ENG tickets with their status, and any Klaxon page sent from the ticket.

## Public replies and internal notes

The reply box has two modes. **Public reply** goes to the merchant. **Internal note** is visible only to Quillmoor staff and has a yellow background. Before you press send, look at the colour. Never paste internal error codes, colleagues' chat messages or other merchants' details into a public reply.

## Actions

The **Actions** menu at the top right holds the operations that move a ticket beyond T1:

| Action | What it does |
|---|---|
| Escalate to T2 | Moves the ticket to `t2-investigations` and asks for an escalation summary |
| Create engineering ticket | Opens a linked ticket in the engineering project ENG |
| Page payments on-call | Sends a Klaxon page with the ticket's summary |
| Forward to privacy | Sends the ticket to `privacy@quillmoor.example` and puts it on hold |
| Merge | Joins duplicate tickets; the oldest creation time and highest priority win |

When and how to use the first three is on [Support escalation playbook](escalation.md). Setting a ticket to P1 also pages the payments on-call by itself, a rule built under ENG-27.

## Tags

Tags drive reports and bulk replies. The ones that matter most:

- `inc-[short name]` for tickets about a declared incident;
- `formal-complaint` for complaints that Legal must see;
- `dsar` for forwarded requests about personal data;
- `p1-ack`, set by the `ack-p1` macro.

Do not invent tags for one ticket. If you think a new tag would help a report, ask in `#team-support`.

## Shortcuts

| Keys | Does |
|---|---|
| `g` then `q` | Go to your queue |
| `r` | Public reply |
| `n` | Internal note |
| `/` in the reply box | Search macros |
| `Shift` and `Enter` | Send and go to the next ticket |

## When Harbour is down

Harbour's status is in the Lantern dashboard "Harbour health". If Harbour is unavailable, keep a list of merchants who contacted you by phone or chat, and enter them as tickets as soon as it returns. A P1 can still reach the payments on-call by email at `payments-oncall@quillmoor.example`.
