---
title: "Post-incident review template"
---

# Post-incident review template

*Maintained by Site Reliability. Page owner: Lukas Brennand. Last reviewed on
2026-07-14, after the review of the Merchant Hub login outage showed that the
"Detection" section was too often left empty.*

A **post-incident review (PIR)** is how we learn from an incident: a written account of
what happened and why, a meeting to test that account with the people who were there,
and a short list of actions that make the next incident less likely or less painful.
This page explains when a PIR is needed, how to run it, and what goes in each section
of the template. The template itself is further down, ready to copy.

## When a PIR is needed

| Incident | PIR |
|---|---|
| SEV1 | Always |
| SEV2 | Always |
| SEV3 | When the IC asks for one; usually a short form (summary, timeline, cause, actions) |
| SEV4 | No; a note in the owning team's channel is enough |
| A near miss | When anyone involved thinks it was luck that kept it from being a SEV2 |

For SEV1 and SEV2 incidents, **the review meets within 5 business days of resolution**.
Not of detection, not of mitigation: of the moment the IC resolved the incident in
Klaxon. Five business days is long enough to gather logs and short enough that people
still remember why they did what they did. If a key person is on annual leave, hold
the meeting anyway and send them the draft; do not wait.

Security incidents rated S1 or S2 also use this template, with a restricted
circulation list and the SIRT running the meeting; the
[security incident response plan](../security/incident-response-plan.md) covers what
differs.

## Blameless means what it says

Our reviews are **blameless**. We assume that everyone involved acted reasonably on
the information, tools and time they had. When someone ran the wrong command, the
interesting question is never "who" but "what made that command look right at the
time, and what would have stopped it".

This is not about being nice. People who expect blame stop telling us the useful
details: the alert they silenced, the step they skipped, the dashboard they could not
find. Without those details we fix the wrong thing.

In practice:

| Instead of writing | Write |
|---|---|
| "Hester left the alert silenced." | "The alert was silenced for 24 hours during Tuesday's planned maintenance, and the silence outlived the maintenance. Nothing showed active silences on the dashboard." |
| "The on-call was slow to respond." | "The page was acknowledged after 14 minutes. The phone's notification settings delayed it; see action 3." |
| "Human error." | Describe the decision, what the person could see, and what would have changed it. |
| "Support should have escalated sooner." | "The first tickets described a sign-in loop; nothing in Harbour linked that symptom to an outage." |

Names appear in the timeline, because "Corinne scaled `card-auth` to 40 pods" is
clearer than "an engineer scaled a service". Names never appear as the subject of a
root cause.

The facilitator stops the meeting if the discussion turns to fault, and anyone may
ask them to. Managers do not use PIRs in performance conversations; that rule has been
agreed with People and with every head of department.

## Who does what

- **Author.** Named by the IC before the incident channel goes quiet; usually the
  operations lead or the IC. Writes the draft and owns the page until it is published.
- **Facilitator.** Runs the meeting. Someone from the IC rota who was **not** involved
  in the incident, so that they can ask naive questions.
- **Attendees.** Everyone who acted in the incident, the owning team lead, someone
  from Merchant Support for incidents merchants noticed, and anyone else who wants to
  learn. The meeting is open unless the incident involved security.
- **Approver.** The head of the owning department, who confirms that the actions are
  the right ones and are staffed. For payments incidents that is Nadia Ferreira.

## From resolution to publication

| Business day after resolution | What happens |
|---|---|
| 0 | IC resolves the incident in Klaxon and names the author |
| 1 | Author creates the page from the template and fills in the timeline from the Klaxon record and the channel |
| 2 to 3 | Author completes the draft; contributors correct the timeline in comments |
| 3 | Draft circulated in `#team-sre` and the owning team's channel, with the meeting invitation |
| 5 at the latest | The review meets |
| 7 | Page updated with what the meeting changed; actions filed as ENG tickets |
| 10 | Approver signs off; the page is marked final |

## Running the meeting

Fifty minutes, on a video call with the draft on screen.

1. **Five minutes.** The facilitator reminds everyone that the review is blameless and
   says what the meeting is for: to agree on what happened, and on the actions.
2. **Twenty minutes: the timeline.** The author walks through it. Attendees correct
   it. The facilitator asks, at each decision, "what did you know at this point?"
3. **Fifteen minutes: causes.** What made the incident possible, what made it worse,
   what made it shorter. Resist settling on one cause too early.
4. **Ten minutes: actions.** Agree each action, its owner and its due date. Anything
   without an owner by the end of the meeting is dropped, not left floating.

The author takes notes in the page itself. There are no separate minutes.

## The template

Copy this into a new page in the Incidents section, named
`report-YYYY-MM-DD-short-name`, where the date is the day the incident started in UTC
and the short name is the incident channel's without `#inc-`. The six most recent
reports, such as [the stale FX quotes report](report-2026-08-08-stale-fx.md) and
[the card authorisation latency report](report-2025-09-17-card-auth-latency.md), show
what good looks like.

```text
Title:      Incident report YYYY-MM-DD: <symptom, in merchants' words>
Severity:   SEV<n>                 Identifiers: <error codes, alert names>
IC:         <name>                 Author: <name>
Channel:    #inc-<short name>      Review held: <date>
Status:     draft | final

1. Summary
   Three to five sentences. What merchants experienced, for how long,
   what the cause was, how it was fixed.

2. Impact
   Who was affected and how much: merchants, sellers, buyers, payments,
   payouts, money. Duration from start of impact to end of impact.
   Anything still being put right.

3. Timeline (UTC)
   HH:MM  event
   Include: first impact, first signal, page, acknowledgement,
   declaration, each mitigation tried, mitigation, resolution.

4. Detection
   How we found out. How long between first impact and first signal.
   Whether the alert that fired was the one that should have.

5. Response
   What we tried, in order, and what each attempt taught us.
   Where the runbook helped and where it did not.

6. Root cause and contributing factors
   The technical chain of events. Then the conditions that let it
   happen, made it worse or made it last.

7. What went well
8. What was difficult
9. Where we got lucky

10. Actions
   | Action | Type | Owner | Ticket | Due |
   Types: prevent, detect, mitigate, process.

11. Appendix
   Graphs from Lantern, relevant log lines, links to tickets.
```

### The short form, for SEV3

A SEV3 PIR keeps sections 1, 3, 6 and 10 and drops the rest. The meeting, if there is
one, is 25 minutes with the people involved, and the IC may replace it with comments
on the draft. The five-day rule does not apply, but the actions are still `pir-action`
tickets. The [ledger reconciliation break of 2025-12-02](report-2025-12-02-ledger-break.md)
is a good example of how short a useful SEV3 review can be.

### A timeline that works

Good timelines are dull to read and easy to check. Each line carries one event and,
where it matters, its source:

```text
08:16  First PGW-5021 on a batch submitted at 08:06 (Lantern, stuck batch ratio)
08:46  PayoutQueueBacklog fires; Klaxon pages payments-primary as SEV2
08:49  Page acknowledged
08:55  SEV2 declared, #inc-payouts-delayed
09:06  DECISION: pause the scheduler; no deploy in the last 24 hours, so no rollback
```

Avoid lines such as "09:00 to 10:00 investigation continued". If nothing happened for
an hour, say what people were waiting for.

## Writing each section

**Summary.** Written last, read first. Someone who reads only this paragraph should
know what happened to merchants and whether it could happen again tomorrow.

**Impact.** Numbers, with their source. "About 41,800 authorisations declined (Lantern,
card-auth overview, 17:44 to 19:31 UTC)" is useful; "significant impact on payments" is
not. Say whether money moved wrongly and whether it has been put right. Never include a
PAN, a card's details, a merchant's name or a bank's name: use counts, internal
merchant identifiers if you must, and "the issuer", "the acquiring bank" or "our
settlement bank".

**Timeline.** UTC throughout, even for incidents around a UK or CET cut-off; give the
local time in brackets when it matters. One line per event. Copy from the Klaxon
record, then add what the record missed, such as the moment someone first noticed
something odd in a dashboard.

**Detection.** The section most often skipped, and among the most useful. If merchants
told us before our alerts did, say so plainly.

**Response.** Include the dead ends. A mitigation that did not work, and why we thought
it would, is often the best lesson in the document.

**Root cause and contributing factors.** Start with the technical chain, then widen.
There is rarely a single cause; the contributing factors are where most actions come
from. Be careful with "five whys": it tends to produce one tidy chain and miss the
branches.

**What went well, what was difficult, where we got lucky.** Three short lists. "Where
we got lucky" deserves real thought: luck is a control we do not own.

## Actions

Every action is an **ENG ticket labelled `pir-action`**. That label is how the
[PIR actions tracker](pir-actions-tracker.md) finds them, how the monthly Site
Reliability review counts overdue ones, and how quarterly planning sees them.

- File each ticket in the epic it belongs to when one fits; for example, an action on
  payout batching went into ENG-1 and the Beacon template action into ENG-13.
  Otherwise file it without an epic and the owning team schedules it.
- Each action has **one person** as owner, not a team, and a due date.
- Each action says which type it is: **prevent** (stops the cause), **detect** (finds
  it sooner), **mitigate** (makes it smaller or shorter) or **process** (changes how
  people work).
- Prefer three actions that will be done over ten that will not. "Be more careful"
  and "improve monitoring" are not actions.
- An action that turns out to be unnecessary is closed as Won't Do with a sentence
  explaining why, never left open.

Overdue `pir-action` tickets are listed in `#team-sre` on the first Monday of each
month, with their owners.

## Common problems with drafts

- The timeline is in UK time, or mixes UK time and UTC.
- The impact section describes the systems rather than merchants.
- The root cause is a person.
- The actions are all "prevent", and nothing would make the next one shorter.
- The draft waits for the meeting. It should be complete before the meeting; the
  meeting corrects it.

## Related pages

- [Production incident management](incident-management.md), for severities and roles
- [PIR actions tracker](pir-actions-tracker.md)
- [Incident roles quick reference](roles-quick-reference.md)
