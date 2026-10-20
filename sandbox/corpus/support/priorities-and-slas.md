---
title: "Ticket priorities and SLAs"
---

- Owner: Femi Haldane, head of customer support
- Last reviewed: 2026-07-15
- Applies to: every merchant ticket in Harbour, in every queue and language

Every merchant ticket carries a priority from P1 to P4. The priority decides how quickly a person must first answer the merchant, who is told about the ticket, and whether anyone is woken up. This page is the only place where the support scale is defined. Other support pages use P1 to P4 and link here rather than repeating the targets.

## The scale

| Priority | Meaning | First response | When the clock runs |
|---|---|---|---|
| P1 | A merchant cannot take payments | Within 15 minutes | At all hours, every day of the year |
| P2 | A major function is impaired | Within 1 hour | In business hours |
| P3 | A minor problem, a problem with a workaround, or a question that needs investigation | Within 8 business hours | In business hours |
| P4 | A general question, a request for information, feedback | Within 2 business days | In business hours |

A **first response** is a reply from a person to the merchant that shows we have read and understood the ticket. The automatic acknowledgement does not count, nor does an internal note. A macro counts if you have adapted it to the ticket; an unedited macro sent to stop the clock does not, and the weekly review treats it as a breach.

The SLA is about the first response only. Resolution has no contractual target, but each priority has an internal update cadence (see "What each priority sets in motion").

## Business hours

| Queue | Business hours | Days |
|---|---|---|
| English-language queues | 08:00 to 18:00 UK time | Monday to Friday, except bank holidays in England |
| `fr-marchands` | 09:00 to 18:00 Paris time | Monday to Friday, except French public holidays |

A ticket follows the business hours of the queue in which it arrived. Moving a ticket to another queue does not restart or change its clock: a ticket that a London agent moves to `fr-marchands` keeps its original due time.

Worked examples, for an English-language queue:

| Arrives | Priority | First response due |
|---|---|---|
| Sunday 03:10 | P1 | Sunday 03:25 |
| Wednesday 17:45 | P2 | Thursday 08:45 |
| Friday 16:30 | P3 | Monday 14:30 |
| Thursday 11:00 | P4 | Monday 11:00 |
| Saturday 10:00 | P3 | Monday 16:00 |

Harbour computes the due time and shows it on the ticket; you should never need to work it out by hand, but it helps to know why a ticket is due when it is.

## Choosing the priority

T1 sets the priority on first triage. Ask these questions in order and stop at the first "yes".

1. **Can the merchant take payments?** If buyers cannot complete card payments at the merchant's checkout, for all of them or for every buyer using one of the card schemes, it is a P1. A merchant who can take payments, however unhappy, is not a P1.
2. **Is a major function impaired?** Payouts not sent, no user able to sign in to Merchant Hub, refunds impossible to issue, a whole Merchant API endpoint failing, webhooks not delivered: a P2.
3. **Is it a problem with a workaround, or a question that needs someone to investigate?** A P3. Most tickets are P3.
4. **Is it information, feedback or a request with no time pressure?** A P4.

### Examples

| Ticket | Priority | Why |
|---|---|---|
| "Every payment at our checkout has failed since 10:20" | P1 | The merchant cannot take payments |
| "Buyers with cards from one of the card schemes all get an error; others are fine" | P1 | Those buyers cannot pay at all |
| "Some payments are declined, most go through" | P3, or P2 if the share is rising | Payments are being taken; T2 checks the decline reasons |
| "Yesterday's payout has not arrived" | P2 | A major function; see [Payout delays: what to tell merchants](payout-delay-faq.md) |
| "Nobody on our team can sign in to Merchant Hub" | P2 | Payments still work, the dashboard does not |
| "The refund button gives an error, but the API works" | P3 | There is a workaround |
| "How do I add a user with read-only access?" | P4 | Information |
| "Our sandbox test payments fail" | P3 at most | Test mode never takes real payments; see [Test merchants and test cards](../payments/test-merchants.md) |
| "We have a dispute and want to know what to send" | P3 | Time-bound, but days, not hours; see [Chargebacks and disputes](chargebacks.md) |
| "Please send a copy of last year's invoices" | P4 | No time pressure |

### What does not change the priority

- The merchant's size or importance. Strategic merchants use the same scale; their tickets reach a named owner faster through routing, not through a higher priority. See [Strategic merchants](strategic-merchants.md).
- The merchant writing "urgent" in the subject, or following up several times.
- The channel: a P1 by email is a P1, and a P4 in a chat is a P4.

### What does change it

- **Upgrade** when the impact grows: the workaround stops working, a second merchant reports the same thing, or the merchant's payments start failing. Any agent can upgrade.
- **Downgrade** when the impact shrinks: for example, once the merchant can take payments again but wants an explanation, the follow-up becomes a P3. Only a T2 or a team lead may downgrade a P1. Write the reason in an internal note; Harbour records the change.

## What each priority sets in motion

| Priority | Harbour does | People do | Update the merchant |
|---|---|---|---|
| P1 | Pages the payments on-call through Klaxon (since ENG-27); out of hours, also pages the support duty agent; pins the ticket at the top of every view | First response; then follow [Support escalation playbook](escalation.md) | At least every hour until the merchant can take payments again |
| P2 | Notifies the T2 duty specialist; moves the ticket to the top of its queue | T1 investigates; T2 joins if the cause is not obvious within the hour | At least every 4 business hours |
| P3 | Sorts by due time | Worked in due-time order | When something changes, and at least every 2 business days |
| P4 | Sorts by due time | Worked in due-time order; can be answered in batches | With the answer |

## The clock in detail

- The clock starts when the ticket is created, whether by email, through the contact form in Merchant Hub, or from a chat transcript.
- It stops at the first public reply by a person.
- Setting a ticket to **Pending merchant** before the first response does not stop the clock: you cannot be waiting for a merchant you have not yet answered.
- When tickets are merged, the merged ticket keeps the earliest creation time and the highest priority.
- A ticket that the merchant reopens after it was solved gets a new first-response target at its current priority.
- A ticket that arrives in the wrong language queue keeps its clock; move it quickly, because the receiving team inherits whatever time is left.

## Breaches

Harbour turns a ticket amber when 75% of the first-response target has elapsed, and red when the target is missed.

- **P3 and P4 breaches** are reviewed by the team lead each morning, looking for patterns: a queue short of people, a macro that confuses merchants, a type of ticket that T1 cannot answer.
- **P2 breaches** are reviewed by the T2 lead within two business days.
- **P1 breaches** are reviewed by Femi Haldane within the week, with the agent and, if it happened out of hours, the support duty agent. The review is blameless: the question is what made the target hard to meet, not who missed it.

Every breach is counted in the weekly review. The current figures are in [Support weekly review October 2026](weekly-review-2026-10.md).

## Targets

| Priority | First responses on time, target |
|---|---|
| P1 | 98% |
| P2 | 95% |
| P3 | 92% |
| P4 | 90% |

These are measured per calendar month, per queue. A month below target in any queue gets an action in the next weekly review.

## Common mistakes

These come up in almost every month's breach review.

- **Setting P1 for a payout problem.** Payouts matter a great deal to marketplaces, but a payout problem is a P2; the paging rule for several merchants exists so that a widespread payout failure still reaches the on-call quickly.
- **Leaving a new ticket at the default P3.** Harbour gives every new ticket P3 until someone triages it. A P1 that sits at P3 for twenty minutes has already breached; triage the `general` queue from the oldest ticket first.
- **Downgrading to buy time.** Lowering a priority to move its due time is never acceptable, and the weekly review checks every downgrade made in the hour before a due time.
- **Treating a reopened ticket as old.** A reopened ticket has a new target; it appears in the queue by due time like any other.

## Three scales, never mixed

Quillmoor has three severity scales, and support must not mix them:

- **P1 to P4**, defined here, rate a merchant's ticket. Support sets them.
- **SEV1 to SEV4** rate a production incident. Engineering sets them; they are defined on [Production incident management](../incidents/incident-management.md).
- **S1 to S4** rate a security incident. The SIRT sets them; they are defined on [Security incident response plan](../security/incident-response-plan.md).

A P1 ticket is not a SEV1. One merchant who cannot take payments because of their own configuration is a P1 for us and no incident at all for engineering; a SEV2 incident may reach us as twenty P2 tickets. Never write "SEV1" on a ticket to mean "very urgent", and never tell a merchant what SEV level an incident has.

The ideas board in `PRB` holds a proposal, "One severity scale for incidents, security and support". Until it is decided, the three scales stay separate.

## FAQ

**Does a French-speaking merchant get a P1 response out of Paris hours?** Yes. P1 runs at all hours for every merchant. Out of hours the support duty agent answers, in English, with the `fr-p1-accuse-reception` macro attached so that the merchant also has a French acknowledgement. See [Supporting French-speaking merchants](french-speaking-merchants.md).

**A payout has failed for a whole marketplace's sellers. Is that a P1?** No: the merchant can still take payments, so it is a P2. If several merchants are affected, the paging rule in the escalation playbook applies anyway.

**Can a merchant set the priority?** No. The contact form asks the merchant how urgent the problem is, and Harbour shows the answer, but an agent sets the priority.

**Does the priority change when T2 takes a ticket over?** No. The priority follows the impact on the merchant, not the tier working on it.

**Do internal tickets, from colleagues, use this scale?** No. The scale is for merchants' tickets. Colleagues' requests go to the team's chat channel or to the owning team's own queue.

**What if I set P1 and it turns out not to be?** Ask T2 to downgrade it and tell the on-call. A P1 set in good faith is never wrong.
