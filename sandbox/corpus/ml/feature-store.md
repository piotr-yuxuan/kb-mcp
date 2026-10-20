---
title: "Feature store guide"
---

# Feature store guide

*Owner: Risk ML. Maintained by Sunniva Holt. Last reviewed 2026-09-30.*

"Feature store" is a grand name for something deliberately small: a folder of feature
definitions in the `risk-ml` repository, a Python package that reads them, and two
places where the values live. It exists so that a feature means the same thing when
we train a model and when `risk-scorer` scores a payment.

## The pieces

| Piece | Where | What it holds |
|---|---|---|
| Definitions | `risk-ml/features/*.yaml` | Name, entity, window, owner, description, as-of rule |
| Offline values | `marts.fraud_features_daily` | One row per authorisation, values as of authorisation time |
| Online values | Inside `risk-scorer` | The latest aggregates per card token, device and seller |
| Library | `qm_features` Python package | Point-in-time reads, feature sets, validation |

The offline table is built by the `fraud_features_daily` pipeline, which Data
Platform runs; its schedule and checks are on
[Pipeline: fraud_features_daily](../data/pipeline-fraud-features-daily.md). The table
sits in the `marts` layer of the warehouse described in the
[data platform overview](../data/platform-overview.md).

## Naming

Feature names follow `entity__measure__window`, with double underscores:

- `card__auth_count__24h`: authorisations for this card token in the previous 24 hours.
- `seller__chargeback_rate__90d`: the seller's fraud chargeback rate over 90 days,
  counting only chargebacks known at the time.
- `payment__amount_band`: no window, because it describes the payment itself.

Entities are `card`, `device`, `seller`, `merchant` and `payment`. Windows are `1h`,
`24h`, `7d`, `30d` and `90d`; ask before adding another.

## A definition

```yaml
name: seller__chargeback_rate__90d
entity: seller
window: 90d
owner: risk-ml
description: >
  Share of the seller's settled payments in the previous 90 days that received a
  fraud chargeback, counting only chargebacks received before the authorisation.
as_of: authorised_at
source: staging.chargebacks
null_policy: zero_if_no_payments
personal_data: false
feature_sets: [fraudscore_v7]
```

`as_of` is the important line. It tells the library which timestamp the value must
not look past. A feature without it is rejected in review.

## Reading features for training

Always go through the library. It joins on the authorisation's own timestamp and
refuses features that are not in the requested feature set:

```python
from qm_features import FeatureSet

features = FeatureSet.load("fraudscore_v7")
frame = features.read_offline(
    start="2025-07-01",
    end="2025-07-31",
    snapshot_id=7342918840012655311,
)
print(frame.shape)  # one row per authorisation, one column per feature
```

Hand-written SQL against the table is fine for exploration in a
[notebook](notebooks.md). It is not fine for anything that trains a candidate, because
the library is where the as-of rules are enforced.

## Adding a feature

1. Write the definition and a short test of its as-of behaviour.
2. If the feature needs a new column in `fraud_features_daily`, agree it with Data
   Platform in `#team-data` first; they own the pipeline.
3. If it uses personal data, set `personal_data: true` and tag the source column as
   described on [Tagging personal data columns](../data/personal-data-columns.md).
   The DPO's team reviews these.
4. Add the online computation to `risk-scorer`, or confirm that it can be loaded from
   the nightly snapshot.
5. Open a pull request; a second Risk ML engineer reviews it.
6. Once merged, the feature appears in the offline table from the next run. For
   history, Data Platform runs a backfill.

## Online and offline parity

A nightly job compares a sample of 50,000 of yesterday's authorisations: the values
`risk-scorer` used against the offline values for the same payments. Any feature whose
values differ on more than 0.1% of rows raises an alert in `#team-risk-ml`. Parity
breaks are usually rounding, a time-zone boundary, or a late event that the online
side never saw.

## Common mistakes in review

These come up often enough that reviewers check for them first:

- **A window that ends at midnight.** `24h` means the 24 hours before the
  authorisation, not "yesterday". A definition that reads a daily partition for a
  `24h` window is wrong for every payment made after midnight.
- **Counting the payment itself.** `card__auth_count__1h` excludes the authorisation
  being scored. Including it shifts every value by one and breaks parity with the
  online side, which never counts the current payment.
- **Nulls that mean two things.** "No payments in the window" and "data missing" must
  not both become null. Use `null_policy` to say which one a null means, and make the
  other a value.
- **Amounts in major units.** Amounts are integer minor units everywhere; a feature
  that divides by 100 on the way in will disagree with every other amount feature.
- **Seller and merchant confused.** The merchant is the marketplace that integrates
  with Quillmoor Pay; the seller is who gets paid out. A `merchant__` feature is about
  the marketplace as a whole.

## Retiring a feature

Remove it from every feature set first, wait until no registered model that might be
served (including the rollback target) uses it, then delete the definition. `modelctl
describe` lists each model's features.
