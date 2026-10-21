---
title: "Data office hours notes July 2026"
---

# Data office hours notes July 2026

**Date:** Thursday 16 July 2026, 15:00 to 16:00 UK time, Quill House floor 4 and video
**Sprint:** ENG Sprint 33 (2026-07-06 to 2026-07-19)
**Host:** Tomasz Wilde
**Data Platform:** Hana Ostrowska, Rafael Quist, Signe Abernethy
**Visitors:** Beatrix Sallow (DPO), Arjun Pelletier (Finance), Oskar Ngata (Payouts
product), two analysts from Risk Operations
**Notes:** Rafael Quist

Office hours are open to anyone with a question about the warehouse. These notes record
the questions and what we agreed; the answers are summaries, not policy. Policy lives
on the pages linked.

## 1. Erasure automation is live

*Beatrix:* Now that ENG-19 has closed (last tickets done in ENG Sprint 32), how does the
privacy team show that a given request was applied, without asking a data engineer?

*Signe:* Every applied request has a row in `privacy.erasure_log`, and the
`privacy_officer` role can read it directly. Signe showed the "requests not yet
applied" query from [Erasure requests in the warehouse](erasure-requests.md). The log
holds only request identifiers, never names or emails.

*Beatrix* asked whether the job also covers personal scratch tables. Yes: `scratch` is
in scope like every other schema, which surprised the Risk Operations analysts.

Agreed: the privacy team will check the "not yet applied" query weekly, on Mondays.

## 2. Overnight noise on payouts_hourly

*Oskar:* The Payouts channel gets `DQ-031` warnings most nights between 01:00 and 05:00
UTC, and people have started ignoring them, which defeats the purpose since this table
blocks on that check.

*Hana:* At night some hours have a few dozen payouts, so a swing of ten payouts is more
than a quarter of the median. Proposal: skip the row-count check for hours whose 7-day
median is below 200 payouts.

Agreed, with Oskar's support. Hana to ship it this sprint.

## 3. Refunds in merchant_orders_daily

*Arjun:* The daily revenue report's refund figure for a day never matches what the
`ledger` team shows for refunds against that day's orders.

*Rafael:* That is by design: the table counts refunds on the day they are processed,
not on the order's day, so that old partitions stay stable. Both numbers are right;
they answer different questions. The detail is on
[Pipeline: merchant_orders_daily](merchant-orders-daily.md).

Arjun asked for this to be visible where analysts look, not only on the wiki. Rafael to
put it in the table description in the catalogue.

## 4. Backfill tooling

ENG-20 started this sprint. *Tomasz* explained the first deliverable: a hard cap on
partitions per backfill, and a refusal to start during the nightly window. A Risk
Operations analyst asked whether they could still fill two years of a new table in one
go once the cap lands. No: it will be split into monthly backfills, and we will post a
script for it.

## 5. Access requests are slow

Two visitors waited over a week for `analyst_confidential`. The bottleneck was stewards
not seeing the request in a busy channel. Agreed: Data Platform will tag the steward in
the thread and chase after two working days.

## Actions

| Action | Owner | Due | Epic |
|---|---|---|---|
| Skip `DQ-031` for hours with a 7-day median under 200 payouts on `payouts_hourly` | Hana Ostrowska | 2026-07-19 | |
| Add the refunds note to the catalogue description of `marts.merchant_orders_daily` | Rafael Quist | 2026-07-24 | |
| Weekly check of unapplied erasure requests | Beatrix Sallow's team | Every Monday | ENG-19 (follow-up) |
| Publish a script to split long backfills into months | Hana Ostrowska | When the cap ships | ENG-20 |
| Tag stewards on access requests and chase after two working days | Signe Abernethy | From now | |

Next office hours: Thursday 20 August 2026.
