---
title: "Warehouse naming conventions"
---

# Warehouse naming conventions

Owner: Rafael Quist. Last reviewed 2026-06-18.

Names in the warehouse are an interface. People find tables by guessing their names,
and pipelines break when names change, so we choose them once and carefully. These
conventions apply to every new table and column; existing exceptions are listed at the
end and will not be renamed.

## Schemas

The schema is the layer, as described in the
[Data platform overview](platform-overview.md): `raw`, `staging` or `marts`, plus the
service schemas `privacy`, `ops` and `scratch`. Do not create new schemas; if you think
you need one, ask in `#team-data`.

## Tables

| Layer | Pattern | Example |
|---|---|---|
| `raw` | source service, two underscores, entity | `raw.payout_gateway__payouts` |
| `staging` | `stg_`, source service, two underscores, entity | `staging.stg_ledger__captures` |
| `staging` (intermediate) | `int_`, pipeline name, two underscores, step | `staging.int_merchant_orders_daily__fx_to_gbp` |
| `marts` | domain, entity, grain | `marts.merchant_orders_daily` |
| `scratch` | your user name, two underscores, anything | `scratch.rafael_quist__refund_check` |

Rules:

- Lower case, words separated by underscores. Hyphens in service names become
  underscores: `payout-gateway` becomes `payout_gateway`.
- **The grain is the last word of a mart's name**: `_daily`, `_hourly`, `_monthly`, or
  `_current` for a table that holds only the latest state. A mart without a grain word is
  refused at review.
- Entities are plural nouns: `payouts`, `orders`, `features`.
- Intermediate tables belong to one pipeline. Nobody outside that pipeline should read
  them, and the pipeline may change them without notice.
- Finance marts start with `finance_`, which is how alert routing recognises them (see
  [Data quality alerts](quality-alerts.md)).
- No version numbers in names. A breaking change is a new column or, rarely, a new table
  with a new name that says what is different.

## Pipelines

A Conveyor pipeline takes the name of the mart it builds, without the schema:
`merchant_orders_daily` builds `marts.merchant_orders_daily`. A pipeline that builds
several marts is named after the main one.

## Columns

| Kind | Convention | Example |
|---|---|---|
| Identifiers | `_id` suffix, same name everywhere the same thing is meant | `merchant_id`, `seller_id` |
| Timestamps | `_at` suffix, `timestamp(6) with time zone`, always UTC | `authorised_at`, `built_at` |
| Dates | `_date` suffix, the UTC date | `order_date`, `feature_date` |
| Hours | `_hour` suffix, truncated UTC timestamp | `payout_hour` |
| Money | `_amount_minor` suffix, integer minor units, with a `currency` column in the same row | `captured_amount_minor` |
| Money in GBP | `_amount_gbp_minor` or `_gbp_minor` for converted figures | `gross_amount_gbp_minor` |
| Counts | `_count` suffix | `orders_count` |
| Booleans | `is_` or `has_` prefix | `is_test_merchant`, `has_chargeback` |
| Ratios | `_ratio` suffix, between 0 and 1 | `decline_ratio_7d` |
| Windows | the window as a suffix: `_1h`, `_24h`, `_7d`, `_30d` | `auth_count_7d` |

Money is always stored in integer minor units, as decided in
[ADR-017](../architecture/adr-017-money-minor-units.md). Never store an amount as a
decimal number of pounds or euros, and never put two currencies in one column without a
`currency` column next to it.

Abbreviations are avoided, except these: `id`, `fx`, `gbp`, `eur`, `utc`, `min` and
`max`. Write `authorisation`, not `auth`, in new entity names; `auth` survives in
column names that already use it.

## Spelling

British spelling in names, as in the rest of the company: `authorised_at`,
`organisation_id`, `cancelled_at`. Where a source service uses American spelling,
staging renames the column.

## Known exceptions

- `raw.card_auth__authorizations` keeps the source table's spelling; its staging model
  is `staging.stg_card_auth__authorisations`.
- `marts.fraud_features_daily` uses `auth_` in its feature names, which predate this
  page.

See also the [SQL style guide](sql-style-guide.md) for how to write the queries that
use these names.
