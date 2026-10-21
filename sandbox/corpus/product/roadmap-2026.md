---
title: "Product roadmap 2026"
---

| | |
|---|---|
| Owner | Ama Rowntree, head of product |
| Contributors | Oskar Ngata (payouts), Linnea Ashdown (Merchant Hub and Merchant API), Nadia Ferreira, Bram Oyelaran, Priya Castellane |
| Last reviewed | 2026-10-16 |
| Status | Living document, updated after every quarterly planning round |

> [!NOTE]
> Quarters on this page are calendar quarters. Finance plans on the fiscal year that starts on 1 April, so "Q3 2026" here is the second quarter of fiscal year 2026/27. The [quarterly planning process](quarterly-planning.md) explains how the two line up and how this page gets updated.

## Where we are in October 2026

We set four bets for merchants at the start of the year. Three of them have landed: marketplaces in Europe can settle euros in euros since March, merchants can issue refunds themselves since July, and chargeback evidence has been submitted for them automatically since the end of August. The fourth, a Merchant Hub that is pleasant to use all day, is half done: the accessibility work closed in April and dark mode is in preview.

Two epics reach their last planned sprint in ENG Sprint 40: ENG-26 (dark mode for Merchant Hub) and ENG-30 (date-based API versioning). Neither will be finished by the end of that sprint; both carry on for the rest of the quarter, as the [Q4 2026 OKRs](okrs-2026-q4.md) describe. The one open strategic question is instant payouts, where we owe the leadership team a go or no-go recommendation by the end of November.

## What this page is, and what it is not

This roadmap says what we intend to deliver to merchants in 2026, in which quarter, and why. It is the page to send to anyone who asks "what is product working on?".

It is not a list of dates. Delivery dates live on the epics in the ENG project, where each epic carries its sprint span. Quarterly targets live on the OKR pages, and raw ideas live on the ideas board (see [Product discovery and the ideas board](discovery-process.md)). If this page disagrees with an epic in ENG, the epic is right and this page is stale: tell Ama.

## Themes for 2026

We chose four themes in the December 2025 planning round, from three inputs: what merchants told us in support tickets and account reviews, what we lost deals over, and what our own operations teams spent the most time on.

### 1. Europe as a home market

Before this year, a French marketplace taking euros from buyers and paying euros to sellers saw its money converted to sterling and back. That cost them twice and confused their finance teams. Settling euros in euros was the most requested change in our 2025 account reviews with European merchants.

- Multi-currency settlement (ENG-4), shipped in March. See the [brief](brief-multi-currency.md).
- The fx-quote rewrite (ENG-5), shipped in May, so that conversions that do still happen use fresh rates.
- Merchant Hub in French, shipped in May.

**How we measure it:** the share of euro card volume from European merchants that settles in euros, and the number of support tickets about conversion.

### 2. Merchants serve themselves

In 2025 about a third of all merchant support tickets asked us to do something a merchant could have done alone with the right tool, refunds above all. Every one of those tickets is slow for the merchant and expensive for us.

- Self-serve refunds API (ENG-6), generally available since 28 July. See the [brief](brief-self-serve-refunds.md).
- Chargeback evidence automation (ENG-28), live since the end of August.
- Team roles in Merchant Hub, shipped in February, so that a marketplace's finance staff can work without an administrator's login.

**How we measure it:** the share of refunds issued without a support ticket, and refund-related tickets per week.

### 3. A dashboard people are happy to work in

Merchant Hub is where marketplace operations staff spend their shifts. Our satisfaction survey scored it 7.1 out of 10 at the end of 2025, with accessibility and eye strain on late shifts among the most frequent complaints.

- Accessibility remediation (ENG-25), closed in April.
- Dark mode for Merchant Hub (ENG-26), in preview since 15 September. See the [brief](brief-dark-mode.md).
- Saved views on the payments and payouts lists, shipped in June.

**How we measure it:** the quarterly satisfaction score, open high-severity accessibility issues, and dark mode adoption.

### 4. Change without fear

Merchants integrate with us once and expect it to keep working. Every breaking change to the Merchant API in 2025 cost us escalations, and several merchants told us they had stopped upgrading at all.

- Event log migration (ENG-29), completed in April, which moved the events behind merchant webhooks to the replicated log described in [ADR-019](../architecture/adr-019-replicated-event-log.md).
- Beacon status page automation (ENG-13), completed in August, so merchants hear about incidents sooner and more consistently.
- Date-based API versioning (ENG-30), in progress, following [ADR-023](../architecture/adr-023-api-versioning.md).

**How we measure it:** merchant-reported breaking changes (target: none), and the share of API keys pinned to a dated version.

### Foundations we depend on

These epics are owned by platform, security, data and risk teams. They are on this page because merchant-facing work depends on them, not because product owns them.

| Epic | What it unlocks for product |
|---|---|
| ENG-9 Kubernetes 1.31 upgrade | Closed in January; removed a blocker on new node pools for Merchant Hub |
| ENG-22 Shadow mode and promotion gates | Closed at the end of January; safer fraud model changes, fewer surprise declines |
| ENG-15 Access review tooling | Closed in March; answers a recurring question in merchants' security questionnaires |
| ENG-10 Zero-downtime database migrations | Closed in June; Merchant Experience can ship schema changes in normal deploy windows |
| ENG-19 Warehouse erasure automation | Closed in early July; erasure requests from merchants' sellers are handled faster |
| ENG-16 Hardware security keys for admins | Closed in August; another security questionnaire answer |
| ENG-20 Conveyor backfill tooling | In progress; faster repair of merchant reporting data when a pipeline fails |

## Timeline by quarter

| Quarter | ENG sprints | Merchant-facing outcomes | Epics |
|---|---|---|---|
| Q1 2026 | 20 to 25 (5 January to 29 March) | Euro settlement pilot, then general availability; team roles in Hub | ENG-4 |
| Q2 2026 | 26 to 32 (30 March to 5 July) | Accessible Hub; webhooks on the new event log; fresher FX quotes; Hub in French; refunds pilot | ENG-25, ENG-29, ENG-5, ENG-6 (started) |
| Q3 2026 | 33 to 38 (6 July to 27 September) | Self-serve refunds; automatic chargeback evidence; incident banners; dark mode preview; dated API versions for new keys | ENG-6, ENG-28, ENG-13, ENG-26 (preview), ENG-30 (started) |
| Q4 2026 | 39 onwards (from 28 September) | Dark mode on the most used pages; every API key on a dated version; instant payouts decision | ENG-26, ENG-30 |

### Q1 2026: euros, settled in euros

Multi-currency settlement (ENG-4) ran from ENG Sprint 15 to ENG Sprint 24. We opened a pilot to eight French marketplaces in January and made euro settlement through SEPA generally available on 9 March. The settlement windows for each currency are on [Settlement windows and cut-off times](../payments/settlement-cutoffs.md); we do not repeat them here because they change more often than this page.

Team roles shipped in February. ENG-12, the SLO dashboards in Lantern, closed at the turn of the year and gave us the error budget view we now use in planning.

### Q2 2026: a sturdier, more accessible Hub

Accessibility remediation (ENG-25) closed in April, after nine sprints of fixes across Merchant Hub: keyboard navigation, focus states, contrast and labels. The event log migration (ENG-29) also closed in April; merchants saw no change, which was the point.

The fx-quote rewrite (ENG-5) closed in May. Merchant Hub in French followed the same month, driven by the Paris support team's data on French-speaking merchants. We ran fourteen merchant interviews in May (see [Merchant interviews May 2026](merchant-interviews-2026-05.md)); they confirmed the refunds work and moved dark mode forward by a quarter.

The self-serve refunds API started in ENG Sprint 26 and went to a pilot of twenty merchants in June.

### Q3 2026: merchants serve themselves

Self-serve refunds (ENG-6, sprints 26 to 34) became generally available on 28 July. Chargeback evidence automation (ENG-28, sprints 27 to 36) went live for all merchants at the end of August. Beacon status page automation (ENG-13, sprints 30 to 36) means the status page and Merchant Hub's incident banner now carry the same message.

Dark mode for Merchant Hub (ENG-26) started in ENG Sprint 31 and opened as a preview on 15 September. Date-based API versioning (ENG-30) started in ENG Sprint 34; new API keys have been pinned to a dated version since 21 September.

The quarter scored 0.77 overall. The [Q3 2026 OKRs](okrs-2026-q3.md) have the detail, including the three committed key results we missed.

### Q4 2026: finish what is in flight

Q4 is deliberately light on new starts. ENG-26 and ENG-30 both reach ENG Sprint 40 with roughly six in ten of their tickets done, and we would rather finish them well than open three new epics.

- **Dark mode:** general availability on the twenty most visited Hub pages by the end of the quarter. The remaining pages are tracked as an idea on the ideas board.
- **Dated API versions:** every existing API key pinned to a dated version, with an upgrade assistant in Merchant Hub.
- **Refunds adoption:** from 52% to 70% of refunds issued without a ticket.
- **Instant payouts:** a decision, not a build. See the [brief](brief-instant-payouts.md).

Launches avoid the two change freezes at the end of November and over the year end; the dates are on the [change freeze calendar](../release/change-freeze-2026.md). In practice, anything merchant-facing that is not live by the middle of November waits until January.

## Now, next, later

| Horizon | Item | Status |
|---|---|---|
| Now | Dark mode for Merchant Hub (ENG-26) | In delivery, preview live |
| Now | Date-based API versioning (ENG-30) | In delivery, new keys pinned |
| Now | Self-serve refunds adoption | Shipped; adoption work with support |
| Next | Instant payouts pilot | Depends on the November decision |
| Next | Dark mode for the remaining Hub pages | Idea on the ideas board |
| Next | Bulk refunds from an uploaded file | Asked for by six interviewed merchants |
| Next | Settlement report redesign | Discovery started in September |
| Later | Settlement in further currencies | No currency has enough demand yet |
| Later | Merchant-configurable payout schedules per seller | Exploring |

"Next" means a candidate for the first half of 2027, not a commitment. Items move from "next" to "now" only through quarterly planning.

## What we decided not to do in 2026

Saying no is part of the roadmap. These came up often enough that they deserve a recorded answer.

- **A GraphQL Merchant API.** Rejected in [ADR-016](../architecture/adr-016-no-graphql.md); date-based versioning addresses the real complaint, which was breaking changes.
- **A native mobile app for Merchant Hub.** Usage on phones is under 4% of sessions, and those sessions are mostly people checking a single payout. We made the payout pages work well at phone width instead.
- **Settlement in dollars.** Three of the fourteen merchants we interviewed in May mentioned it, none as a priority.
- **Merchant-branded themes for Hub.** Dark mode solves the problem merchants described; arbitrary colours would undo the accessibility work.

## Dependencies and risks

| Risk | Effect if it happens | Mitigation | Owner |
|---|---|---|---|
| Older Hub pages predate Inkwell and do not follow the theming rules | Dark mode cannot reach them this year | Pages are migrated in order of traffic; the rest wait for the idea on the ideas board. How theming works is on [Theming and dark mode](../design/theming.md) | Priya Castellane |
| Merchants' developers do not pin their existing keys | ENG-30 cannot close | Upgrade assistant in Hub, email campaign, support macros | Linnea Ashdown |
| Instant payouts need us to pay before card money settles | Working capital cost we have not budgeted | Finance model before the decision | Idris Kallenberg |
| Payments Core capacity is consumed by incident follow-up | Refunds and instant payouts work slips | 20% of capacity reserved for reliability in planning | Nadia Ferreira |
| Change freezes shorten Q4 | Launches bunch up in early November | Launch readiness reviewed in sprint 40 | Ama Rowntree |

## How to propose a change to this roadmap

Raise it on the ideas board with the evidence you have, and mention it in `#team-product`. Ama reviews roadmap changes every two weeks with the product managers. Changes that move an epic between quarters also need the engineering head who owns the team, because they move capacity.

## Change log

| Date | Change |
|---|---|
| 2026-01-12 | First published for 2026, with the four themes |
| 2026-03-16 | Euro settlement marked as shipped; Q2 plan added |
| 2026-05-29 | Dark mode brought forward to start in ENG Sprint 31, after the May merchant interviews |
| 2026-06-29 | Q3 plan added; refunds pilot results noted |
| 2026-09-28 | Q4 plan added; instant payouts decision added as a Q4 objective |
| 2026-10-16 | ENG-26 and ENG-30 status updated after the sprint 40 review |

## Related pages

- [Quarterly planning process](quarterly-planning.md)
- [OKRs Q3 2026](okrs-2026-q3.md) and [OKRs Q4 2026](okrs-2026-q4.md)
- [Merchant Hub release notes 2026](merchant-hub-release-notes-2026.md), for what actually shipped each month
- [Launch checklist](launch-checklist.md)
