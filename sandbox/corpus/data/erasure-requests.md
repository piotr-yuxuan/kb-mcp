---
title: "Erasure requests in the warehouse"
---

# Erasure requests in the warehouse

- **Process owner (warehouse):** Signe Abernethy, Data Platform
- **Policy owner:** Beatrix Sallow, DPO
- **Contact:** `privacy@quillmoor.example` for requests; `#team-data` for the job
- **Last reviewed:** 2026-07-30

This page describes how an erasure request is applied to the data warehouse: which data
is in scope, what the `privacy_erasure` job does, what we keep and why, and how to prove
afterwards that a request was carried out. It is written for data engineers, for the
data on-call, and for the privacy team when they need to know what the warehouse can
and cannot do.

It does not cover whether a request is valid, how the requester's identity is checked,
or what we reply to them. Those belong to the privacy team and are set out in the
[DPA playbook](../legal/dpa-playbook.md). Production services erase data in their own
databases under their own procedures; this page is only about the warehouse.

## Background

GDPR Article 17 gives a person the right to have their personal data erased in a
number of situations, for example when it is no longer needed for the purpose it was
collected for, or when they withdraw consent and there is no other lawful basis. The
right is not absolute: data that we are legally obliged to keep, or that we need for
the establishment or defence of legal claims, stays, and for those records we
pseudonymise rather than erase.

The warehouse matters here because it holds copies. Every service database replicated
into `raw`, every staging model and many marts contain personal data about merchant
users, marketplace sellers and the cardholders who buy from them. An erasure that
stops at the production database leaves the person in a dozen Iceberg tables and in
their snapshots.

## Our commitment

> [!IMPORTANT]
> Every approved erasure request is applied in the warehouse **within 30 days** of the
> privacy team receiving it, and recorded in `privacy.erasure_log`.

In practice the job applies a request on the first nightly cycle after the privacy team
approves it, so most requests are applied within two days of approval. The 30 days are
the outer limit, and the reason the data on-call treats a failing erasure job as urgent
even though nobody is paged for it at night.

The 30-day commitment was the goal of ENG-19, the warehouse erasure automation epic,
which ran from ENG Sprint 24 to ENG Sprint 32 and finished in July 2026. Before it,
erasure in the warehouse was a manual SQL procedure run by whichever data engineer was
free, took up to three weeks, and was tracked in a spreadsheet.

## How a request reaches the warehouse

```text
person / merchant / support agent
          |
          v
privacy@quillmoor.example  -->  privacy team checks identity and scope
                                        |
                          approved      |      refused or partly refused
                                        v
                         row in privacy.erasure_requests (state: approved)
                                        |
                                        v
                 privacy_erasure job, daily at 07:00 UTC (Conveyor)
                                        |
                                        v
                 row in privacy.erasure_log (state: applied)
                                        |
                                        v
                 privacy team confirms to the requester
```

Requests arrive in three ways:

- **Directly** from the person, by email to `privacy@quillmoor.example`, sometimes as
  part of a wider DSAR.
- **Through Merchant Support**, when a merchant user or seller asks an agent. Agents do
  not act on these; they forward them as described in
  [Forwarding data subject requests](../support/data-subject-requests.md).
- **Through a merchant**, when the person is a merchant's customer and Quillmoor acts as
  the merchant's processor under a DPA. The merchant instructs us; the terms that govern
  those instructions are in the [DPA playbook](../legal/dpa-playbook.md).

Only the privacy team can write to `privacy.erasure_requests`, through the
`privacy_officer` Trino role. Data engineers can read the queue but cannot add to it,
so nobody erases data on the strength of a chat message.

## Who can be erased, and how we find them

Each request names a subject type and one or more keys:

| Subject type | Who | Keys the request carries |
|---|---|---|
| `merchant_user` | A person with a Merchant Hub login | `user_id`, email address |
| `seller` | A marketplace seller paid by Quillmoor Payouts, when an individual or sole trader | `seller_id`, email address |
| `cardholder` | A customer who paid a merchant through Quillmoor Pay | Email address, tokenised card reference, `customer_ref` supplied by the merchant |

The job finds every column that can hold one of those keys through the column tags
described in [Tagging personal data columns](personal-data-columns.md). A column tagged
`personal.subject_key` with `subject_type: seller` tells the job "rows where this column
matches a seller's key belong to that seller". A table with personal data and no
subject key tag cannot be erased reliably, which is why untagged personal data blocks
promotion to `marts`.

Card numbers are not in the warehouse at all, so there is nothing to erase there:
`card-auth` replicates only tokenised references.

## What the job does

`privacy_erasure` is an ordinary Conveyor pipeline. It runs daily at 07:00 UTC, after
the nightly pipelines have published, so that it never races a scheduled run for the
same table. For each approved request it:

1. **Resolves keys.** It expands the keys on the request into every identifier the
   warehouse uses for that person, for example from an email address to the
   `seller_id` and from there to payout account references.
2. **Plans.** It lists every table with a matching subject key column, in `raw`,
   `staging`, `marts` and `scratch`, and the action for each, from the table's
   erasure policy (below).
3. **Applies.** It erases or pseudonymises the matching rows with Iceberg row-level
   operations, table by table, each in its own commit.
4. **Rewrites and expires.** Row-level operations leave the old values in earlier data
   files and snapshots. The job compacts each touched table, then expires every
   snapshot older than the erasure commit and removes orphaned files, so the old values
   are physically gone from the live warehouse.
5. **Logs.** It writes one row per request to `privacy.erasure_log` and marks the
   request `applied`.

The core of step 3 for a table whose policy is `erase`:

```sql
delete from iceberg.raw.payout_gateway__sellers
where seller_id in (
    select subject_key
    from iceberg.privacy.erasure_keys
    where request_id = 'ER-2026-0412'
      and key_type = 'seller_id'
);
```

and for step 4:

```sql
alter table iceberg.raw.payout_gateway__sellers execute optimize;
alter table iceberg.raw.payout_gateway__sellers
    execute expire_snapshots(retention_threshold => '1d');
alter table iceberg.raw.payout_gateway__sellers
    execute remove_orphan_files(retention_threshold => '1d');
```

The job runs through a dedicated catalogue, `iceberg_erasure`, whose minimum snapshot
retention is lowered to one day; the ordinary `iceberg` catalogue refuses thresholds
that short, so nobody can expire history by accident.

### Erasure policies

Every table with personal data declares one of three policies in its table properties:

| Policy | What the job does | Typical tables |
|---|---|---|
| `erase` | Removes the subject's rows entirely | Raw copies of user and seller profiles, notification logs, scratch tables |
| `pseudonymise` | Replaces personal columns with a stable token such as `erased_7f3a9c21`, keeps the rest of the row | Payment, refund and payout records, which we must keep |
| `aggregate_only` | Nothing: the table holds no row about an individual | Most marts, including `marts.merchant_orders_daily` |

Pseudonymised rows keep amounts, dates and merchant identifiers, so financial reporting
still adds up, but no longer say who the person was. The token is derived from the
request identifier, not from the person's data, so it cannot be reversed. How long the
pseudonymised records are then kept is set by the
[Data retention schedule](retention-schedule.md).

## Backups

Warehouse backups (copies of the Iceberg data files and metadata in a separate storage
account) are taken nightly and **expire after 35 days**. We do not edit backups: they
are immutable by design, which is what makes them useful. Erased data therefore remains
in backups until they expire, at most 35 days after the erasure was applied, and is out
of reach of everyone except the two Data Platform engineers who can restore.

If a backup is ever restored, the restore procedure applies every entry in
`privacy.erasure_log` with an `applied_at` later than the backup's date before the
restored tables are opened to anyone. That step is part of the restore checklist and is
not optional. The privacy team includes the 35-day backup window in the reply to the
requester.

## The erasure log

`privacy.erasure_log` is the evidence that a request was carried out. It holds no
personal data itself: only the request identifier, which the privacy team can map back
to the person in their own records.

| Column | Meaning |
|---|---|
| `request_id` | Identifier from the privacy team, such as `ER-2026-0412` |
| `subject_type` | `merchant_user`, `seller` or `cardholder` |
| `received_at` | When the privacy team received the request |
| `approved_at` | When it was approved and queued |
| `applied_at` | When the job finished applying it |
| `tables_erased` | Tables where rows were removed |
| `tables_pseudonymised` | Tables where rows were pseudonymised |
| `rows_affected` | Total rows changed |
| `job_version` | Version of `privacy_erasure` that applied it |
| `notes` | Anything unusual, such as a key that matched nothing |

To check a request, or to find any that are at risk of missing the commitment:

```sql
-- One request
select request_id, received_at, applied_at, rows_affected, notes
from iceberg.privacy.erasure_log
where request_id = 'ER-2026-0412';

-- Approved requests not yet applied, oldest first
select
    r.request_id,
    r.received_at,
    date_diff('day', r.received_at, current_timestamp) as days_open
from iceberg.privacy.erasure_requests as r
left join iceberg.privacy.erasure_log as l
    on l.request_id = r.request_id
where r.state = 'approved'
  and l.request_id is null
order by r.received_at;
```

Anything open for more than 20 days is raised with Signe Abernethy and the privacy team
the same day.

## Edge cases

**The key matches nothing.** The job logs the request with `rows_affected = 0` and a
note. This is common for cardholders who paid once, years ago, through a merchant that
has since left. It is still a completed request.

**A legal hold applies.** If Legal or Risk Operations need the data for a claim or a
fraud investigation, the privacy team sets the request to `on_hold`. The job skips it
and logs nothing until the hold is lifted. Data engineers never decide this themselves.

**Free text.** A few raw tables hold free text, such as merchants' descriptions of
disputes. Tagged free-text columns are scanned for the subject's email address and
names, and matching values are replaced. The scan is good, not perfect, which is why we
avoid ingesting free text where we can.

**Backfills.** Staging models exclude every subject in `privacy.erasure_log`, and the
job also cleans `raw`, so a backfill built from the warehouse cannot bring an erased
person back. Backfilling from an export or a file outside the warehouse would; see
[Backfilling historical partitions](backfills.md).

**Exports and extracts.** Data copied out of the warehouse (a CSV in someone's
downloads folder, a spreadsheet sent to a merchant) is beyond the job's reach. The
warehouse access rules forbid exporting personal data for this reason; see
[Requesting warehouse access](warehouse-access.md).

**A table is added after the request was applied.** New tables are built from staging,
which already excludes erased subjects, so they start clean.

## When the job fails

A failure posts to `#data-alerts` and to `#team-data`. It does not page, but it is the
data on-call's first job the next working morning. Most failures are a commit conflict
with another writer on the same table; the job is safe to start again for the same day:

```bash
conveyor run privacy_erasure --partition 2026-07-29
```

If a single table keeps failing, the job carries on with the others and lists the
failing table in the request's `notes`. Fix that table within the week; the request is
not complete until every table in its plan has been applied.

## Related pages

- [DPA playbook](../legal/dpa-playbook.md), for the obligations behind this page.
- [Tagging personal data columns](personal-data-columns.md), for how the job finds data.
- [Data retention schedule](retention-schedule.md), for how long records are kept.
- [Data platform overview](platform-overview.md), for the layers named above.
