---
title: "Database migrations"
---

# Database migrations

*Owner: Platform (release engineering); Ledger reviews every change to ledger schemas. Channel: `#team-platform`. Last reviewed: 2026-07-21.*

Every service owns its own PostgreSQL database ([ADR-012](../architecture/adr-012-database-per-service.md), [ADR-004](../architecture/adr-004-postgresql.md)), and every change to a schema is a migration: a numbered SQL file in the service's repository, applied by Shipwright. This page is the rulebook. It is short on theory and long on the mistakes that taught us each rule.

## The rules

1. **Expand, then contract.** Add the new shape, move the code over, and only then remove the old shape, each step in its own release.
2. **Never drop a column in the release that stops using it.** The release that stops reading and writing a column ships first; the drop comes in a later release, once nothing running uses the column.
3. **Migrations run through `shipwright migrate`.** Nobody runs schema statements against a production database by hand, including during incidents.
4. **Every migration must be safe while the previous release serves traffic.** Old and new code run side by side for most of an hour during every deploy.
5. **Down migrations exist, but they are a last resort.** Recovery from a bad migration is normally a new forward migration.
6. **Schema changes on payments databases need a `CHG-` ticket.** That means `card-auth`, `ledger`, `payout-gateway` and `settlement-batcher`, plus large tables anywhere; the full list of high-risk changes is on [How code reaches production](deployment-pipeline.md).

## Why expand then contract

During a deploy, the old and the new release run at the same time against the same database: a few pods during the canary, then more and more during the rollout. If a release is reverted, the old code meets whatever schema the new release left behind. So every migration must keep both the previous release and the new one working, and expand then contract is the pattern that guarantees it.

The **expand** step only adds: new tables, new nullable columns, new indexes. Old code ignores them. The **contract** step only removes, and only once no running release needs what it removes. Between the two, code moves from the old shape to the new one, as many releases as it takes.

## Worked example: renaming a column

Task: rename `merchants.legal_name` to `merchants.registered_name` in `merchant-api`.

A rename in one statement (`ALTER TABLE ... RENAME COLUMN`) breaks every pod of the old release at the moment it runs. Instead it takes four releases.

### Release 1: expand

```sql
-- migrations/0150_add_registered_name.up.sql
SET lock_timeout = '2s';
ALTER TABLE merchants ADD COLUMN registered_name text;
```

The code in release 1 writes both columns and still reads `legal_name`.

### Release 2: copy, then switch reads

Existing rows need the new column filled in. Do it in batches, so that no single statement holds locks or bloats the table for long:

```sql
-- migrations/0151_copy_registered_name.up.sql
-- shipwright: batched, repeat-until-zero, pause_ms=200
UPDATE merchants
SET registered_name = legal_name
WHERE id IN (
    SELECT id
    FROM merchants
    WHERE registered_name IS NULL
    ORDER BY id
    LIMIT 10000
);
```

The header comment tells Shipwright to repeat the statement until it updates no rows, pausing 200 ms between batches. The code in release 2 reads `registered_name` and still writes both columns.

### Release 3: stop using the old column

The code neither reads nor writes `legal_name`. **This release carries no migration.** It is the release that stops using the column, so it must not drop it: while release 3 is in its canary, release 2 is still serving most traffic and still writing `legal_name`.

### Release 4: contract

Once release 3 has been at 100% in production for at least one full working day, and nothing else reads the column:

```sql
-- migrations/0152_drop_legal_name.up.sql
SET lock_timeout = '2s';
ALTER TABLE merchants DROP COLUMN legal_name;
```

"Nothing else" includes the warehouse. Tell Data Platform before you drop or rename a column they ingest; otherwise they find out from a `DQ-044` alert ([Data quality alerts](../data/quality-alerts.md)).

Four releases sounds slow. In practice they ship over a week or two, each one small and dull, which is how database changes ought to feel.

## Running migrations with Shipwright

Migrations live in `migrations/` as `NNNN_description.up.sql`, each with a matching `NNNN_description.down.sql`. Shipwright records what has been applied in a `shipwright_migrations` table in each database.

```bash
# What would run against staging?
shipwright migrate merchant-api --env staging --plan

# Apply to staging (the pipeline normally does this during the staging stage)
shipwright migrate merchant-api --env staging --apply

# Production: normally run by the pipeline after staging and before the canary
shipwright migrate merchant-api --env production --plan
shipwright migrate merchant-api --env production --apply --release 12.6.0

# What has been applied, when, and by which release?
shipwright migrate merchant-api --env production --status
```

The pipeline applies a release's pending migrations after the staging stage and before the canary, and it will not start the canary while any are pending. You may run `--apply` by hand ahead of a deploy, for example to run a long expand migration early in the morning, but only inside the deploy windows and only for migrations that belong to a release already in staging.

A plan looks like this:

```text
$ shipwright migrate merchant-api --env production --plan
database: merchant_api (primary, active region)
pending:
  0150_add_registered_name   ADD COLUMN   lock: ACCESS EXCLUSIVE (brief)   estimate: under 1s
lint: ok (7 rules checked)
change ticket: not required
```

## The migration linter

Since epic ENG-10 (Zero-downtime database migrations, ENG Sprints 22 to 30, February to June 2026), every pull request that touches `migrations/` runs the linter, and Shipwright runs it again at the build stage. It blocks:

| Rule | Blocks |
|---|---|
| `drop-column-same-release` | dropping a column that code in the same release stopped using, found by comparing the release with the one before it |
| `rename-column` | `RENAME COLUMN` and `RENAME TO` on tables in use |
| `index-not-concurrent` | `CREATE INDEX` without `CONCURRENTLY` on an existing table |
| `not-null-without-default` | adding a `NOT NULL` column with no default |
| `missing-lock-timeout` | schema statements without `SET lock_timeout` |
| `type-change` | changing a column's type in place |
| `mixed-schema-and-data` | schema changes and data changes in the same file |

`drop-column-same-release` came from the main story of ENG-10 and is the rule that fires most often. When it fires, it is right: move the drop to a later release. A suppression needs a comment with the reason and a platform reviewer's approval. We have granted two in 2026, both for columns that no released code had ever read.

## Locks and timeouts

PostgreSQL takes an `ACCESS EXCLUSIVE` lock for most forms of `ALTER TABLE`. The change itself may be instant, but the statement waits behind any long-running query on the table, and every query that arrives meanwhile waits behind the statement. That is how a one-millisecond migration takes a service down.

So:

- Start every schema migration with `SET lock_timeout = '2s'`. Shipwright retries a lock timeout up to five times with a growing pause. If it still cannot take the lock, the migration fails cleanly and nothing has changed. Find the long query on the service's Lantern database dashboard and try again.
- Create indexes with `CREATE INDEX CONCURRENTLY`. Shipwright detects such files and runs them outside a transaction. If a concurrent build fails, it leaves an invalid index behind; remove it with `DROP INDEX CONCURRENTLY` in a new migration and try again.
- Add foreign keys and check constraints as `NOT VALID`, then `VALIDATE CONSTRAINT` in a later migration, which does not block writes.
- Never change a column's type in place. Add a new column and treat it as a rename.

## Large tables

A migration that rewrites or locks a table of more than 50 million rows is high-risk whatever the service, and needs a `CHG-` ticket ([Raising a change ticket](change-tickets.md)). For those:

- Data changes run in batches, as in release 2 above, never as one statement.
- Plan them for the morning of a deploy day, so that a slow run finishes well inside the window.
- Watch replication lag to the passive region while they run; Shipwright pauses a batched migration when lag exceeds 30 seconds.
- Run the whole sequence in `staging-eu` first, against a copy of the table at production size if the seed data is too small to show the timing.

The 2026 ledger schema migration, `CHG-2291`, is the example we point people to: it followed expand then contract over two months and is described on the change tickets page.

## Down migrations

Every `up.sql` has a `down.sql`, and the linter checks that it exists. Down migrations are there for local development and `staging-eu`, where resetting a schema is routine, and for the rare production case where no forward fix is possible.

In production they are a last resort because:

- a down migration that drops a column added by its up migration destroys everything written to that column since;
- it runs against a schema that may have moved on since the up migration;
- it is the least tested code in the repository.

Running one in production needs a `CHG-` ticket approved by the head of platform engineering, and the service's owning team present:

```bash
shipwright migrate ledger --env production --down 0098 --change CHG-NNNN
```

If you are here because a release with a migration went wrong, the answer is almost always to roll forward; see [Reverting a bad release](reverting-a-release.md).

## Personal data

When a migration adds a column that holds personal data, tag it as described in [Tagging personal data columns](../data/personal-data-columns.md). The linter warns about new columns whose names look personal (`email`, `name`, `phone`, `address`, `date_of_birth`) and carry no tag.

## Before you merge

1. Expand and contract are in separate releases.
2. No column is dropped in the release that stops using it.
3. `lock_timeout` is set and indexes are built concurrently.
4. The `down.sql` exists and has been run in `staging-eu`.
5. The previous release has been tested against the new schema (the compatibility suite in the test stage does this if your service has enabled it).
6. There is a `CHG-` ticket if the database or the table size calls for one.
7. Data Platform knows about any drop or rename of an ingested column.
8. Personal data columns are tagged.
9. Ledger has reviewed anything that touches a ledger schema.

## History

Until 2024 each team ran migrations its own way, some at service start-up, which meant the canary pods migrated the schema under the feet of the baseline. Moving every service to `shipwright migrate` took most of 2024. The linter arrived with ENG-10 in 2026, after three incidents in one quarter caused by a dropped column that the previous release still read.
