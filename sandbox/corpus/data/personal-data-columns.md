---
title: "Tagging personal data columns"
---

# Tagging personal data columns

*Owner: Signe Abernethy. Last reviewed 2026-07-08.*

Any column in the warehouse that holds personal data, meaning data about an identifiable
person, must carry a tag that says what kind of personal data it is. Tags are not
paperwork: two things depend on them.

1. **Masking.** Trino masks tagged columns for every role that is not entitled to see
   them, so `analyst_internal` users see `***` where an email address would be.
2. **Erasure.** The `privacy_erasure` job finds a person's data only through tagged
   columns. An untagged column holding an email address is a column the job will never
   clean. See [Erasure requests in the warehouse](erasure-requests.md).

## The tags

| Tag | Use it for | Examples |
|---|---|---|
| `personal.subject_key` | A column that identifies a person and can be matched to an erasure request; needs `subject_type` | `seller_id`, `user_id`, `customer_ref`, `card_token` |
| `personal.contact` | Ways to reach a person | Email address, phone number, postal address |
| `personal.name` | Names | First name, surname, a seller's trading name when it is their own name |
| `personal.financial` | Financial details of an individual | Payout account references of individual sellers |
| `personal.online` | Online identifiers | IP address, device identifier |
| `personal.free_text` | Free text that may contain any of the above | Dispute descriptions, notes |

`subject_type` is one of `merchant_user`, `seller` or `cardholder`. A table with any
personal data must have at least one `personal.subject_key` column, otherwise the job
cannot tell whose data a row is.

Card numbers are never in the warehouse and need no tag; if you ever find one, stop and
tell Security, because it means something upstream is badly wrong.

## Where tags go

Tags live in the column file next to each model, in `data-pipelines`:

```yaml
# models/staging/stg_payout_gateway__sellers.columns.yaml
table: staging.stg_payout_gateway__sellers
erasure_policy: erase
columns:
  - name: seller_id
    tags: [personal.subject_key]
    subject_type: seller
  - name: email
    tags: [personal.contact]
  - name: display_name
    tags: [personal.name]
  - name: payout_account_ref
    tags: [personal.financial]
  - name: country_code
    tags: []
```

The `erasure_policy` (`erase`, `pseudonymise` or `aggregate_only`) is explained on the
erasure page. Tags flow downstream automatically when a mart selects a tagged column
under the same name; a renamed or derived column must be tagged again.

## The build will stop you

When a model is built in review, a detector looks at column names and a sample of
values. A column called `email`, `phone`, `first_name`, `address`, `ip_address` or
similar, or whose values look like email addresses or phone numbers, must be either
tagged or explicitly marked `tags: []` with a comment saying why it is not personal:

```yaml
  - name: support_email
    tags: []   # the merchant's shared support mailbox, not a person
```

The build refuses to promote an untagged column that the detector flags. False alarms
cost a line of YAML; misses cost an erasure we cannot carry out.

## Hard cases

**Is `merchant_id` personal?** Usually not: most merchants are companies. Sole traders
are people, though, so `merchant_id` is not tagged, but `seller_id` in payout tables is,
because individual sellers are a large share of payout recipients.

**A shared mailbox such as a merchant's support address?** Not personal, as long as it
does not name a person. `first.last@example.com` is personal; `support@example.com` is
not. When in doubt, tag.

**Hashed values?** A hash of an email address is still personal data: anyone with the
address can compute the hash and find the row. Tag it with the same tag as the original.

**Aggregates?** A count of orders per merchant per day is not personal. A count per
cardholder per day is, because the grain is a person; such a table needs a
`personal.subject_key` column like any other.

## Classification

A table with any `personal.*` column is classed Confidential at least. The classes and
what they mean for handling are on
[Data classification](../security/data-classification.md).

## Checking a table

```sql
select column_name, tags, subject_type
from iceberg.ops.catalogue_columns
where table_name = 'marts.merchant_orders_daily'
  and cardinality(tags) > 0;
```

An empty result for a mart that is meant to hold only aggregates, as here, is what you
want to see.
