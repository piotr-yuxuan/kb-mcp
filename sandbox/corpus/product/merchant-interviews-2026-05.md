---
title: "Merchant interviews May 2026"
---

Research notes. Interviewers: Oskar Ngata, Linnea Ashdown and Ama Rowntree, with Inès Moreau for the four interviews held in French. Interviews ran from 4 to 22 May 2026. Synthesis written by Linnea Ashdown; last reviewed 2026-06-05.

## Why we ran this round

We had three bets in flight or about to start (self-serve refunds, dark mode, dated API versions) and one we had not decided to pursue (instant payouts). We wanted to hear, unprompted, what slowed marketplaces down, before asking about any of them.

## Method

- Fourteen merchants, chosen to mix size, country and type of marketplace, and to include five who had moved to euro settlement since March.
- 45-minute video calls; two interviewers each time, one asking and one taking notes.
- First 20 minutes open: "walk us through last week in Merchant Hub". Then specific questions on refunds, payouts, reports and the API.
- Participants agreed to recording. Recordings are kept as the [data retention schedule](../data/retention-schedule.md) requires; the notes are anonymised and attached as insights to the relevant ideas on the ideas board.

## Participants

| Id | Marketplace | Country | Size | Who joined |
|---|---|---|---|---|
| M01 | Fashion resale | UK | Large | Head of operations, finance manager |
| M02 | Handmade crafts | France | Medium | Founder, developer |
| M03 | Event ticket resale | UK | Large | Payments lead, developer |
| M04 | Second-hand furniture | Netherlands | Medium | Operations manager |
| M05 | Home services | UK | Medium | Finance director |
| M06 | Second-hand books | France | Small | Founder |
| M07 | Car parts | UK | Medium | Operations lead, developer |
| M08 | Food producers | Belgium | Small | Operations lead |
| M09 | Short-stay rentals | UK | Large | Head of finance, developer |
| M10 | Fashion resale | France | Large | Head of operations, technical lead |
| M11 | Private tutoring | UK | Small | Founder |
| M12 | Sports equipment rental | UK | Medium | Operations manager |
| M13 | Art prints | France | Medium | Finance manager, developer |
| M14 | Trade packaging supplies | UK | Medium | Finance manager, developer |

M02, M04, M08, M10 and M13 settle in euros.

## Headline findings

1. **Refunds through support are the biggest daily irritation.** Refunds were the first complaint of nine merchants out of fourteen. Six asked for bulk refunds as well.
2. **Sellers want their money sooner.** Nine merchants said sellers ask for faster payouts; two named a competitor that pays sellers instantly.
3. **Euro settlement works; the reports do not.** All five euro merchants were glad to have it. Four found the settlement report confusing, chiefly because settlement date and payout date looked alike.
4. **Night shifts are real.** Five merchants raised eye strain or asked for a dark theme before we mentioned it.
5. **Developers fear upgrades.** Four of the six merchants who brought a developer said they avoid upgrading the API because of past breaking changes.

## Themes in more detail

### Refunds

The typical story: a buyer complains, the operations team agrees a refund, raises a ticket with us and then refunds the buyer from its own account so as not to wait. M01 keeps a spreadsheet to match our refunds to their own a day later. M09 said refunds were "the only reason someone on my team has to watch the support inbox at weekends".

What they asked for: refunds from the payment page; partial refunds without explaining why; and, from six merchants, refunding many payments at once after a cancelled event or a faulty batch.

### Payouts

M03, M06 and M11 described sellers threatening to leave for a platform that pays faster. M07 pays some sellers early from its own funds and would pay a fee to stop doing so. Nobody wanted every payout instant; they wanted the option.

Questions about delayed payouts were common. Several merchants did not know that new sellers' payouts are held, and why; support's answers are on [Payout delays: what to tell merchants](../support/payout-delay-faq.md).

### Settlement and reporting

M10: "The money arrives in euros now, which is all we asked for. But my accountant cannot tell from the report which day it is for." M13 asked for the report to show the batch each payment belongs to. Three merchants mentioned settlement in dollars, none as a priority.

### Merchant Hub itself

Team roles, shipped in February, were praised by every merchant with a finance team. The French interface was in its last week of testing; M06 and M08 asked when it would be available. Five merchants raised the dark theme; M12's operations manager described turning her screen brightness down to read the payouts list at night.

### The API

M03 and M14 each described an incident of their own caused by a change in a response field. M02's developer pins nothing and "hopes". Developers liked the idea of a dated version they choose to move to, once it was explained.

## What we changed as a result

| Finding | Change | Where |
|---|---|---|
| Refunds | Confirmed ENG-6 scope; added the refund timeline to the payment page | [Self-serve refunds brief](brief-self-serve-refunds.md) |
| Bulk refunds | Added to "next" on the roadmap | [Roadmap 2026](roadmap-2026.md) |
| Faster payouts | Instant payouts moved into discovery for Q3 | [Instant payouts brief](brief-instant-payouts.md) |
| Settlement reports | Separate settlement and payout date columns, shipped in May | [Release notes](merchant-hub-release-notes-2026.md) |
| Dark theme | ENG-26 brought forward to start in ENG Sprint 31 | [Dark mode brief](brief-dark-mode.md) |
| API upgrades | Evidence for ENG-30 and its upgrade assistant | [ADR-023](../architecture/adr-023-api-versioning.md) |

## Next round

The next interview round is planned for November 2026, focused on dark mode preview users and on developers who have pinned a dated version.
