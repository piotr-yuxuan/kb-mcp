---
title: "Quarterly planning process"
---

**Process owner:** Ama Rowntree, head of product. **Approver:** Ottilie Marsh, chief technology officer. **Last reviewed:** 2026-09-02, before the Q4 2026 round.

Every quarter, product and engineering agree what each team will deliver, write it down as OKRs, and turn it into epics in the ENG project. This page describes how that works, step by step, so that a new product manager or engineering lead can run their part without having watched a round first.

If you only need the output, read the [Product roadmap 2026](roadmap-2026.md) and the current quarter's OKR page, such as [OKRs Q4 2026](okrs-2026-q4.md).

## Principles

1. **Outcomes, not output.** An objective describes a change for merchants or for Quillmoor. Epics are how we get there, and they can change during the quarter; the objective should not.
2. **Plan to capacity, not to wishes.** We count capacity in team-sprints before we discuss priorities, so that the discussion is about what to drop rather than what to squeeze in.
3. **Reliability is not optional.** A fixed share of every team's capacity is reserved for reliability, incident follow-up and technical debt. It is not up for negotiation in planning week.
4. **One owner per key result.** A key result with two owners has none.
5. **Everything is published.** Drafts, scores and decisions are on the wiki for the whole company to read.

## Quarters, sprints and the fiscal year

Product plans in **calendar quarters**: Q1 is January to March, Q2 April to June, Q3 July to September, Q4 October to December. Engineering works in two-week ENG sprints that start on Mondays. The two do not line up exactly, so we use one rule: **a quarter's first sprint is the ENG sprint whose Monday falls nearest to the quarter's first day.**

| Quarter | ENG sprints | Dates |
|---|---|---|
| Q1 2026 | 20 to 25 | 5 January to 29 March |
| Q2 2026 | 26 to 32 | 30 March to 5 July |
| Q3 2026 | 33 to 38 | 6 July to 27 September |
| Q4 2026 | 39 onwards | from 28 September |

Most quarters hold six sprints; Q2 2026 held seven. Planning assumes six and treats a seventh as buffer.

Finance runs on the fiscal year from 1 April to 31 March, so our Q2 is the first fiscal quarter and our Q1 is the last. The annual budget, which sets headcount and therefore capacity, comes out of the [annual budget cycle](../finance/budget-cycle.md). The Q2 planning round is the first one that uses a new year's budget, and it is the round where headcount surprises show up: product managers should ask their finance partner for the approved headcount before drafting.

## The calendar

Each round runs over six weeks before the quarter's first sprint, which we call week 0.

| Week | Step | Who | Output |
|---|---|---|---|
| -6 | Gather inputs | Product managers | Inputs document per area |
| -5 | Insights review | Product, support, engineering heads | Ranked problems, not solutions |
| -4 | Draft objectives | Product managers with engineering leads | Draft OKRs |
| -3 | Capacity | Engineering heads | Team-sprints available per team |
| -2 | Planning week | Everyone who leads a team | Epics in ENG, dependencies agreed |
| -1 | Leadership review and publication | Leadership team | Published OKR page, roadmap updated |
| 0 | Kick-off | Teams | First sprint planning on the new epics |
| +6 or so | Mid-quarter check-in | Product managers | Confidence per key result |
| End, plus 2 | Scoring | Key result owners | Scores and lessons on the OKR page |

### Example: the Q4 2026 round

| Step | Date |
|---|---|
| Inputs due | 17 August 2026 |
| Insights review | 24 August |
| Draft OKRs | 31 August |
| Capacity figures | 7 September |
| Planning week | 14 to 18 September (ENG Sprint 38) |
| Leadership review | 22 September |
| OKRs published | 25 September |
| Kick-off | 28 September, with ENG Sprint 39 |
| Q3 scores published | 9 October |

## Step 1: gather inputs

Each product manager writes a short inputs document for their area. It is a list of problems with evidence, not a list of features. Typical sources:

- **The ideas board**, the Product Discovery project `PRB`. Look at ideas with fresh insights and at anything that has moved to "ready for delivery". The board is explained on [Product discovery and the ideas board](discovery-process.md).
- **Merchant research**: interviews, such as the [May 2026 round](merchant-interviews-2026-05.md), account reviews with the commercial team, and the quarterly satisfaction survey.
- **Support data from Harbour**: ticket volumes by category, and which categories grew. Femi Haldane's team sends a summary by week -6.
- **Incidents**: incident reports from the last quarter and open actions on the [PIR actions tracker](../incidents/pir-actions-tracker.md).
- **Reliability**: error budget burn per service from the SLO dashboards in Lantern.
- **Obligations**: security, privacy and regulatory work with a deadline, from Callum Ibe, Beatrix Sallow and Saoirse Lindqvist.
- **Technical debt** that teams have flagged, following [Managing technical debt](../engineering/tech-debt.md).

## Step 2: insights review

A two-hour session in week -5. Each product manager presents their top five problems in five minutes each. The room ranks them on merchant impact, cost of delay and confidence in the evidence. The output is a ranked list of problems. Proposals for solutions are welcome but are not ranked.

## Step 3: draft the OKRs

Product managers draft objectives and key results with the engineering leads of the teams who will do the work.

- 3 to 5 objectives per area; 2 to 4 key results per objective.
- Each key result is measurable from data we already collect, or the first key result is to start collecting it.
- Mark each key result **committed** (we expect to hit it fully) or **aspirational** (0.7 would be a good result).
- Each key result names one owner.

```text
Objective: [a change for merchants or for Quillmoor, in plain words]

Key result 1: [metric] from [baseline] to [target] by [end of quarter]
  committed, owner: [name]
Key result 2: [deliverable] live for [who] ([epic key in ENG])
  aspirational, owner: [name]

Why now: [one or two sentences of evidence]
Depends on: [teams, epics, decisions]
```

## Step 4: capacity

Engineering heads (Nadia Ferreira for payments, Bram Oyelaran for platform, and the leads of the other teams) give each team's capacity in team-sprints for the quarter. A team with six sprints in the quarter has six team-sprints, less known absences: leave booked in Haven, on-call weeks for teams with a heavy rota, and parental leave. Capacity is then split:

| Share | Use |
|---|---|
| 20% | Reliability, PIR actions and technical debt, chosen by the team |
| 10% | Unplanned work and support escalations |
| 70% | Planned epics from the OKRs |

If the planned epics need more than 70%, something comes out in planning week. We do not raise the percentage.

## Step 5: planning week

Planning week runs in the second-to-last sprint of the quarter.

- **Monday:** dependency mapping. Each team lists what it needs from others; the product managers keep a single dependency table.
- **Tuesday and Wednesday:** team sessions. Each committed key result becomes one or more epics in ENG, with a label (`payments`, `platform`, `sre`, `security`, `data`, `risk-ml`, `design-system`, `merchant-hub`, `support` or `architecture`), an owner, and a planned sprint span such as "ENG Sprint 33 to 38".
- **Thursday:** cross-team review of the dependency table. Conflicts go to the engineering heads, then to Ottilie Marsh.
- **Friday:** draft OKR page and epic list sent for leadership review.

An epic may span quarters. ENG-6, the self-serve refunds API, ran from ENG Sprint 26 to ENG Sprint 34, across Q2 and Q3, and was reviewed in both rounds. A long epic is reviewed in every round it touches: ENG-26, dark mode for Merchant Hub, started in ENG Sprint 31 and has now been through three.

## Step 6: leadership review and publication

Hollis Varga, Ottilie Marsh, Idris Kallenberg and Ama Rowntree review the drafts in a ninety-minute session. They check that:

- the objectives together reflect the company's priorities for the year;
- nothing obligatory has been left out (security, privacy, regulatory work);
- the plan fits capacity, including the reserved 20%;
- the quarter avoids launching into a change freeze (see the [change freeze calendar](../release/change-freeze-2026.md)).

After the review, Ama publishes the OKR page for the quarter, updates the [roadmap](roadmap-2026.md), and posts both in `#team-product` and the engineering all-hands channel.

## Step 7: kick-off and the quarter itself

Teams pick up their new epics in the first sprint planning of the quarter. Product managers attend sprint reviews for their areas.

### Mid-quarter check-in

Around the sixth week, each key result owner gives a confidence level: **on track**, **at risk** or **off track**, with one sentence of explanation. At-risk and off-track key results get a short conversation with the engineering head. Allowed outcomes:

- re-scope the key result and record the change on the OKR page;
- drop it, and record why;
- add a new key result only by dropping or shrinking another of the same size.

### Epics that overrun

An epic that reaches the end of its planned sprint span unfinished is not quietly extended. The owning team decides, at the next sprint review, whether to extend it, split the remainder into a new epic, or stop. The decision is noted on the epic in ENG and on the OKR page.

## Step 8: scoring and lessons

Within the first two weeks of the next quarter, each owner scores their key results from 0.0 to 1.0:

| Score | Meaning |
|---|---|
| 1.0 | Fully achieved |
| 0.7 | A good result for an aspirational key result |
| 0.4 | Real progress, well short |
| 0.0 | No progress |

A committed key result below 1.0 gets a sentence on what happened. The objective's score is the average of its key results, and the quarter's score is the average of its objectives. Scores are published on the quarter's OKR page, as on [OKRs Q3 2026](okrs-2026-q3.md).

Scores measure the plan, not the people. They are not used in [performance reviews](../people/performance-reviews.md).

## Roles

| Role | Responsibilities |
|---|---|
| Head of product | Runs the process, chairs the insights review, publishes the OKRs and the roadmap |
| Product managers | Inputs, drafts, dependency table, mid-quarter check-ins, scoring |
| Engineering heads | Capacity figures, epics in ENG, resolving conflicts between teams |
| Team leads | Sprint spans, technical risks, the use of the reserved 20% |
| Chief technology officer | Arbitrates conflicts that the engineering heads cannot settle; approves the plan |
| Leadership team | Final review of the plan |
| Head of customer support | Support data for inputs; readiness for launches |

## Frequently asked questions

**Can I add work in the middle of a quarter?** Yes, by trading: something of the same size comes out, and the OKR page records it. Incidents and security fixes are exempt; they use the reserved and unplanned capacity first.

**Where do ideas for internal tools go?** On the ideas board, like product ideas. Several current ideas are about internal processes rather than merchant features; the owning team decides when to plan them.

**What if a key result depends on another team that did not plan for it?** That is what planning week's dependency table is for. If it was missed, raise it with both engineering heads straight away rather than waiting for the check-in.

**Do platform and data teams write OKRs too?** Yes, in the same format and on the same calendar. They publish on their own section pages; product links to the ones that merchant-facing work depends on.

**Who decides between two teams' priorities?** The engineering heads first, then the chief technology officer. Product gives the merchant impact; it does not overrule engineering on capacity.

## Related pages

- [Product roadmap 2026](roadmap-2026.md)
- [Product discovery and the ideas board](discovery-process.md)
- [OKRs Q3 2026](okrs-2026-q3.md) and [OKRs Q4 2026](okrs-2026-q4.md)
- [Launch checklist](launch-checklist.md)
