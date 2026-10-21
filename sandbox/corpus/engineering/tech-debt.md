---
title: "Managing technical debt"
---

# Managing technical debt

Owner: Bram Oyelaran, head of platform engineering. Last reviewed: 2026-08-12.

Technical debt is any part of our code or platform that makes the next change slower or riskier than it needs to be. Some of it we take on deliberately, to ship sooner; the rest accumulates while nobody is looking. Both kinds are fine as long as they are visible, and paid down before they turn into an incident.

## Recording debt

Debt worth remembering gets a ticket in ENG with the label `tech-debt`. Its description answers four questions:

1. What is the debt? Name the code, the service or the process.
2. What does it cost today? Slower changes, pages to on-call, manual toil, risk.
3. Roughly what would it take to pay it down?
4. What makes it worse over time, if anything?

A `TODO` in the code is not a record. If it matters, it has a ticket, and the comment says where to find it:

```python
# TODO(tech-debt): replace the per-currency branches once settlement
# configuration moves into the database; ticket in the Payouts debt register.
```

## Scoring

Each team scores its open debt once a quarter, at its planning session, on two scales from 1 to 3:

| | Effort 1: days | Effort 2: a sprint | Effort 3: an epic |
|---|---|---|---|
| **Impact 3:** incidents, risk to money | Next sprint | This quarter | Propose an epic |
| **Impact 2:** slows most changes | When nearby | This quarter | Next quarter |
| **Impact 1:** an annoyance | When nearby | Leave it | Close as Won't Do |

Closing a ticket as Won't Do is a decision, not a failure; it says the team has looked and chosen to live with it.

## Paying it down

- **A fifth of the sprint.** Each team keeps about 20% of every sprint for debt, tooling and maintenance. It is a budget, not a quota: a team in the middle of a launch may spend less for a sprint or two, and make it up afterwards.
- **Leave it better, separately.** Improve the code you touch, but in a change of its own; a refactor buried inside a feature is hard to review (see the [code review guidelines](code-review.md)).
- **Epics for the big ones.** Debt that needs more than a sprint becomes an epic with its own goal. Recent examples: ENG-10, zero-downtime database migrations, which ended the evening maintenance windows for schema changes; ENG-8, Switchboard kill switches, which replaced hand-edited configuration during incidents; and ENG-29, the event log migration under [ADR-019](../architecture/adr-019-replicated-event-log.md).

## The quarterly look across teams

Once a quarter, the backend and frontend guilds each look at the oldest and highest-scored `tech-debt` tickets across all teams. The aim is to spot debt that crosses team boundaries, which no single team will ever prioritise, and to close tickets that no longer matter. The filter in Jira:

```text
project = ENG AND labels = tech-debt AND statusCategory != Done ORDER BY created ASC
```

## Signs that debt has fallen due

- The same area appears in two PIRs in one quarter; the [PIR actions tracker](../incidents/pir-actions-tracker.md) makes this easy to see.
- A routine change needs a specialist to review it.
- New engineers are told "don't touch that".
- A lint suppression, allowed under the [coding standards](coding-standards.md), has been copied into a third file.
