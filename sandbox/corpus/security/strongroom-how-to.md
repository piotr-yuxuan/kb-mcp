---
title: "Using Strongroom"
---

# Using Strongroom

Strongroom is our secrets manager, and the only place a secret may live:
[ADR-020](../architecture/adr-020-strongroom.md) explains why. This page is the
practical side: how to sign in, read and write secrets, wire them into a service and
rotate them.

Maintained by Security. Last reviewed: 2026-09-02. Questions to `#team-security`.

## Paths

Every secret has a path of the form environment, owner, name:

| Path | Holds |
|---|---|
| `prod/card-auth/db-app` | The production database credential of `card-auth` |
| `prod/payout-gateway/bank-api-token` | The token `payout-gateway` uses with our settlement bank |
| `staging/notify/webhook-signing-key` | The webhook signing key of `notify` in `staging-eu` |
| `team/payouts/bank-portal` | A credential the Payouts team shares for a supplier's website |

Production paths start with `prod/`. Access to them is granted per path, approved by the
owning team's lead and by Security, and certified in every
[quarterly access review](access-reviews.md).

## Signing in

```bash
strongroom login
```

This opens the identity provider in your browser. Paths under `prod/` also ask for your
hardware security key. A session lasts 8 hours.

## Reading and writing

```bash
# Read the current version
strongroom get staging/notify/webhook-signing-key

# Show the versions and who created them, without the values
strongroom versions staging/notify/webhook-signing-key

# Store a new version, read from standard input so it never lands in your shell history
strongroom put team/payouts/bank-portal --from-stdin --reason "supplier reset the password"
```

People should rarely read production secrets. Every read of a `prod/` path by a person
asks for a reason, is logged, and appears in Security's weekly review of human reads.
If you find yourself reading one regularly, ask us how to automate the task instead.

## Using a secret in a service

Services never read Strongroom with a person's credentials. Each workload has its own
identity, and the Strongroom sidecar mounts the secrets named in its annotations:

```yaml
metadata:
  annotations:
    strongroom.quillmoor.example/inject: "prod/payout-gateway/bank-api-token"
```

The secret appears as a file under `/var/run/strongroom/`. When a new version is
created, the sidecar replaces the file within 90 seconds. Read the file each time you
need the value, or watch it for changes; a service that reads it only at start needs a
redeploy to pick up a rotation.

Never copy a secret into an environment variable in a manifest, a Conveyor DAG, a test
fixture or a `.env` file that is committed. The secret scanner will find it, and you
will be following the [leaked secret playbook](leaked-secret.md).

## Rotation

```bash
# Rotate now: Strongroom creates the new value and sets it on the target
strongroom rotate prod/card-auth/db-app --reason "scheduled"

# See when a secret is next rotated automatically
strongroom schedule show prod/card-auth/db-app

# Revoke an old version once nothing reads it
strongroom revoke prod/card-auth/db-app --version 17 --reason "rotation complete"
```

Production database credentials are rotated automatically every 30 days, a schedule
introduced under ENG-14. Other automatic schedules are set per path by the owning team;
service-to-service tokens default to 90 days.

During a rotation the old and the new version are both valid. Revoke the old one only
when `strongroom consumers` shows that no workload still holds it.

## Auditing

```bash
# Who read this secret over the last week?
strongroom audit prod/payout-gateway/bank-api-token --since 7d

# Which workloads hold a lease on it now?
strongroom consumers prod/payout-gateway/bank-api-token
```

## Common errors

| Message | What it means | What to do |
|---|---|---|
| `permission denied on path` | Your account or the workload's identity has no policy for that path | Request access, or add the path to the workload's policy through a pull request reviewed by Security |
| `session expired` | Your 8-hour session ended | `strongroom login` |
| `version revoked` | The version your service holds was revoked | Redeploy the service so that it reads the current version |
| `hardware key required` | You tried a `prod/` path without your key | Insert your key and sign in again |
