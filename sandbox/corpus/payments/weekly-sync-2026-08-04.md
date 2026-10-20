---
title: "Payments weekly sync 2026-08-04"
---

- **Date:** Tuesday 4 August 2026, 10:30 to 11:15 UK time, ENG Sprint 35
- **Chair:** Nadia Ferreira
- **Attendees:** Nadia Ferreira, Yusuf Achterberg, Kwabena Stroud, Oskar Ngata, Lukas Brennand
- **Apologies:** Femi Haldane (annual leave)
- **Notes:** Kwabena Stroud

## 1. Self-serve refunds API (ENG-6)

ENG-6 closed with the end of ENG Sprint 34 on Sunday 2 August. The self-serve refunds API is available to every merchant; refunds over £10,000 need a second approver, as designed.

Oskar reported that two merchants with a single finance user asked whether that user could approve their own refunds from a second device. The group agreed that the point of the rule is a second person, not a second device, and that it stays as it is. Oskar will answer both merchants and suggest they add a second user.

## 2. Hardware security keys (ENG-16)

ENG-16 closes with ENG Sprint 35 on 16 August. Three payments production administrators have not yet enrolled their keys: two in Payouts and one in Ledger. Nadia will chase them this week, so that payments is not the team holding the epic open.

## 3. Chargeback evidence (ENG-28)

Support's chargeback evidence automation needs the outcome of each authorisation, including the 3DS result, in a form it can attach to an evidence pack. Today that means someone in Payments Core querying `card-auth`'s records by hand. Nadia proposed a small read endpoint on `card-auth`, keyed by payment token and returning nothing that could identify the card beyond what Support already sees. Agreed in principle; a short design note first, since it touches the card data environment's boundary.

## 4. Status page templates (ENG-13)

Site Reliability's Beacon automation work wants a ready-made template for payout delays, so that the first public update can go out quickly. Yusuf will draft one, written for sellers rather than engineers, and run it past Support before it goes to Site Reliability.

## 5. Operations review: July

- `PayoutQueueBacklog` fired three times in July, each time at an end-of-day peak, and each resolved within one cycle. No rollback was needed.
- Lukas asked whether the threshold should rise from 2,000 to 3,000 queued payouts to stop the peak-time noise. Yusuf argued that a backlog of 2,000 already means the first sellers in the queue are 15 minutes late, and that the three pages were cheap. The group kept the threshold.
- `LedgerReconBreak` paged on nine mornings; all breaks were explained within the day, and none reached the finance controller.
- `CardAuthP99High` fired once, for a single slow issuer, and resolved without action.

## 6. Summer cadence

Several people are away in August. The sync will run fortnightly until the end of September and return to weekly on 29 September. Notes stay under the "weekly sync" title so that people can find them.

## Decisions

1. The rule that refunds over £10,000 need a second approver stays as built in ENG-6, including for merchants with a single user.
2. The `PayoutQueueBacklog` threshold stays at 2,000 queued payouts.
3. The sync runs fortnightly until 29 September; the next one is on 18 August.

## Actions

| Owner | Action | Ticket | Due |
|---|---|---|---|
| Oskar Ngata | Reply to the two merchants about the second approver | ENG-6 | 2026-08-07 |
| Nadia Ferreira | Chase the three remaining hardware key enrolments | ENG-16 | 2026-08-14 |
| Nadia Ferreira | Design note for an authorisation evidence endpoint on `card-auth` | ENG-28 | 2026-08-18 |
| Yusuf Achterberg | Draft a Beacon template for payout delays, reviewed by Support | ENG-13 | 2026-08-18 |
| Kwabena Stroud | Publish these notes and link them from [Payments engineering teams](teams.md) | | 2026-08-05 |

Next: [Payments weekly sync 2026-08-18](weekly-sync-2026-08-18.md).
