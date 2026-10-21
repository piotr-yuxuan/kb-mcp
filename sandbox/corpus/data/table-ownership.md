---
title: "Data catalogue and table ownership"
---

# Data catalogue and table ownership

Owner: Tomasz Wilde. Last reviewed 2026-07-21.

Every table in `marts` has an owning team and a steward. The data catalogue is where you
find them, along with each table's description, grain, tier, freshness deadline and
classification. You can browse it under **Tables** in the Conveyor web interface, or
query it in `ops.catalogue_tables`.

## Owner and steward

- The **owning team** is accountable for the table: its correctness, its quality checks
  and its alerts. Alerts route to the owning team's channel and, for tier 1 tables, its
  on-call.
- The **steward** is the named person in that team who answers questions about the
  table, approves changes to it and approves access to it when it is Confidential.
  Every steward has a deputy for when they are away; for a table whose pipeline Data
  Platform runs on another team's behalf, the deputy may come from Data Platform.

A team can own a table without running the pipeline that builds it. Risk ML owns the
feature definitions of `marts.fraud_features_daily`, for example, while Data Platform
runs the pipeline; the catalogue records both.

## Where ownership is declared

Ownership lives in `catalogue/owners.yaml` in `data-pipelines`, reviewed like code. The
catalogue is rebuilt from it on every deploy.

```yaml
- table: marts.merchant_orders_daily
  owning_team: data-platform
  steward: rafael.quist
  deputy: hana.ostrowska
  tier: 1
  classification: Confidential
  consumers: [finance, product, merchant-support, risk-operations]
  description: >
    Orders, captures and refunds per merchant, day and currency.
    Days are UTC; refunds count on the day they are processed.

- table: marts.fraud_features_daily
  owning_team: risk-ml
  pipeline_team: data-platform
  steward: mireille.okonkwo
  deputy: hana.ostrowska
  tier: 1
  classification: Confidential
  consumers: [risk-ml]
```

The `classification` uses the classes from
[Data classification](../security/data-classification.md). Columns that hold personal
data are tagged separately; see [Tagging personal data columns](personal-data-columns.md).

## Finding an owner

```sql
select table_name, owning_team, steward, deputy, tier
from iceberg.ops.catalogue_tables
where table_name like 'marts.finance%'
order by table_name;
```

## Responsibilities of an owning team

1. Keep the description and consumers up to date.
2. Keep the quality checks meaningful, and respond to the table's alerts (see
   [Data quality alerts](quality-alerts.md)).
3. Announce breaking changes to consumers at least one sprint ahead.
4. Review the table once a year: is it still used, is the tier right, is the steward
   still in the team?

## When a steward leaves or a team changes

The catalogue build fails if a steward's account is deactivated, so a leaver cannot
silently orphan a table: the next deploy of `data-pipelines` stops until someone
updates `owners.yaml`. When teams reorganise, the previous owning team keeps the table
until the new one accepts it in a reviewed change.

## Unowned and unused tables

Each quarter Data Platform lists marts that nobody has queried for 90 days. Their
owners are asked whether to keep them; a table with no answer after 30 days is marked
`deprecated` in the catalogue, and dropped 30 days after that. Tables in `scratch` are
not in the catalogue and expire on their own.
