---
title: "Local development environment"
---

# Local development environment

> [!NOTE]
> Owned by the Platform team; ask in `#team-platform`. Last reviewed: 2026-10-07, for `qm` 2.14.

This page explains how to run Quillmoor services on your laptop: the `qm` command, the development containers that every repository ships, and the seed data that makes a fresh environment look like a small, believable Quillmoor. If you only want the commands, start with the short version and come back when something breaks.

## The short version

```bash
qm doctor                         # checks the container runtime, memory, disk and access
cd ~/src/payouts                  # any team repository
qm dev up                         # dependencies, the development container, migrations
qm dev seed --profile payments    # synthetic merchants, payments, payouts and journals
qm dev status                     # what is running, and on which port
```

`qm dev up` is safe to run again at any time. After a pull, it starts what is missing, rebuilds what changed and applies any new migrations, and leaves everything else alone.

## How it fits together

Each team has one repository ([ADR-005](../architecture/adr-005-repository-per-team.md)), and each repository has two files that `qm` reads:

- `qm.yaml`, the stack file, lists the services in the repository, the dependencies they need and the seed profile they expect.
- `.devcontainer/devcontainer.json` describes the development container in which the code is built, run and tested.

`qm dev up` reads the stack file, starts the dependencies as containers on a private network called `qm-dev`, builds or pulls the development container, applies migrations the same way `shipwright migrate` does in staging, and then starts the repository's services inside the development container with live reload. Everything listens on `127.0.0.1` only.

```yaml
# qm.yaml in the payouts repository
version: 2
services:
  payout-gateway:
    language: python
    command: ["python", "-m", "payout_gateway", "--reload"]
    port: 8040
    database: payout_gateway
  settlement-batcher:
    language: python
    command: ["python", "-m", "settlement_batcher", "--reload"]
    port: 8041
    database: settlement_batcher
dependencies:
  - postgres
  - kafka
  - stub-bank
  - switchboard-local
  - ledger          # the Ledger team's latest main image, not built from source
seed:
  profile: payments
  version: 2026.10.1
```

## Before you start

| Need | Detail |
|---|---|
| Memory | 32 GB recommended; 16 GB is enough for one repository with the `minimal` profile |
| Disk | 40 GB free for images, volumes and caches |
| Container runtime | Installed with the standard laptop image; `qm doctor` checks its version |
| `qm` | Version 2.14 or later |
| Strongroom | Read access to the `dev/` namespace, requested with your other accounts through the [new engineer checklist](new-engineer-checklist.md) |
| Registry | Pull access to `registry.quillmoor.example`, which comes with the engineering group on the code host |

Install or update `qm`:

```bash
curl -fsSL https://tools.quillmoor.example/qm/install.sh | sh
qm version          # prints the version and tells you if a newer one exists
qm doctor           # run this before asking for help, and paste its output
```

## The `qm dev` commands

| Command | What it does |
|---|---|
| `qm dev up` | Start dependencies, the development container and the repository's services; apply migrations |
| `qm dev up --except card-auth` | Start everything except one service, which you then run yourself |
| `qm dev down` | Stop everything, keeping volumes and data |
| `qm dev status` | List containers, ports and health checks |
| `qm dev logs payout-gateway -f` | Follow one service's logs |
| `qm dev shell` | Open a shell inside the development container |
| `qm dev seed --profile payments` | Load a seed profile into the local databases |
| `qm dev reset --db ledger` | Drop and recreate one database, migrate it and seed it again |
| `qm dev reset --all` | Remove every volume; the next `qm dev up` starts from nothing |
| `qm dev env payout-gateway` | Print the environment a service runs with, for your editor's run configuration |
| `qm dev secrets pull` | Fetch development secrets from Strongroom |
| `qm dev flags set NAME on` | Switch a flag in the local Switchboard |
| `qm dev stub set NAME KEY=VALUE` | Change how a stub behaves |
| `qm dev rebuild` | Rebuild the development container after a change to `.devcontainer/` |

Every command takes `--help`, and `qm dev status --all` shows the stacks of every repository you have started, which is the first thing to check when the laptop slows down.

## Development containers

The development container is where your code runs locally. It is built from the same base image that CI uses, so "works on my machine" and "works in CI" mean the same thing. The images are `registry.quillmoor.example/devcontainers/python:3.13` and `registry.quillmoor.example/devcontainers/go:1.26`, rebuilt every week with security patches.

Each image carries the language toolchain at the baseline version in the [coding standards](coding-standards.md), the linters and type checkers that CI runs, `psql`, `kcat`, ShellCheck and `qm` itself. Your source tree is mounted into the container from your disk, so you edit files as usual; package and build caches live in named volumes, so they survive `qm dev rebuild`.

Most editors can attach to a running development container through the open Dev Container specification, and then run tests, debuggers and language servers inside it. If yours cannot, `qm dev shell` gives you a terminal inside the container, working on the same files.

```json
{
  "name": "payouts",
  "image": "registry.quillmoor.example/devcontainers/python:3.13",
  "runArgs": ["--network=qm-dev"],
  "mounts": [
    "source=qm-uv-cache,target=/home/dev/.cache/uv,type=volume"
  ],
  "postCreateCommand": "uv sync --frozen",
  "containerEnv": {
    "QM_ENV": "local"
  }
}
```

A change to `.devcontainer/` is reviewed like any other code. Keep repository-specific additions small: a tool that more than one team needs belongs in the base image, which Platform maintains, and you can ask for it in `#team-platform`.

## What runs beside your code

| Dependency | Local port | Notes |
|---|---|---|
| PostgreSQL 16 | 5432 | One database per service ([ADR-012](../architecture/adr-012-database-per-service.md)); user `dev`, password from `qm dev env` |
| Apache Kafka | 9092 | A single broker; topics are created from each repository's topic list on `qm dev up` |
| `stub-issuer` | 8081 | Answers card authorisations for the test cards, and can be told to be slow or to fail |
| `stub-bank` | 8082 | Accepts payout batches and settlement files, and acknowledges them after a configurable delay |
| `switchboard-local` | 8083 | Reads flags and kill switches from `flags.local.yaml` |
| `strongroom-dev` | 8084 | Serves the secrets fetched by `qm dev secrets pull` |
| OpenTelemetry collector | 4317 | Receives traces; `qm dev traces` opens a local trace viewer |

Services from another team's repository run from that team's latest `main` image, not from source. If you need a change in someone else's service at the same time as your own, run their repository's `qm dev up` in a second terminal: `qm` notices the shared network and replaces the image with the source build.

The stubs let you exercise failure paths without waiting for one to happen in staging:

```bash
# make the issuer stub answer slowly, to watch card-auth time out
qm dev stub set stub-issuer delay_ms=3500
# make the bank stub stop acknowledging payout batches
qm dev stub set stub-bank ack=never
# back to the defaults
qm dev stub reset
```

The errors these provoke, and what on-call does about them in production, are explained in the payments runbooks, such as [card authorisation latency](../payments/card-auth-latency.md).

## Seed data

A fresh database is empty, and an empty Merchant Hub tells you nothing. Seed profiles fill the local databases with synthetic data that is consistent across services: the ledger's journals match the payments, and the payouts match the ledger.

| Profile | What it loads | Load time |
|---|---|---|
| `minimal` | One merchant, one user, no transactions | A few seconds |
| `payments` | The sandbox test merchants, with 30 days of payments, refunds, payouts and journals | About a minute |
| `merchant-hub` | Merchants with users in every role, for the dashboard | About 30 seconds |
| `full` | Everything above, plus 90 days of history for reports | About five minutes |

The merchants are the ones described in [test merchants and test cards](../payments/test-merchants.md), with the same identifiers, so that a test written against your laptop runs unchanged against staging.

Rules for seed data:

- **It is generated, never copied.** The generator builds it from a fixed random seed, so the same seed version gives the same rows on every laptop. No row ever comes from production or from a staging database.
- **People are invented.** Names come from a list of made-up names, email addresses are on `example.com`, and the only card numbers are the published test cards.
- **It is versioned.** `seed.version` in `qm.yaml` pins it. When a migration changes a seeded table, the owning team publishes a new seed version in the same release.

To add rows for your own work, extend a profile in the repository's `seed/` directory rather than inserting them by hand, so that your teammates get them too:

```python
# seed/payouts_extra.py
from qm_seed import Profile, merchants, payouts

profile = Profile.extend("payments")


@profile.step(after="payouts")
def held_payouts(ctx):
    """A new seller with held payouts, for the payout holds screen."""
    seller = merchants.new_seller(ctx, onboarded_days_ago=2)
    for _ in range(3):
        payouts.create(ctx, seller=seller, status="held")
```

Load it with `qm dev seed --profile payments --extra seed/payouts_extra.py`.

## Running one service from source

When you want a debugger on one service, run everything else in containers and that one from your editor:

```bash
qm dev up --except fx-quote
qm dev env fx-quote > .env.local    # .env.local is ignored by Git
go run ./cmd/fx-quote
```

The service reaches its dependencies on the published ports, and other services reach it through a host alias that `qm` points at your laptop.

## Secrets and flags

Services read secrets through the same client locally as in production. `qm dev secrets pull` fetches values from Strongroom's `dev/` namespace only: credentials for the stubs, signing keys for local webhooks, and the like. `qm` refuses any path outside `dev/`, and no production secret is ever needed on a laptop ([ADR-020](../architecture/adr-020-strongroom.md)). Pulled secrets are cached in the development container for 12 hours, then fetched again.

Flags and kill switches start from their defaults in `flags.local.yaml`. Switch one with `qm dev flags set`, and see what is set with `qm dev flags list`. Local flags never reach Switchboard itself, so you cannot change anything outside your laptop by mistake.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `qm dev up` stops at "waiting for kafka" | The broker needs more memory than is free | Close another stack, or use the `minimal` profile |
| Port 5432 already in use | A PostgreSQL installed outside `qm` | Stop it, or set `QM_POSTGRES_PORT` |
| Migrations fail after switching branch | The database is ahead of the branch's migrations | `qm dev reset --db NAME` |
| Seed fails on a missing column | The seed version is older than the schema | Pull, then check `seed.version` in `qm.yaml` |
| Image pulls are slow or time out | The registry or the build cache | See [build cache troubleshooting](../release/build-cache.md) |
| Everything is slow | Too many stacks running | `qm dev status --all`, then `qm dev down` the ones you do not need |

When you ask for help in `#team-platform`, attach the output of `qm doctor --report`. It collects versions, container state and recent errors, with secrets removed, and saves a round of questions.
