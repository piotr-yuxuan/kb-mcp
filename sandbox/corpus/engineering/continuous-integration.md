---
title: "Continuous integration"
---

# Continuous integration

Owner: Platform (`#team-platform`). Last reviewed: 2026-10-01.

CI runs on every push to a branch with an open change, and again on `main` after merge. Its job ends when it has produced a tested, signed container image. From there, Shipwright takes the release to production, as [how code reaches production](../release/deployment-pipeline.md) describes.

## The required checks

| Check | What it does | Typical time |
|---|---|---|
| `lint` | Ruff, golangci-lint, ESLint or ShellCheck, with the shared configuration | 1 minute |
| `types` | mypy or tsc; for Go, the compiler | 1 to 2 minutes |
| `unit` | Unit tests | 2 minutes |
| `integration` | Integration tests against PostgreSQL and Apache Kafka in containers | 5 to 8 minutes |
| `contracts` | Contract tests against every consumer | 2 minutes |
| `migrations-lint` | Rejects unsafe schema migrations | Under a minute |
| `secrets` | The secret scanner; any finding blocks the merge | Under a minute |
| `pr-size` | Counts changed lines and labels large changes | Seconds |
| `image` | Builds and signs the container image | 3 minutes |

Checks run in parallel where they can, and the whole run should finish within 15 minutes. Past that, Platform treats it as a bug in the pipeline, not in your change.

`migrations-lint` came out of ENG-10 and enforces the rules in [database migrations](../release/database-migrations.md). Findings from `secrets` are handled as [leaked secret or API key](../security/leaked-secret.md) describes, even on a branch that never merges. `pr-size` supports the size rule in the [code review guidelines](code-review.md).

## Configuration

Each repository has a `ci.yaml` that names its pipeline template and anything specific to it. Keep it short; behaviour that several teams want belongs in the templates, which Platform maintains.

```yaml
# ci.yaml in the payouts repository
template: python-service@7
services:
  - payout-gateway
  - settlement-batcher
integration:
  dependencies: [postgres, kafka, stub-bank]
extra_checks:
  - name: batch-replay
    run: python -m payout_gateway.tools.replay_check
```

## Running CI on your laptop

`qm ci run` runs the same checks in the same development container that CI uses, so a failure reproduces locally; see [local development environment](local-development.md).

```bash
qm ci run                     # every check
qm ci run unit integration    # only the checks you name
qm ci run --changed           # only the checks your diff affects
```

## When CI fails

1. Read the log of the failing step in the code host. The first error is usually the real one.
2. If the failure has nothing to do with your change, look at the Lantern dashboard "CI health" and at `#team-platform` for a known problem before retrying.
3. A test that fails and then passes on retry is flaky. Quarantine it as the [testing strategy](testing-strategy.md) says, rather than retrying until it goes green.
4. Slow or failing cache restores are covered in [build cache troubleshooting](../release/build-cache.md).

Never merge with a required check skipped. Administrators can override checks on the code host; every override is logged, and Platform reviews the list every week.

## On main

After merge, CI runs again on `main`, builds the release image and hands it to Shipwright. A red `main` blocks every deploy from that repository, so the author of the breaking change fixes or reverts it within the hour, and says which in the team channel.
