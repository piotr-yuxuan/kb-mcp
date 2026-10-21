---
title: "Risk operations: reviewing declined payments"
---

# Risk operations: reviewing declined payments

- **Owner:** Risk Operations, lead Rafael Ostrowski
- **Co-owner for the data side:** Risk ML
- **Last reviewed:** 2026-09-29

Risk Operations reviews a sample of the payments that the fraud model declined, every
day, by hand. The reviews tell us how many honest buyers we are turning away, feed
labels back into training, and give an early warning when the model starts behaving
oddly. This page is the reviewers' procedure and what Risk ML does with the results.

## What gets reviewed

| Review set | Size | Chosen how | When |
|---|---|---|---|
| Daily sample | 200 declines | Stratified by currency and score band | Every day, previous day's declines |
| Merchant appeals | All | A merchant asks us to look at a decline | Within 2 working days |
| Shadow-mode review | 300 declines | Payments only a challenger would have declined | During a challenger's shadow period |
| Ad hoc | Varies | Risk ML asks, for example after a rollback | As agreed |

The daily sample over-represents scores just above the threshold, because that is
where the model is least sure and where a review teaches us the most.

## The review itself

Reviews are worked in Harbour, in the "Declined payment review" view, one case per
payment. For each case, look at:

1. The payment: amount, seller, marketplace, currency, whether 3DS was attempted.
2. The card token's recent history on our platform: earlier payments, earlier
   declines, any chargebacks.
3. The seller: account age, earlier fraud findings, open payout holds.
4. Anything the merchant has sent us, for appeals.

Then record one outcome:

| Outcome | Meaning | Becomes a label? |
|---|---|---|
| Confirmed fraud | Clear evidence: a known pattern, a match with confirmed fraud, the cardholder's own statement | Yes, fraud |
| Legitimate | Clear evidence the buyer was genuine, such as a long consistent history | No, but counted as a false decline |
| Inconclusive | Not enough to tell | No |

Choose "inconclusive" freely. A wrong "confirmed fraud" goes into the training data;
a wrong "inconclusive" costs nothing. How outcomes become labels is on
[Labelling fraud from chargebacks](chargeback-labels.md).

Never contact the cardholder. If a merchant appeal suggests fraud against the
merchant itself, hand it to Support following
[Merchants reporting fraud](../support/merchant-fraud-reports.md). Holds on new
sellers' payouts follow their own process on
[Payout holds and releases](../payments/payout-holds.md) and are not part of this
review.

## What the numbers usually look like

Over the last quarter, of the daily sample:

| Outcome | Typical share |
|---|---|
| Confirmed fraud | 30% to 38% |
| Legitimate | 45% to 55% |
| Inconclusive | 12% to 18% |

A model that declines 0.5% of payments while fraud is a fraction of that will always
turn away some honest buyers; the reviews tell us how many. These shares are a
property of the operating point, not a sign that anything is wrong.

## When to raise the alarm

Post in `#team-risk-ml` and mention the Risk ML on-call when any of these happen:

- The legitimate share of a daily sample exceeds 65%.
- More than five merchant appeals in a day name the same marketplace.
- Reviewers see a new pattern of declines that makes no sense, for example declines
  on long-standing buyers with nothing unusual about the payment.

Risk ML decides what to do. The options include a rollback of the model, which is
their call and is described on
[Rolling back a model in production](model-rollback.md). If they roll back, they will
tell you in `#risk-ops`; expect the mix of declined payments to change within the
hour, and note the time on the day's review summary.

## Daily summary

The lead on duty posts a short summary in `#risk-ops` by 11:00 UK time:

```text
Review summary for 2026-09-28 declines
Sample: 200 (GBP 148, EUR 52)
Confirmed fraud 69 | Legitimate 101 | Inconclusive 30
Appeals: 4 received, 3 legitimate, 1 inconclusive
Notes: cluster of legitimate declines on one homeware marketplace, raised with Risk ML
```

Risk ML pulls the outcomes from Harbour into the warehouse every night, and the
"Review outcomes" panel of the drift dashboard (see
[Model drift monitoring](drift-monitoring.md)) plots the legitimate share over time.
