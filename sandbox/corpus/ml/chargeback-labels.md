---
title: "Labelling fraud from chargebacks"
---

# Labelling fraud from chargebacks

**Owner:** Risk ML, with Risk Operations for manual findings.
**Last reviewed:** 2026-08-12 by Sunniva Holt.

Our models learn what fraud looks like from labels, and almost all of those labels come
from chargebacks. This page sets out which payments we call fraudulent, which we do
not, and where the labels live. How long a payment must wait before its label counts
for training is part of the training procedure, and is on
[Training the fraud model](fraud-model-training.md).

## Sources of labels

| Source | Becomes a fraud label when | Share of fraud labels, last 12 months |
|---|---|---|
| Chargebacks | The card scheme's reason code is in the fraud category | 88% |
| Risk Operations findings | A reviewer marks a payment "confirmed fraud" | 9% |
| Merchant reports | A merchant reports fraud and Risk Operations confirms it | 3% |

A payment with no fraud label from any source, once the wait has passed, is labelled
legitimate. That is an assumption, not a fact: some fraud is never charged back,
usually because the amount was too small for the cardholder to notice.

## Chargebacks

Each card scheme publishes its own reason codes. We map them to three groups in
`risk-ml/labels/reason_codes.yaml`:

- **Fraud**: the cardholder says they did not make or authorise the payment. These
  make a fraud label.
- **Service**: goods not received, not as described, cancelled subscriptions. These
  are disputes between buyer and seller, not fraud, and never make a fraud label.
- **Processing**: duplicate processing, wrong amount, late presentment. Not fraud.

When a scheme adds or changes a reason code, the mapping must be updated before the
next training run; an unmapped code fails the label build rather than being guessed.

### Awkward cases

- **Chargeback reversed after evidence.** If the merchant wins the dispute with
  evidence, the fraud label is removed. The dispute process itself is on
  [Chargebacks and disputes](../support/chargebacks.md).
- **Several chargebacks on one payment.** Count the payment once.
- **Partial chargebacks.** A fraud chargeback for part of the amount still makes the
  whole payment fraudulent; the amount matters only for value-weighted recall.
- **Refunded before the chargeback.** If a merchant refunds a payment and the
  cardholder still raises a fraud chargeback, it is fraud. If the merchant refunds
  because they suspect fraud and no chargeback follows, a Risk Operations finding is
  needed for a label.
- **"Friendly fraud".** A cardholder who made the purchase and then claims fraud
  produces a fraud chargeback all the same. We cannot tell these apart reliably, and
  we do not try: the model learns them as fraud.

## Risk Operations findings and merchant reports

Reviewers record outcomes as described on
[Risk operations: reviewing declined payments](risk-ops-reviews.md). Only "confirmed
fraud" becomes a label; "legitimate" and "inconclusive" do not override a chargeback.
Merchant reports reach us through Support (see
[Merchants reporting fraud](../support/merchant-fraud-reports.md)) and count only once
Risk Operations confirms them.

## Where labels live

The label build runs nightly and writes `marts.fraud_labels`, one row per
authorisation that has any label source, with amounts in integer minor units as
everywhere else (see
[ADR-017: Represent money in integer minor units](../architecture/adr-017-money-minor-units.md)).

```sql
SELECT authorisation_id,
       label,             -- 'fraud' or 'legitimate'
       label_source,      -- 'chargeback', 'risk_ops' or 'merchant_report'
       first_evidence_at, -- when the first fraud signal arrived
       amount_minor,
       currency
FROM marts.fraud_labels
WHERE authorised_on BETWEEN DATE '2025-08-01' AND DATE '2025-08-31';
```

`first_evidence_at` is what the training pipeline uses to apply the label wait: a
payment whose evidence arrived after the cut-off is treated as unlabelled for that
run, not as legitimate.

## How quickly chargebacks arrive

Measured on 2025 payments, the share of fraud chargebacks received by a given number
of days after authorisation:

| Days after authorisation | Share received |
|---|---|
| 15 | 41% |
| 30 | 78% |
| 45 | 92% |
| 60 | 97% |
| 120 | 99.6% |

This curve is why the wait used for `fraudscore-v6` was later lengthened; see
[Model card: fraudscore-v6](model-card-fraudscore-v6.md).
