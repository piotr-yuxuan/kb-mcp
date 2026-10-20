---
title: "Product discovery and the ideas board"
---

Owner: Ama Rowntree. Last reviewed: 2026-09-21.

## In short

Ideas live on **the ideas board**, the Product Discovery project `PRB` in Jira. Anyone at Quillmoor can add one. Product managers triage the board every week, collect evidence against the ideas worth pursuing, and bring the strongest into [quarterly planning](quarterly-planning.md), where they become epics in ENG.

The board is not a backlog and not a vote. An idea with many requests and no evidence of the problem stays where it is.

## What goes on the board

- Problems merchants or sellers have, and features that might solve them.
- Problems in our own processes and internal tools. The board is open to every team, not only to merchant-facing products; several of the current ideas are internal.
- Not bugs (raise them in ENG with the owning team) and not incidents.

## How to add an idea

1. Search the board first. If the idea exists, add your evidence to it as an insight rather than creating a duplicate.
2. Write the summary as the outcome someone wants, in a sentence: "Let payout operators roll back a payout-gateway release themselves", not "Rollback button".
3. Describe the problem, who has it, and how often. Link the wiki pages that describe today's process.
4. Add at least one insight: a support ticket, an interview note, an incident report, a quote from a sales call.
5. Mention it in `#team-product` if it is urgent.

## How ideas move

| Stage | Meaning | Who moves it |
|---|---|---|
| Parking lot | New or not yet looked at | Anyone, on creation |
| Discovery | A product manager is collecting evidence and sizing it | Product manager |
| Ready for delivery | Problem understood, rough size known, owner team agrees | Product manager with the team lead |
| Delivery | An epic in ENG exists and is linked | Product manager, at planning |
| Won't do | Declined, with the reason written on the idea | Head of product |

Triage happens on Wednesdays: Ama Rowntree and the product managers go through new ideas and anything with fresh insights. Each idea gets an impact score from 1 to 5, an effort size, and, where it fits, the objective it would serve.

## Ideas on the board now

These five are the ideas with the most activity this quarter.

| Idea | Area | Related pages |
|---|---|---|
| Let payout operators roll back a payout-gateway release themselves | Payments operations | [Runbook: rolling back payout-gateway](../payments/payout-gateway-rollback.md), [Reverting a bad release](../release/reverting-a-release.md) |
| One severity scale for incidents, security and support | Incidents, security, support | [Production incident management](../incidents/incident-management.md), [Security incident response plan](../security/incident-response-plan.md), [Ticket priorities and SLAs](../support/priorities-and-slas.md) |
| Automate erasure requests end to end | Data and privacy | [Erasure requests in the warehouse](../data/erasure-requests.md), [DPA playbook](../legal/dpa-playbook.md) |
| Dark mode for every Merchant Hub page | Merchant Hub | [Theming and dark mode](../design/theming.md), [dark mode brief](brief-dark-mode.md) |
| Show each employee's leave carry-over balance | People | [Annual leave policy (UK)](../people/annual-leave-uk.md), [Congés payés et RTT (France)](../people/conges-payes-rtt.md) |

A few notes on where they stand:

- **Payout-gateway rollback.** Today a rollback goes through the on-call engineer, following the runbook. The idea asks whether payout operators could do it themselves safely; the runbook's safety steps are the main question, and the Payouts team owns the answer.
- **One severity scale.** We run three separate scales for production incidents, security incidents and support tickets. The idea is to have one. It touches three owners and is mostly a policy question, which is why it has stayed in discovery.
- **Erasure requests.** ENG-19, closed in July, automated the warehouse part. The idea covers the rest: intake, the checks Legal makes, and the confirmation to the requester.
- **Dark mode.** Delivery started as ENG-26, which covers the twenty most visited pages. The idea stays open for the pages beyond them.
- **Leave carry-over balance.** Asked for by the People team, for staff in both the UK and France. It would show, in Haven, how many days each person can still carry over.

## From idea to epic

An idea becomes an epic only through quarterly planning, where it competes for capacity with everything else. When it does, the product manager links the epic to the idea and moves the idea to "delivery". When the epic closes, the idea is closed with a link to the release notes or the brief.

Strategic bets that come from the leadership team, such as instant payouts, may skip the board and start with a brief instead; see the [instant payouts brief](brief-instant-payouts.md).
