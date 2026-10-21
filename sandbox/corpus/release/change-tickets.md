---
title: "Raising a change ticket"
---

# Raising a change ticket

Owner: Platform (release engineering). Last reviewed: 2026-09-15.

The **Change Register** is where risky production changes are planned, approved and recorded. Each ticket is keyed `CHG-` followed by a number, for example `CHG-2291`. Shipwright reads the Register: for a deploy that needs a ticket, it refuses to start the canary unless the ticket you pass with `--change` is approved and names the service.

## When you need one

- A high-risk change, as listed on [How code reaches production](deployment-pipeline.md).
- A down migration in production ([Database migrations](database-migrations.md)).
- Anything during a change freeze ([Change freeze calendar 2026](change-freeze-2026.md)).

If you are unsure, ask in `#team-platform`. An unnecessary ticket costs ten minutes; a missing one can cost an evening.

## What to write

| Field | What goes in it |
|---|---|
| Summary | One line a stranger would understand |
| Services | Shipwright service names, exactly as in `shipwright.yaml` |
| Type | Standard, Freeze exception or Emergency |
| Plan | The steps in order, with the commands you will run |
| Verification | How you will know it worked: dashboards, queries, checks |
| Back-out plan | What you will do if it does not work. "Roll forward" is a valid answer if you say how |
| Window | Date and time, inside the deploy windows unless it is an emergency |
| People | Who runs it, who watches it, who approves it |
| Links | Pull requests, the ENG epic, runbooks |

Write the plan so that someone else could carry it out if you were ill on the day. That is the test reviewers apply.

## Approval

| Type | Approved by |
|---|---|
| Standard | The owning team's lead and one platform reviewer; for anything touching a ledger schema, a Ledger reviewer as well |
| Freeze exception | The head of platform engineering |
| Emergency, outside a freeze | The IC of the open incident, in Shipwright; complete the ticket within one working day afterwards |
| Emergency, during a freeze | The head of platform engineering, as well as the IC |
| Down migration in production | The head of platform engineering |

## Life of a ticket

Draft, Submitted, Approved, Scheduled, Implemented, Closed. A ticket can also end Rejected or Cancelled. Shipwright accepts a ticket in the Approved or Scheduled state, and moves it to Implemented when the release that cites it reaches 100%. Close it yourself once verification is done, with a sentence on how it went.

```bash
shipwright deploy ledger --release 9.2.0 --env production --change CHG-2291
```

## The ticket everyone copies: CHG-2291

`CHG-2291` is the change ticket for the 2026 ledger schema migration, which partitioned the ledger's journal lines table by month. Kwabena Stroud, the Ledger team lead, raised it on 2026-02-23. It was approved on 2026-03-04 by Bram Oyelaran and Nadia Ferreira, head of payments engineering.

It is a good example because the plan follows expand then contract in two dated halves:

1. **Expand, 2026-03-10.** Create the partitioned table, start writing journal lines to both tables behind `sb.ledger.dual-write-journal-lines`, and copy history across in batches.
2. **Contract, 2026-05-12.** Move reads to the partitioned table behind `sb.ledger.partitioned-journal-reads`, then retire the old table in a later release.

Verification compared row counts and journal totals between the two tables every hour during the dual writes. The back-out plan for each half said what would be switched off and by whom. The ticket was closed on 2026-05-19.

Before raising a ticket for a large migration, read `CHG-2291` in the Change Register. It will save you a review round.
