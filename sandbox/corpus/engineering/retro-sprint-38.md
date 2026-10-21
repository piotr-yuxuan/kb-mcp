---
title: "ENG Sprint 38 retrospective"
---

# ENG Sprint 38 retrospective

ENG Sprint 38 ran from 2026-09-14 to 2026-09-27. We held the retrospective on Friday 2026-09-25, 14:00 to 15:00 UK time, on video.

- **Facilitator:** Imogen (Payments Core)
- **Notes:** Joss (Merchant Experience)
- **Attendees:** Noor, Felix and Joss (Merchant Experience); Sunniva (Data Platform); Hamza (Platform); Ciarán (Site Reliability); Wren (Design System); Léa (Payouts); Amara (Ledger); Imogen (Payments Core)

## Epics in progress

| Epic | Owner team | State at the end of the sprint |
|---|---|---|
| ENG-20 Conveyor backfill tooling | Data Platform | Dry runs in use; concurrency story carried over |
| ENG-26 Dark mode for Merchant Hub | Merchant Experience | Preview live for opted-in merchants on 15 September, on six pages |
| ENG-30 Date-based API versioning (ADR-023) | Merchant Experience | Version handling in staging behind a flag |

Format this time: each person wrote cards under "went well", "went badly" and "puzzles" for five minutes, then we grouped them and voted with three dots each.

## Went well

- **ENG-30 reached staging.** Handling of the `Quillmoor-Version` header is running in staging behind its flag, the contract tests run once per supported version, and `api_version` is now logged on every request, as the [September backend guild](guild-backend-2026-09.md) asked.
- **ENG-26 pages passed design review first time.** The settings and payouts pages went through design review in the dark theme with no contrast findings, which Wren put down to the token clean-up done in the summer.
- **ENG-20 dry runs are useful already.** Data Platform used the dry run, which lists the partitions a backfill would touch, on two real requests from Finance before running them.
- **CI is calmer.** The Kafka readiness fix cut integration failures sharply, and three teams brought quarantined tests back.

## Went badly

- **Staging was unusable on Tuesday morning** (6 votes). A `merchant-api` deploy to staging ran its migration while the `staging-eu` data refresh was still loading, and the refresh then failed half-way. ENG-30 testing lost half a day, and so did Payouts.
- **Reviews waited on Merchant Experience** (5 votes). Three ENG-26 changes waited more than one business day for a first review, because two of the team's three regular reviewers were on annual leave. The [code review guidelines](code-review.md) target was missed, and dark mode work stalled behind it.
- **An ENG-20 story carried over again** (3 votes). The story to limit how many backfills run at once across the cluster carried over for the second sprint running. It was estimated as small, and it is not.

## Puzzles

- How do we test every ENG-26 page in both themes without doubling the visual tests? Wren pointed to [theming and dark mode](../design/theming.md), which already answers part of it; Felix will bring the rest to the frontend guild.
- Should ENG-30's documentation wait for the last stories, or ship page by page? No answer yet; Noor will ask Product.

## Actions

| Action | Owner | Epic | Due |
|---|---|---|---|
| Find out why a staging deploy could run during the refresh, and stop it happening again | Hamza | | Sprint 39 |
| Lend a Design System reviewer to Merchant Experience's rota until ENG-26 closes | Wren and Noor | ENG-26 | From 2026-09-28 |
| Split the ENG-20 concurrency story before planning | Sunniva | ENG-20 | 2026-09-28 |
| Write the version section of the `merchant-api` README | Felix | ENG-30 | Sprint 39 |
| Ask Product how ENG-30's documentation should ship | Noor | ENG-30 | Sprint 39 |

Confidence in sprint 39, by a show of fingers: 3.6 out of 5.
