---
title: "On-call rota and paging policy"
---

# On-call rota and paging policy

Owner: Lukas Brennand, site reliability lead (`#team-sre`)
Agreed with: Rhiannon Dace, head of people, for the allowance and time off in lieu
Last reviewed: 2026-10-05

This policy covers everyone on a production rota in Klaxon: who is on call, how
quickly you must answer, how rotas hand over and swap, and what you receive for being
on call. Data Platform and Security run rotas under this policy too, with additions
on their own pages ([data platform on-call](../data/data-on-call.md) and the
[security incident response plan](../security/incident-response-plan.md)).

How incidents are run once you have answered a page is on
[production incident management](incident-management.md).

## The rotas

Each team owns its rotas in Klaxon. A rota has a primary, who is paged first, and
usually a secondary, who is paged when the primary does not acknowledge. Rotas run 24
hours a day, 7 days a week, unless the table says otherwise.

| Rota in Klaxon | Staffed by | Hours | Pages for |
|---|---|---|---|
| `payments-primary`, `payments-secondary` | Payments Core, Payouts and Ledger engineers together | 24/7 | `card-auth`, `fx-quote`, `payout-gateway`, `settlement-batcher`, `ledger`: the first responder for all of them |
| `payouts` | Payouts | Business days, 08:00 to 20:00 UK time | Escalations from the payments on-call; calls to our settlement bank's operations desk |
| `ledger` | Ledger | Business days, 08:00 to 20:00 UK time | Escalations, schema migration questions, reconciliation breaks |
| `merchant-exp-primary`, `merchant-exp-secondary` | Merchant Experience | 24/7 | `merchant-api`, `merchant-hub`, `notify` |
| `platform-primary`, `platform-secondary` | Platform | 24/7 | Kubernetes, Shipwright, Switchboard, Apache Kafka |
| `sre-primary`, `sre-secondary` | Site Reliability | 24/7 | Lantern, Klaxon itself, anything without an owner |
| `risk-ml-primary` | Risk ML | 24/7 | `risk-scorer` and the fraud model |
| `data-primary` | Data Platform | See the data platform page | Tier 1 warehouse tables |
| `security-oncall` | Security | 24/7 | Security reports; see the security plan |
| `ic-primary`, `ic-secondary` | Trained ICs from several teams | 24/7 | SEV1 and SEV2 incidents |
| `comms-lead` | Merchant Support | 24/7 for SEV1, business hours otherwise | SEV1 and SEV2 incidents |

**"The payments on-call"**, a phrase you will see in runbooks and in Harbour, means
whoever is primary on `payments-primary`. Email to payments-oncall@quillmoor.example
opens a page to that rota, and Harbour pages it automatically when a ticket is set to
P1 (ENG-27). The payments on-call is expected to start any payments runbook alone, and
to page `payouts` or `ledger` when the runbook says so. Out of hours those two rotas
are paged on a best-effort basis: the page reaches the team lead's phone as well, and
whoever is awake answers. Do not bounce a merchant's ticket between payments teams;
the payments on-call owns it until it is handed over in the incident channel.

### Who goes on a rota

- Engineers on an owning team join its rota after shadowing it for two full weeks.
  Shadowing means receiving every page, joining every incident and doing nothing
  alone.
- Being on call is part of the job for engineers on those teams. Exceptions, for
  health, caring responsibilities or anything else, are agreed privately with your
  manager and People; nobody else needs to know why.
- A rota needs at least six people, so that nobody is on call more than one week in
  six. A team that drops below six tells Lukas Brennand, and Site Reliability lends a
  secondary until the team recovers.

## Response times

Klaxon pages carry the severity set by the alert or by whoever declared the incident.
You must acknowledge in Klaxon within these times, and then join the incident channel
or open one.

| Page | Acknowledge within | If nobody acknowledges |
|---|---|---|
| SEV1 | 5 minutes | Klaxon pages the secondary at 5 minutes, then the team lead at 10 minutes, then the head of department |
| SEV2 | 15 minutes | Klaxon pages the secondary at 15 minutes, then the team lead at 30 minutes |
| SEV3 | Next business morning, by 10:00 | Not paged out of hours; Klaxon posts to the team channel |
| SEV4 | Within the sprint | A ticket, never a page |

Acknowledging means "I have seen this and I am on it". It does not mean you have fixed
it, or that you know what it is. If you cannot work on it, because you are driving or
on a train with no signal, do not acknowledge: let Klaxon escalate, which is faster
than acknowledging and handing over by message.

**Raising the severity of your own page.** If an alert arrived as a SEV2 and you can see
it is worse, declare at the higher level with `/klaxon declare`. The new level starts
its own clock for the IC rota.

## Hand-overs

Every rota hands over on **Mondays at 10:00** UK time, the outgoing and the incoming
person together, on a call or in person. The fixed time came with the Klaxon paging
migration, ENG-11, completed in ENG Sprint 7 in July 2025. Before then each team chose
its own day, most chose Friday afternoon, and the person who had just taken over went
straight into a weekend with an unfamiliar backlog.

Use the [on-call handover checklist](handover-checklist.md). A hand-over takes 15 to 30
minutes. When the Monday is a bank holiday, the hand-over still happens at 10:00, by
chat and a short call; it is the one Monday call that is allowed to be brief.

The outgoing person stays responsible for any incident they are IC or operations lead
on until they hand it over explicitly in its channel, even after 10:00.

## Swaps and cover

Swaps are **agreed in Klaxon at least 24 hours ahead**. One person proposes the swap in
Klaxon, the other accepts it there, and Klaxon updates who will be paged. A swap agreed
in chat but not in Klaxon does not exist, because Klaxon is the only thing that pages.

- Swaps less than 24 hours ahead are for emergencies only. The team lead arranges the
  override in Klaxon and tells the person who will be paged.
- Book annual leave knowing your rota dates, and arrange the swap before you book. The
  leave policy says the same thing from the other side.
- Short absences while on call (a two-hour appointment, a flight) are covered by
  asking your secondary in the team channel and setting a Klaxon override for those
  hours. The 24-hour rule applies to whole shifts, not to an afternoon.

## Allowance and time off in lieu

| | |
|---|---|
| On-call allowance | **£250 per week on call**, primary or secondary, paid with the following month's salary |
| Part weeks | Paid pro rata by day, for swaps and cover |
| Call-out after 23:00 | **Time off in lieu**: half a day, or a whole day if you worked more than two hours after 23:00 |
| Bank holiday on call | One extra day of time off in lieu for each bank holiday in your on-call week |
| Rest | After a call-out after 23:00, start no earlier than 11:00 the next morning, whatever the time off in lieu |

Record time off in lieu in Haven, under "Time off in lieu", within the same month,
with the incident channel in the comment; your manager approves it. Take it within
eight weeks. Haven sends the allowance to payroll from the Klaxon schedule, so you do
not claim it; check your payslip and tell `#team-sre` if a week is missing.

Colleagues employed in France are on call under the French on-call agreement, which
sets the equivalent allowance and rest rules; ask People through
people@quillmoor.example.

If a call-out ever needs you in the office at night, which is rare, the taxi rule in
the [expenses policy](../finance/expenses.md) applies.

## What being on call asks of you

- Klaxon on your phone, with notifications allowed to break through silent mode. See
  [setting up Klaxon on your phone](klaxon-setup.md), and send yourself a test page at
  the start of each shift.
- Your laptop, charged, within reach, and an internet connection good enough for a
  video call. Being on call does not mean staying at home; it means being able to
  start work within 15 minutes of a SEV1 page.
- Fit to work. If you are unwell, tell your secondary and your team lead and swap; that
  is what the secondary is for.
- Working from abroad is possible on call if the connection is reliable and you stay
  within a couple of hours of UK time. Tell your secondary.

What being on call does not ask of you:

- To fix everything alone. Page the secondary, the team lead or another team as soon
  as you would like a second pair of eyes. Waking someone at 03:00 for a SEV1 is
  correct; apologising is optional.
- To run the incident and fix it at the same time. For a SEV1 or SEV2, the IC rota is
  paged with you; let the IC take the coordination.
- To work on a SEV3 at night. SEV3 waits for the morning unless it is getting worse.

## Keeping the rotas healthy

Site Reliability reviews every rota monthly, using Klaxon's page reports:

- **Out-of-hours pages.** The target is fewer than two per rota per week. A rota above
  it for two months running gets an action to fix its alerts, owned by the team lead.
- **Pages without action.** An alert that pages and needs nothing done is deleted or
  downgraded to a ticket. Ask in `#team-sre` if you are unsure whether an alert is
  needed.
- **Unacknowledged pages.** Each escalation to a secondary is looked at, gently. The
  usual cause is a phone setting, not a person.

The monthly numbers are posted in `#team-sre` and kept on the Lantern dashboard
"on-call health".

## Related pages

- [Production incident management](incident-management.md)
- [Incident roles quick reference](roles-quick-reference.md)
- [Escalation contacts for incidents](escalation-contacts.md)
- [Runbook: rolling back payout-gateway](../payments/payout-gateway-rollback.md), one of
  the payments runbooks you are most likely to need at night

## Questions people ask

**Do I get the allowance if nothing happens all week?** Yes. The allowance pays for
being available, not for being paged.

**I was paged at 22:50 and worked until 23:40. Do I get time off in lieu?** Yes: the
call-out ran after 23:00. Half a day, since you worked less than two hours after 23:00.

**My partner is having a baby next month and I cannot know the date.** Tell your team
lead now. You will not be scheduled in the weeks around the due date, and the 24-hour
rule does not apply to that kind of emergency.

**Can I be on two rotas at once?** No, except the IC rota, which ICs may hold on top of
their team rota as long as they are not primary on both in the same week.

**I was paged for a P1 ticket that was not an incident. Was the page wrong?** Not
necessarily. Support pages on the merchant's symptoms; deciding that it is not an
incident is a perfectly good outcome. Tell the support agent, so they can update the
merchant.
