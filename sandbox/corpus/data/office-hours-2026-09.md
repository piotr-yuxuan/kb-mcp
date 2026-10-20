---
title: "Data office hours notes September 2026"
---

# Data office hours notes September 2026

Thursday 17 September 2026, 15:00 UK time, in ENG Sprint 38 (2026-09-14 to
2026-09-27). Hosted by Tomasz Wilde; notes by Signe Abernethy. Present from Data
Platform: Hana Ostrowska, Rafael Quist, Signe Abernethy. Visitors: Mireille Okonkwo and
one engineer from Risk ML, Yusuf Achterberg (Payouts), three analysts from Finance and
Product.

## Follow-ups from August

- The overnight `DQ-031` exemption on `payouts_hourly` has been in place since July.
  Yusuf confirmed that the Payouts channel now sees one or two warnings a week, all of
  them worth reading.
- The refunds note is in the catalogue description of `marts.merchant_orders_daily`.

## Questions

### "The backfill command refused my range"

Three people have hit the 31-partition cap since it shipped in ENG Sprint 35. Hana
walked through the month-by-month loop on
[Backfilling historical partitions](backfills.md) and reminded everyone that hourly
pipelines count hours, not days. Automatic splitting of long ranges is the remaining
part of ENG-20 and is planned for ENG Sprint 40.

A Finance analyst asked why the cap is not simply higher for Data Platform. *Tomasz:*
because the reasons for it (commit size, cluster share, how much you lose to a mistake)
do not depend on who runs the command.

### Bank holiday alerts

The late-August bank holiday, Monday 31 August, raised `DQ-031` on eleven tables the
next morning, all of them real drops in volume and none of them problems. *Rafael:* this
is what annotations are for, and we forgot.

Agreed: annotate every UK bank holiday ahead of time for the tier 1 marts. The next ones
are Friday 25 December and Monday 28 December. Rafael will also add the November peak
trading weekend; the format is on [Data quality alerts](quality-alerts.md).

### A new feature for the fraud model

*Mireille:* Risk ML wants a 30-day refund ratio per merchant in
`marts.fraud_features_daily`, with history, for the next training cycle.

*Hana:* fine, as a new column, never by changing an existing one, and the history comes
from a backfill agreed with Risk ML because training sets are pinned to snapshots. The
rules are on [Pipeline: fraud_features_daily](pipeline-fraud-features-daily.md). The
backfill will need several months of partitions, so several runs.

Agreed to schedule the backfill in the week of 5 October, outside the nightly window,
after the feature has passed review.

### Scratch tables vanishing

Two analysts lost scratch tables after three weeks of annual leave, and
asked for a longer expiry. *Tomasz:* no; 21 days is deliberate, and anything worth more
than that should be a mart. Rafael offered to pair with them on turning one of the
tables into a proper tier 2 mart.

## Actions

| Action | Owner | Due | Epic |
|---|---|---|---|
| Annotations for 25 and 28 December 2026 on tier 1 marts | Rafael Quist | 2026-11-30 | ENG-18 (follow-up) |
| Annotation for the November peak trading weekend | Rafael Quist | 2026-11-20 | |
| Review the 30-day refund ratio feature | Hana Ostrowska, Risk ML | 2026-10-02 | |
| Backfill the new feature column, monthly runs | Hana Ostrowska | Week of 2026-10-05 | ENG-20 |
| Pair on promoting a scratch table to a mart | Rafael Quist | 2026-10-09 | |
| Automatic splitting of long backfill ranges | Hana Ostrowska | ENG Sprint 40 | ENG-20 |

Next office hours: Thursday 15 October 2026.
