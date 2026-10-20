---
title: "ENG Sprint 39 retrospective"
---

# ENG Sprint 39 retrospective

- **Sprint:** ENG Sprint 39, 2026-09-28 to 2026-10-11
- **Held:** Friday 2026-10-09, 14:00 to 15:15 UK time, Quill House floor 4 and video
- **Facilitator:** Léa (Payouts)
- **Notes:** Wren (Design System)
- **Attendees:** Noor, Felix and Joss (Merchant Experience); Sunniva and Tomasz (Data Platform); Hamza (Platform); Ciarán (Site Reliability); Wren and Priya (Design System); Imogen (Payments Core); Léa (Payouts); Bram (Platform) for the last twenty minutes

The epics in progress were the same three as in [sprint 38](retro-sprint-38.md): ENG-20 (Conveyor backfill tooling), ENG-26 (Dark mode for Merchant Hub) and ENG-30 (Date-based API versioning, ADR-023). Sprint 40 is the last sprint planned for all three, which shaped most of the conversation.

## Last sprint's actions

| Action | Status |
|---|---|
| Stop staging deploys running during the data refresh | Done. The refresh now announces its start and end in `#team-platform`, and staging deploys wait until it has finished. |
| Lend a Design System reviewer to Merchant Experience | Done. The median wait for a first review on ENG-26 changes fell to under half a day. |
| Split the ENG-20 concurrency story | Done. Both halves finished this sprint. |
| Version section of the `merchant-api` README | Half done; the examples are missing. Carried. |
| Ask Product how ENG-30's documentation ships | Done. Page by page, as each version change lands. |

## What the sprint delivered

- **ENG-30:** the changelog for merchants is now generated from the version registry, and the first dated version after the baseline is in staging with its transformer. The public reference pages for the header are drafted. See [ADR-023](../architecture/adr-023-api-versioning.md) for the decision itself.
- **ENG-26:** refunds, disputes and the developer pages joined the preview. The reports pages wait for Merchant Hub's charts to move to the Inkwell 3.4 palettes, which Priya expects in the first week of sprint 40.
- **ENG-20:** progress reporting for long backfills is in Conveyor, and Tomasz's team ran a real backfill for the finance marts with it, following [backfilling historical partitions](../data/backfills.md).

## Start, stop, continue

**Start**

- Writing each epic's finishing plan before sprint planning, not during it: what must ship, what can move to the backlog, and who decides. Sprint 40 will not stretch.
- Pairing a Merchant Experience engineer with Design System on the chart palettes, so that reports can switch theme the day the palettes land.

**Stop**

- Taking stories into a sprint without acceptance criteria. Two ENG-30 stories came back from review because nobody had agreed what "done" meant for older versions.
- Discussing design questions in review threads. Felix counted four ENG-26 changes with more than twenty comments each, most of them about design, not code. Take those to [design review](../design/design-review.md) first.

**Continue**

- Running the contract tests once per supported version on every `merchant-api` change.
- The ten-minute demo at the end of each sprint; Product came to this one and asked good questions.
- Rotating the facilitator. Next time: Ciarán.

## Looking at sprint 40

Sprint 40 starts on Monday 2026-10-12. Bram joined for this part. What the teams think will and will not make it:

| Epic | Likely to ship in sprint 40 | Likely to move to the backlog |
|---|---|---|
| ENG-20 | Remaining validation and the operator guide | A web view of backfill history |
| ENG-26 | Reports, once the palettes land; the switch in user settings | The email previews |
| ENG-30 | The public reference pages, and switching the flag on for merchants | A report in Merchant Hub of the version each integration uses |

Bram reminded everyone that the change freeze is not far behind, and that anything needing a risky production change should be planned against the [change freeze calendar 2026](../release/change-freeze-2026.md) now rather than discovered in November.

## Actions

| Action | Owner | Epic | Due |
|---|---|---|---|
| Write the finishing plan for each epic and share it before planning | Sunniva, Noor, Felix | ENG-20, ENG-26, ENG-30 | 2026-10-12 |
| Pair on chart palettes | Joss with Priya | ENG-26 | Sprint 40, first week |
| Add acceptance criteria to the remaining ENG-30 stories | Felix | ENG-30 | 2026-10-12 |
| Finish the `merchant-api` README examples | Felix | ENG-30 | Sprint 40 |
| Move remaining stories to the backlog with a note on why | Each epic owner | All three | End of sprint 40 |
