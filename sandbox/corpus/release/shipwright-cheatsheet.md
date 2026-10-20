---
title: "Shipwright CLI cheat sheet"
---

# Shipwright CLI cheat sheet

Owner: Platform (release engineering). Last reviewed: 2026-10-01.

The commands people look up most, grouped by what you are trying to do. For what the stages mean and when you may deploy, read [How code reaches production](deployment-pipeline.md). The CLI comes with the development container; `shipwright version` tells you which one you have, and `shipwright help <command>` gives every option.

## Look around

```bash
shipwright status merchant-api                      # stage, release per pod group, divergence
shipwright status merchant-api --follow             # live until the current deploy ends
shipwright releases merchant-api --env production --limit 10
shipwright logs merchant-api --env staging --since 15m
```

## Deploy

```bash
shipwright deploy merchant-api --release 12.4.0 --env staging
shipwright deploy merchant-api --release 12.4.0 --env production
shipwright deploy ledger --release 9.2.0 --env production --change CHG-2291
shipwright abort merchant-api --reason "5xx on canary"   # stop; completed waves stay
shipwright retry-canary merchant-api                       # same artefact, new canary
shipwright approve-canary merchant-api                     # only for an inconclusive verdict
```

## Undo

```bash
shipwright rollback notify --to 3.8.4 --reason "webhook signatures rejected" --incident inc-webhook-signatures
```

`shipwright rollback` is shorthand for `shipwright deploy` with an earlier `--release`, plus a confirmation prompt. The same rules apply: the release must have run in production in the last 14 days and must not predate a migration. Which way out to choose is on [Reverting a bad release](reverting-a-release.md).

## Migrations

```bash
shipwright migrate merchant-api --env staging --plan
shipwright migrate merchant-api --env production --apply --release 12.6.0
shipwright migrate merchant-api --env production --status
```

## Run a command in a pod

```bash
shipwright exec merchant-api --env staging -- ./bin/admin check-config
shipwright exec merchant-api --env production --pod canary -- ./bin/admin show-flags
```

Production `exec` sessions are recorded and posted to `#deploys`. They are for inspection and for the admin commands that runbooks name, not for editing files in a running pod.

## Hotfixes and the train

```bash
shipwright hotfix start merchant-api --from 12.6.0     # registers hotfix/merchant-api-12.6.1
shipwright hotfix finish merchant-api                  # checks the fix is on main
shipwright train show --next
shipwright train hold merchant-api --reason "waiting on ENG-30 contract tests"
```

See the [hotfix process](hotfix-process.md) and the [Release train FAQ](release-train-faq.md).

## Build cache

```bash
shipwright build merchant-api --no-cache
shipwright cache stats merchant-api
```

More on [Build cache troubleshooting](build-cache.md).

## Options you will type often

| Option | Meaning |
|---|---|
| `--env` | `staging` or `production` |
| `--release` | The version to deploy, for example `12.4.0` |
| `--change` | The `CHG-` ticket, for high-risk changes and freezes |
| `--incident` | The incident channel, for work outside the deploy windows |
| `--reason` | Free text; required for `abort`, `rollback` and redeploys in production |
| `--dry-run` | Print what would happen and stop |

## Errors you will meet

| Message starts with | Meaning |
|---|---|
| `production stages are closed` | Outside the deploy windows or in a freeze |
| `change ticket required` | The service or migration is high-risk; pass `--change` |
| `pending migrations` | Run or let the pipeline run `shipwright migrate` first |
| `service diverged from main` | An earlier release was redeployed; land the revert commit |
| `release predates migration` | Roll forward instead |
