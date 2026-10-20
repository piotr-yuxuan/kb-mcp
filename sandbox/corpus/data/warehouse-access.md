---
title: "Requesting warehouse access"
---

# Requesting warehouse access

Last reviewed 2026-10-02 by Signe Abernethy.

Access to the warehouse is granted through Trino roles. You sign in with your normal
Quillmoor account; the role decides what you can read. Nobody gets write access to
`raw`, `staging` or `marts` as a person: only pipelines write there.

## Roles

| Role | Can read | Approved by | Typical holder |
|---|---|---|---|
| `analyst_internal` | `marts` tables classed Internal; personal data columns are masked | Your manager | Most people who query the warehouse |
| `analyst_confidential` | `marts` tables classed Confidential, unmasked | Your manager and each table's steward | Finance analysts, Risk Operations |
| `finance_reader` | `marts.finance_*` and `marts.merchant_orders_daily`, unmasked | The finance director | Finance |
| `staging_reader` | `staging`, masked | Data Platform lead | Pipeline authors in other teams |
| `raw_reader` | `raw`, unmasked | Data Platform lead and the DPO | Data Platform engineers only |
| `privacy_officer` | `privacy`, with write access to the erasure queue | The DPO | The privacy team |

Everyone with any role can also create tables in `scratch`, prefixed with their user
name.

Data classed Restricted, which includes card numbers, is not in the warehouse at all, so
there is no role for it. The classes are explained in
[Data classification](../security/data-classification.md).

## How to ask

1. Post in `#team-data` using the pinned "access request" template:

   ```text
   Role: analyst_confidential
   Tables (if Confidential): marts.merchant_risk_profile_daily
   Why: monthly merchant risk review for Risk Operations
   Until: permanent (or a date)
   Manager: @your-manager
   ```

2. Your manager approves in the thread. For Confidential tables, the steward named in
   the data catalogue approves too (see
   [Data catalogue and table ownership](table-ownership.md)).
3. Data Platform grants the role, usually within two working days, and replies in the
   thread when it is done.

Access for a fixed period (a project, a contractor) is removed automatically on the
date given.

## Rules that come with access

- **Do not export personal data.** No CSV extracts, spreadsheets or copies of rows that
  identify a person outside the warehouse. Copies cannot be reached by the erasure job
  (see [Erasure requests in the warehouse](erasure-requests.md)). Aggregates are fine.
- **Do not share your session or put credentials in notebooks.** Services and scheduled
  jobs use service accounts whose credentials live in Strongroom; ask Data Platform for
  one.
- **Query sensibly.** Read [Keeping warehouse queries cheap](query-costs.md) before
  your first big query.

## Reviews and leavers

Warehouse roles are part of the quarterly access reviews run by Security: your manager
will be asked to confirm that you still need each role. Movers keep their roles only if
the new manager confirms them; leavers lose them with the rest of their access. The
process is described in [Quarterly access reviews](../security/access-reviews.md).

## Something is not working

If a query fails with `Access Denied`, check which role your client uses: many clients
default to the first role granted. In the Trino command-line client:

```sql
show current roles;
set role analyst_confidential;
```

Still stuck? Ask in `#team-data`, with the query and the exact error.
