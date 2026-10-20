---
title: "Pipeline: fraud_features_daily"
---

# Pipeline: fraud_features_daily

*Run by Data Platform; feature definitions owned by Risk ML. Stewards: Hana Ostrowska
(pipeline) and Mireille Okonkwo's team (definitions). Last reviewed 2026-08-12.*

## Purpose

`fraud_features_daily` computes, once a day, the slow-moving behavioural features that
the fraud models use: how a card token, a customer reference or a merchant has behaved
over the past hours, days and weeks. The table is the training source for Risk ML and
the daily refresh of the slow features in the feature store. The fast features, those
that change within a payment session, are computed online by `risk-scorer` and are not
in the warehouse at all.

How the features are used in training is described in
[Training the fraud model](../ml/fraud-model-training.md); how they reach serving is in
the [Feature store guide](../ml/feature-store.md). This page covers the pipeline.

## Facts

- **Output:** `marts.fraud_features_daily`, partitioned by `feature_date`.
- **Schedule:** daily at 02:30 UTC; freshness deadline 05:00 UTC; tier 1.
- **Grain:** one row per entity and `feature_date`, where the entity is a
  `card_token`, a `customer_ref` or a `merchant_id`, given by `entity_type`.
- **Sources:** staging models of `card-auth` authorisations, `ledger` refunds and
  chargebacks, `merchant-api` orders and `risk-scorer` decisions.
- **Size:** about 38 million rows a day.

## Point in time, always

Every feature for `feature_date` D is computed from data that existed at 23:59:59 UTC
on D, and nothing later. That rule is what makes the table usable for training: a
feature that peeks at the future makes a model look excellent offline and useless in
production.

In practice this means:

1. Window functions are bounded by the partition date, never by `current_date`.
2. Late-arriving events (a chargeback recorded in the ledger weeks after the payment)
   count from the date they were recorded, not from the date of the payment they
   belong to.
3. The pipeline does not refresh a trailing window. Each partition is written once and
   then left alone, unless a backfill is agreed.

```sql
-- Pattern used by every windowed feature
count_if(a.authorised_at >= timestamp '{{ partition }} 00:00:00 UTC' - interval '7' day
     and a.authorised_at <  timestamp '{{ partition }} 00:00:00 UTC' + interval '1' day)
    as auth_count_7d
```

## Changing a feature

Risk ML proposes, Data Platform reviews, both approve. A pull request that adds or
changes a feature needs:

- the definition in `models/marts/fraud_features_daily/features.yaml`, with an owner
  and a plain-English description;
- a point-in-time test against a fixed fixture day;
- a dry-run backfill over the last 31 days, with the distribution of the new feature
  attached;
- for a changed feature, a new column name. We never change the meaning of an existing
  column, because trained models depend on it.

## Backfills need Risk ML

Training sets are pinned to Iceberg snapshots of this table. A backfill creates new
snapshots and can change the values a model was trained on, which breaks
reproducibility. Before any backfill of `fraud_features_daily`, agree it with Risk ML in
`#team-risk-ml`; they may ask you to write to a new column instead. The general
procedure, including the limit on partitions per run, is on
[Backfilling historical partitions](backfills.md).

## When it is late

A missed deadline raises `DQ-017` and pages the data on-call. The models keep serving
yesterday's slow features, so a delay of a few hours has no merchant impact; tell
`#team-risk-ml` and fix it in the normal way. If the table is still not ready by 12:00
UTC, Risk ML decides whether the feature store should be refreshed from a partial run.
