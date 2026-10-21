---
title: "Support shift patterns"
---

Owner: Joss Fairweather, support operations analyst. Last reviewed 2026-10-09, when the November rota was published.

Merchant Support is staffed in business hours from London and Paris, and covered at all other times by one person on call, the support duty agent, for P1 tickets only. This page describes the shifts, the duty, and how to change either. Business hours themselves are defined on [Ticket priorities and SLAs](priorities-and-slas.md).

## Who works where

| Group | London | Paris |
|---|---|---|
| T1 agents | 20 | 6 |
| T2 specialists | 8 | 3 |
| Leads | Femi Haldane, Dorian Pask (T2), Ewan Mabry (T1) | Inès Moreau |

## Weekday shifts

| Shift | Hours | Covers |
|---|---|---|
| London early | 07:30 to 16:00 UK time | Opens the English queues; triages the overnight backlog before 08:00 |
| London late | 09:30 to 18:00 UK time | Closes the English queues |
| Paris early | 08:30 to 17:00 Paris time | Opens `fr-marchands` |
| Paris late | 09:30 to 18:00 Paris time | Closes `fr-marchands` |

Each shift includes an unpaid break of 30 minutes and two short breaks, taken so that each queue always has at least two agents. Roughly half of each team works each shift; Joss balances the split to the expected volume by day, since Mondays and the first business day after a bank holiday are always the busiest.

Each business day, one T2 specialist is the **T2 duty specialist**: they watch `t2-investigations`, answer questions in `#team-support` and become the support liaison if an incident is declared. See [Support escalation playbook](escalation.md).

## Handover

- **16:00 UK time**, London early to London late: the early shift posts in the day's `#team-support` thread any ticket it has promised to update before 18:00, and any open P1 or P2.
- **18:00 UK time**, London late to the support duty agent: the late shift posts open P1 tickets and anything the duty agent should watch. Paris posts at 18:00 Paris time in the same thread.
- Every handover note names tickets, not general concerns.

## Support duty

Outside business hours, and all weekend, one agent is on the Klaxon rota `support-duty`. The duty runs for a week and hands over at the same day and time as the engineering rotas; see [On-call rota and paging policy](../incidents/on-call.md), which also sets the allowance and compensation that apply to support duty.

The support duty agent:

- is paged by Harbour for every P1 that arrives outside business hours, alongside the payments on-call;
- sends the first response, in English, attaching `fr-p1-accuse-reception` for French-speaking merchants;
- stays with the merchant until the payments on-call has taken the problem over, then updates the merchant as the escalation playbook requires;
- does nothing with P2 to P4 tickets, which wait for the next business day.

The rota draws on T2 specialists and T1 agents with more than a year in the team. Before your first duty week, shadow one, and check your phone with [Setting up Klaxon on your phone](../incidents/klaxon-setup.md). On the first evening of each duty week, Klaxon sends a test page; acknowledge it.

## Peak periods

In November, when volume rises sharply, the London late shift runs until 20:00 on weekdays, and a second support duty agent covers Fridays and Saturdays. The November rota is published at least four weeks ahead. Annual leave in November and the first half of December needs a lead's agreement before you book it.

## Changing your shifts

- The rota is published on the team calendar four weeks ahead.
- Shift swaps are agreed between the two agents and approved by a lead in `#team-support` at least two business days before the shift.
- Support duty swaps are made in Klaxon, under the same rule as engineering swaps.
- Annual leave is booked in Haven; see [Annual leave policy (UK)](../people/annual-leave-uk.md) or, for Paris, [Congés payés et RTT (France)](../people/conges-payes-rtt.md). Book it before the rota is published if you can.
- Sickness: tell your lead as early as possible; the lead rebalances the day's shifts.
