---
title: "Support escalation playbook"
---

**Owner:** Femi Haldane, head of customer support. **Maintained by:** Dorian Pask, T2 lead. **Last reviewed:** 2026-09-30.

This playbook says who works a merchant's ticket at each stage, when it moves up a tier, and when Merchant Support pages the payments on-call. It covers every ticket in Harbour, whatever the language or the queue. It assumes you have already set the ticket's priority: the scale and its response targets are on [Ticket priorities and SLAs](priorities-and-slas.md), and they are not repeated here.

## The three tiers

| Tier | Who | What it owns | Typical work |
|---|---|---|---|
| T1 | Support agents in London and Paris, about 26 people | Every new ticket; the first reply; triage; anything the merchant documentation, Merchant Hub or a macro answers | How do I issue a refund, why is my payout lower than my sales, how do I add a user |
| T2 | Payments specialists, eight in London and three in Paris | Investigations in the back office; approvals that T1 does not hold; disputes; strategic merchants; the support liaison in incidents | A payout missing after the usual checks, a refund over £10,000, chargeback evidence, a balance that does not reconcile |
| T3 | The engineering team that owns the service, reached through an ENG ticket or its on-call | Defects, outages and data corrections | A webhook never sent, a payout paid twice, a report with wrong figures |

T1 and T2 are both Merchant Support. T3 is not a support team: it is whichever engineering team owns the affected service, so an escalation to T3 always names a service and a team.

Each business day one T2 is the **T2 duty specialist**. They watch the `t2-investigations` queue, answer questions in `#team-support`, decide borderline pages, and become support liaison if an incident is declared. The duty is on the team calendar; [Support shift patterns](shift-patterns.md) explains who covers nights and weekends.

## Principles

1. **Support keeps the merchant.** Escalating adds people to the ticket; it does not hand the merchant to someone else. The agent who owns the ticket in Harbour keeps replying until T2 explicitly takes it over, and engineers do not reply to merchants directly.
2. **Escalate on facts, not on tone.** An angry merchant with a how-to question is still a T1 ticket. A polite merchant who says nobody can pay at checkout is a P1.
3. **Write it once.** The escalation note must let the next tier start without asking a question. If they have to come back to you for the merchant's reference or the payment, the note was not finished.
4. **One problem, one ticket.** Do not open a second Harbour ticket for the same problem; link related tickets instead, so that the history and the clock stay in one place.

## From T1 to T2

Escalate to T2 when any of the following holds. If you are unsure, ask the T2 duty specialist in `#team-support`.

- The merchant asks for a refund over £10,000 to be approved, or a large refund is stuck waiting for approval. See [Handling merchant refund requests](refunds.md).
- A dispute has opened and the merchant has sent evidence, or asks what to send. See [Chargebacks and disputes](chargebacks.md).
- A payout has not arrived and you have already worked through [Payout delays: what to tell merchants](payout-delay-faq.md).
- The merchant's balance, fees or payout amounts do not match their own records after you have gone through the payout report with them.
- The question touches KYC: a document rejected, an account restricted, a review the merchant contests. See [Answering KYC queries](kyc-queries.md).
- The merchant is on the strategic list: their tickets go to a named T2 owner. See [Strategic merchants](strategic-merchants.md).
- The merchant mentions a regulator, an ombudsman, a lawyer or court action. Escalate to T2 and tell Legal the same day (see "Other routes" below).
- The ticket has been reopened twice for the same problem.

### How to escalate in Harbour

Use the **Escalate to T2** action. It moves the ticket to the `t2-investigations` queue, keeps you as a follower, and asks for three fields: the product (Quillmoor Pay, Quillmoor Payouts, Merchant Hub or Merchant API), the merchant's account reference, and a one-line summary. Then add an internal note in this form:

```text
Merchant: [trading name], account [reference]
Asked: [what the merchant wants, in one sentence]
Checked: [what you have already looked at, and what you found]
Payments or payouts: [references, amounts, dates]
Merchant told: [what you have promised, and by when]
```

Reply to the merchant at the same time, so they know the ticket has moved and what happens next:

> Thank you for the details. I have passed your question to our payments specialists, who can look into your account in more depth. I will stay on this ticket with you and will update you by {{ticket.next_update}}.

T2 picks up a ticket in `t2-investigations` within the response target of its priority, as T1 would. If T2 needs more from the merchant, they ask through the ticket's owner, unless they have taken the ticket over: in that case the owner field changes, and T2 introduces themselves to the merchant in a short reply.

## From T2 to T3

T2 escalates to engineering when the evidence points to our systems rather than to the merchant's integration or to a bank, and support cannot put it right with the back-office tools.

### Non-urgent defects

Use **Create engineering ticket** in Harbour. It opens a ticket in the engineering project ENG with the merchant's reference, the Harbour link and the component, and shows the ENG ticket's status in the Harbour side panel. Choose the component by the service at fault:

| Symptom | Service | Team | Chat channel |
|---|---|---|---|
| Authorisations failing or slow; currency quotes wrong | `card-auth`, `fx-quote` | Payments Core | `#team-payments-core` |
| Payouts late, missing or duplicated; settlement files | `payout-gateway`, `settlement-batcher` | Payouts | `#team-payouts` |
| Balances, journal entries, statement lines | `ledger` | Ledger | `#team-ledger` |
| API errors, dashboard pages, merchant emails and webhooks | `merchant-api`, `merchant-hub`, `notify` | Merchant Experience | `#team-merchant-hub` |
| Payments declined by the fraud model | `risk-scorer` | Risk ML | `#team-risk-ml` |

Engineering teams acknowledge support tickets by the next business day and triage them at their weekly planning. For a quick question that does not need a ticket, ask in the team's channel, then paste the answer into the Harbour ticket as an internal note so that the next agent can find it.

Some problems look like defects but are not. A merchant who missed a webhook can usually be helped without engineering, because T2 can replay it: the procedure is on [How to replay a merchant webhook](../payments/replay-webhook.md). A merchant whose test payments fail in the sandbox is almost always using the wrong test account; check [Test merchants and test cards](../payments/test-merchants.md) before raising anything.

### Urgent problems

If the problem is happening now and affects payments or payouts, do not wait for a ticket to be triaged: page the payments on-call, as below.

## When to page the payments on-call

The payments on-call is the engineer on the Klaxon rota for Payments Core, Payouts and Ledger. Paging them can wake someone at night, so page when one of the conditions below holds, and not otherwise.

### Page when

| Situation | Why it cannot wait |
|---|---|
| Any P1 ticket: a merchant cannot take payments | Every minute is lost sales for the merchant |
| Three or more merchants report the same failure in payments or payouts within 30 minutes, even if each ticket alone is a P2 | It is probably ours, and probably spreading |
| The back office shows payout batches failing, for example with `PGW-5021`, for more than one merchant | Sellers will not be paid on time |
| Payouts appear to have been paid twice, or for the wrong amount | Money is leaving that may not come back |
| Authorisations declining with `CAU-1207` for several merchants at once | The path to the issuers is degraded |

Since ENG-27, setting a ticket to P1 in Harbour pages the payments on-call through Klaxon automatically, with the ticket's summary and link. Do not page a second time; check in the ticket's side panel that the Klaxon page shows as sent.

For the other situations, use **Page payments on-call** in the ticket's action menu, or email `payments-oncall@quillmoor.example`, which opens a Klaxon page. If Harbour itself is unavailable, the email route still works.

### Do not page for

- one merchant's integration error, such as API requests rejected because of a missing field;
- a single declined card, or one cardholder disputing a payment;
- questions about fees, statements or invoices;
- a P2 out of business hours that is not getting worse: it waits for the morning shift, which answers it first.

When in doubt, the T2 duty specialist decides in business hours and the support duty agent decides out of hours. A page that turns out to be unnecessary is not a failure, but tell the on-call at once so that they can stand down.

### What to put in a page

Keep it short: the on-call reads it on a phone.

```text
P1 / payments: [one line on the symptom]
Merchants affected: [count and references, or "one so far"]
Since: [time, UK]
Evidence: [error codes, payment references, Lantern link if you have one]
Harbour: [ticket link]
Support contact: [your name, and how to reach you]
```

### After paging

The on-call acknowledges in Klaxon; if they do not, Klaxon escalates by itself. Acknowledgement times and the escalation chain belong to engineering and are on [On-call rota and paging policy](../incidents/on-call.md).

The on-call decides whether the problem is an incident and, if so, declares it with `/klaxon declare`. Incidents use the production SEV scale, which engineering sets and which is not the ticket priority: a P1 ticket can turn out to be a SEV3, and a SEV1 can start from a P2 ticket. The SEV levels are defined on [Production incident management](../incidents/incident-management.md).

## During an incident

When an incident is declared, the T2 duty specialist (out of hours, the support duty agent) becomes the support liaison:

- Join the `#inc-[short name]` channel and say that you are the support liaison.
- Tag every related Harbour ticket with `inc-[short name]`, so that the tickets can be counted and answered together.
- Post the number of merchants who have contacted us, and any new symptom they describe, whenever it changes.
- Answer merchants with the `incident-known-issue` macro, which points to Beacon at `status.quillmoor.example`. Add no cause, timing or promise that is not on Beacon. The cadence of Beacon updates and their templates are on [Status page communications](../incidents/status-page.md).
- When the incident is resolved, send the closing reply from the tagged view and check that every tagged ticket has had an answer.

Support's input to the PIR goes to the IC through the liaison: what merchants saw, how many contacted us, and where our replies could have been faster.

## Other routes

Some tickets are not for engineering at all.

| Situation | Route | Read |
|---|---|---|
| A merchant's API key may have leaked | Email `security@quillmoor.example` at once; help the merchant create a new key | [Playbook: leaked secret or API key](../security/leaked-secret.md) |
| Someone asks for their personal data, or for an erasure request to be applied | Forward to `privacy@quillmoor.example` | [Forwarding data subject requests](data-subject-requests.md) |
| The merchant reports fraud on their marketplace | T2, `fraud-reports` queue | [Merchants reporting fraud](merchant-fraud-reports.md) |
| A seller's payout is held for review | T2; Risk decides | [Payout holds and releases](../payments/payout-holds.md) |
| A legal threat, a regulator or a formal complaint | T2, and email `legal@quillmoor.example` the same day; tag `formal-complaint` | |
| A Quillmoor invoice is contested | `finance@quillmoor.example` | |

## Escalating to a manager

A merchant who asks for a manager gets one: the T2 lead in business hours, or Femi Haldane for strategic merchants and formal complaints. Do not refuse; tell the merchant who will contact them and when. The manager reads the whole ticket first and then calls, rather than writing, unless the merchant prefers email.

## Worked examples

**A marketplace says checkout has shown "payment failed" for every buyer since 14:10.** P1. Harbour pages the payments on-call as soon as you set the priority. Reply with `ack-p1`, ask for two failed payment references, add them to the ticket, and stay with it.

**Three merchants in twenty minutes say yesterday's payouts are missing.** Each ticket alone is a P2. Together they meet the "three or more" rule: page the payments on-call, link the tickets, and post in `#team-support` so that other agents tag new ones.

**A merchant's refund of £14,200 is waiting in Merchant Hub.** Not urgent and not for engineering: it waits for T2 approval in `refund-approvals`. Check that it is in the queue and tell the merchant when to expect a decision.

**A merchant says their developer pasted the live API key in a public forum.** Security first: email `security@quillmoor.example` and help the merchant create a new key. This is not a page to the payments on-call.

## FAQ

**Can T1 page the payments on-call directly?** Yes. Every agent can, by setting P1 or from the action menu. A P1 needs no T2 permission.

**What if the on-call says the problem is not ours?** Note their reasoning on the ticket and keep working it as a T2 investigation. If more merchants report the symptom, page again and say what has changed.

**Who owns the ticket after T3 has fixed the problem?** The support owner, who confirms the fix with the merchant and solves the ticket. Engineers update the ENG ticket, not the merchant.

**Is there a T3 inside Merchant Support?** No. The tiers inside support stop at T2; T3 always means the owning engineering team.
