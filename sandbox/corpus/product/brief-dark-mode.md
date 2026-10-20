---
title: "Product brief: dark mode for Merchant Hub"
---

*One-page brief. Product: Linnea Ashdown. Design: Priya Castellane and the Design System team (`#team-inkwell`). Engineering: Merchant Experience (`#team-merchant-hub`). Epic: ENG-26, planned for ENG Sprint 31 to ENG Sprint 40 (from 8 June 2026). Status: in progress, preview live since 15 September 2026. Last reviewed: 2026-10-14.*

## Why

Marketplace operations teams live in Merchant Hub. Many of them work evening and night shifts, because their buyers shop in the evening and their sellers ship in the morning. In the [May 2026 interviews](merchant-interviews-2026-05.md), five of fourteen merchants raised eye strain or asked for a dark theme without being prompted, and one operations manager described turning her screen brightness down to read the payouts list at night.

Dark mode was already on the ideas board, as "Dark mode for every Merchant Hub page", with more merchant requests linked to it as insights than any other Hub idea. The interviews moved it from "later" to a start in June.

## Who it is for

- Operations staff who spend long shifts in Hub, often in dim rooms.
- Users who rely on their operating system's dark setting for comfort or for an accessibility need.
- Not primarily: developers, who spend little time in Hub.

## What good looks like

A merchant who prefers a dark theme can use the pages they spend their day on without ever being flashed by a white page, and without losing any information that colour carried in the light theme. Status colours (succeeded, pending, failed) remain distinguishable, and every page still meets the [Accessibility checklist](../design/accessibility.md).

## Scope

**In scope for ENG-26**

- A theme switch in the profile menu: light, dark, or follow the device.
- The twenty most visited Hub pages, in order of traffic.
- Charts on the home page and the settlement reports.
- Inkwell components used by those pages, which the Design System team updates where needed.

**Out of scope**

- Emails and webhooks sent by `notify`.
- The public status page.
- Merchant-branded or custom colour themes.
- The pages beyond the top twenty. They remain on the ideas board under the same idea, and will be planned once we know how much of the remaining work is migrating old pages.

How the theme is implemented, and the rules for colours in both themes, belong to the design system and are on [Theming and dark mode](../design/theming.md).

## How we will know it worked

| Measure | Target |
|---|---|
| Accounts with at least one user in dark mode | 1,500 by the end of Q4 2026 |
| Issue reports from preview users | Fewer than 10 a week |
| Top twenty pages available in dark mode | 20 of 20 by the end of Q4 2026 |
| Satisfaction score from preview users | No lower than light-theme users |

## Plan

| Period | Milestone |
|---|---|
| June to July 2026 | Colour audit of Hub; pages that break the theming rules fixed first |
| August 2026 | Internal dogfooding by Merchant Support |
| 15 September 2026 | Preview opened to all merchants on six pages |
| October 2026 | Preview extended to 14 pages |
| Rest of Q4 2026 | General availability on the top twenty pages |

As of 20 October, 1,150 accounts have opted in and preview users report about six issues a week, mostly charts with low contrast between series.

## Risks

- **Older pages hard-code colours.** Some settings and reporting pages predate Inkwell. Every one of them needs migrating before it can go dark. This is why the scope stops at twenty pages.
- **Charts.** Chart colours were tuned for a white background. The Design System team is defining dark variants for the chart palette.
- **The end of ENG Sprint 40.** About six in ten of the epic's tickets are done; the rest continues into the quarter, as recorded on the [Q4 2026 OKRs](okrs-2026-q4.md).

## Open questions

- Should "follow the device" become the default for new users, or stay opt-in until general availability?
- Do we show a notice on pages that are not yet dark, or switch silently?
