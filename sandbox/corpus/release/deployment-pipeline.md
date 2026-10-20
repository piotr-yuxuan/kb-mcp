---
title: "How code reaches production"
---

# How code reaches production

**Owner:** Platform team, release engineering (`#team-platform`)
**Accountable:** Bram Oyelaran, head of platform engineering
**Last reviewed:** 2026-09-29

Every change to a production service at Quillmoor takes the same road. It is merged, Shipwright picks it up, and it passes through five stages: **build**, **test**, **staging**, **canary** and **full rollout**. Nothing reaches merchants by any other road: there is no shell access to production pods for deploying, no hand-edited Kubernetes manifest and no quick copy of a binary "just this once".

This page explains each stage, when you are allowed to deploy, which changes need extra paperwork, and what to watch while your release goes out. If a release has already gone wrong, go to [Reverting a bad release](reverting-a-release.md). If you need a fix out fast, read the [hotfix process](hotfix-process.md) first.

## The road at a glance

| Stage | What happens | Typical time | Stops the release when |
|---|---|---|---|
| Build | Shipwright builds and signs the container image from the merge commit and records the release | 4 to 8 minutes | the build fails or the image is unsigned |
| Test | Unit, integration and contract suites run against the built image | 10 to 15 minutes | any required suite fails |
| Staging | The release is deployed to `staging-eu`, smoke tests run, then a 15-minute soak | about 20 minutes | smoke tests fail or staging alerts fire |
| Canary | 5% of production traffic for 30 minutes, compared with the current release | 30 minutes | canary analysis fails |
| Full rollout | The release replaces the current one in three waves | about 25 minutes | an alert fires or someone stops it |

From merge to 100% of traffic, a typical release takes about 90 minutes. Most of that is waiting, and the waiting is the point.

## Stage by stage

### Build

Shipwright builds from a merge commit on the main branch, or on a registered hotfix branch (see the [hotfix process](hotfix-process.md)), never from a working copy. The resulting image is signed and stored with a release record: the service name, the version from `shipwright.yaml`, the commit and the build time. A release is immutable. If you need to change anything, even a single configuration value, you make a new release.

Releases are named by the service's version, for example `merchant-api` 12.4.0, and Shipwright tags the commit `merchant-api-12.4.0`. The version must be higher than every release already recorded for that service; Shipwright refuses a duplicate.

Slow or strange builds are usually the cache. See [Build cache troubleshooting](build-cache.md).

### Test

The test stage runs the suites listed in `shipwright.yaml` against the image that was just built, not against the source tree. That catches a class of problems that the checks on a pull request cannot see: a file missing from the image, the wrong base image, a binary built for the wrong architecture. The suites themselves are the same ones that run on every pull request; see [Continuous integration](../engineering/continuous-integration.md) and the [testing strategy](../engineering/testing-strategy.md).

A test marked as quarantined is reported but does not block. Quarantine is for flaky tests with an open ticket, not for tests you disagree with.

### Staging

Shipwright deploys the release to `staging-eu`, runs the service's smoke tests, then holds the release in staging for a 15-minute soak while Lantern watches the staging alerts. What lives in staging, and how often its data changes, is on [Staging environments](staging-environments.md).

A release can wait in staging for up to 24 hours. After that it expires and must be deployed to staging again, so that nobody promotes a day-old release into a production that has moved on.

### Canary

The canary takes **5% of production traffic for 30 minutes**. Shipwright starts canary pods next to the pods running the current release, sends 5% of requests to them, and compares the two groups minute by minute. If the canary is worse than the baseline by more than the agreed thresholds, Shipwright stops the release and sends all traffic back to the current pods, usually in under a minute. The thresholds, and how they are computed, are on [Canary analysis thresholds](canary-analysis.md).

The share and the duration are the same for every service. Teams sometimes ask for a shorter canary for "trivial" changes; the answer is no, because the trivial changes are the ones nobody looks at closely. Teams with very little traffic should read the canary analysis page, which explains what happens when 30 minutes is not enough data to judge.

The canary has worked this way since epic ENG-7 (ENG Sprints 3 to 10, May to August 2025). Before that it was a 10-minute look at dashboards by whoever was deploying, and it missed most of the regressions it was meant to catch.

### Full rollout

When the canary passes, Shipwright rolls the release out in three waves: 25%, 50% and 100% of pods, with a 10-minute pause after each of the first two. Kubernetes replaces pods gradually inside each wave ([ADR-010](../architecture/adr-010-kubernetes.md)). The active region is updated first and the passive region last, so that a failover during a rollout lands on a known release ([ADR-021](../architecture/adr-021-active-passive-regions.md)).

You can stop a rollout at any time with `shipwright abort`. Stopping leaves the waves already completed in place; it does not undo them. Undoing is a separate decision, covered in [Reverting a bad release](reverting-a-release.md).

## Deploy windows

Production deploys run **Monday to Thursday, 09:00 to 16:00 UK time**.

In practice:

- Shipwright will not start the canary or the full rollout outside the window. Build, test and staging run at any hour, so you can prepare a release on Friday and promote it first thing on Monday.
- A rollout that started inside the window is allowed to finish after 16:00. Do not treat that as a loophole: a canary started at 15:55 means finishing the rollout at half past five with half the team gone.
- The window follows UK clock changes. For colleagues in Paris it is 10:00 to 17:00 all year round.
- There are no production deploys on Fridays, at weekends or on UK bank holidays. On the working day before a bank holiday, the window closes at 12:00.
- During a change freeze the window is closed altogether; see the [2026 freeze calendar](change-freeze-2026.md).

Outside the window, Shipwright answers like this:

```text
$ shipwright deploy merchant-api --release 12.4.0 --env production
error: production stages are closed (window Mon-Thu 09:00-16:00 Europe/London; now Fri 10:12)
hint: for a declared SEV1 or SEV2, pass --incident <channel>; the IC approves in Shipwright
```

The only way through is a declared SEV1 or SEV2 with the IC's approval, and even then you follow the [hotfix process](hotfix-process.md). Severities are defined on [Production incident management](../incidents/incident-management.md).

Flags and kill switches are not deploys. Turning a feature off, or engaging a kill switch, never waits for the window; see [Feature flags and kill switches](feature-flags.md) for the rules on turning things on.

## High-risk changes need a CHG- ticket

Some changes are risky enough that someone outside the team must look at the plan before the canary starts. These need a `CHG-` ticket in the Change Register, approved before you promote to production:

- a schema migration on the database of `card-auth`, `ledger`, `payout-gateway` or `settlement-batcher`;
- any migration that rewrites or locks a table of more than 50 million rows, whatever the service;
- changes to Kubernetes node pools, cluster versions, ingress or network policy (the Kubernetes 1.31 upgrade, epic ENG-9, ran under a series of change tickets);
- changes to Strongroom policies, or to which secrets a production service can read;
- the first production deploy of a new service;
- anything deployed under a change freeze exception.

Shipwright checks. For a service marked `risk: high`, or a release containing a migration on one of the databases above, it asks for the ticket:

```bash
shipwright deploy ledger --release 9.2.0 --env production --change CHG-2291
```

and refuses to start the canary unless the ticket is Approved or Scheduled and names that service. How to raise one and get it approved is on [Raising a change ticket](change-tickets.md).

What does not need a ticket: ordinary code changes, including ones that ship dark behind a flag; configuration changes reviewed in a pull request; flag and kill switch changes.

## The service's pipeline file

Each repository holds a `shipwright.yaml` at its root. Release engineering's linter checks it on every pull request.

```yaml
service: merchant-api
owners: [merchant-experience]
version: 12.4.0
risk: standard          # "high" makes every production deploy ask for a CHG- ticket
train: true             # ride the release train; see the release train FAQ
stages:
  test:
    suites: [unit, integration, contract]
  staging:
    environment: staging-eu
    smoke: ./scripts/smoke.sh
    soak_minutes: 15
  canary:
    traffic_percent: 5
    duration_minutes: 30
    extra_checks: [webhook_delivery_success]
  rollout:
    waves: [25, 50, 100]
    wave_pause_minutes: 10
migrations:
  path: migrations/
```

The `canary` block is there so that the values are visible in review; the linter rejects anything other than 5 and 30. `extra_checks` may add service-specific checks to the canary analysis but cannot replace the default ones. The `train` key is explained in the [Release train FAQ](release-train-faq.md).

A release that includes a migration runs it with `shipwright migrate` before the canary, and Shipwright will not start the canary while the release has pending migrations. The rules for writing migrations are on [Database migrations](database-migrations.md).

## Watching your release

You deployed it, so you watch it, from the start of the canary until the last wave completes:

1. Keep `shipwright status merchant-api --follow` open. It shows the stage, the canary verdict as it evolves, and each wave.
2. Open the Lantern dashboard "Shipwright deploys" (`https://lantern.quillmoor.example/d/shipwright-deploys`) next to your service's own dashboard. Every stage change appears as an annotation on every Lantern graph for that service.
3. Follow `#deploys` in chat, where Shipwright posts each stage and verdict. Your team channel receives the same messages for your services.
4. Stay reachable until the rollout ends. If you are paged during your own rollout, stop the rollout first and investigate second. The paging rules are on [On-call rota and paging policy](../incidents/on-call.md).

If the release becomes part of an incident, the IC decides what happens next, not the person who deployed.

## Edge cases and questions we get

**Two releases of the same service at once.** Shipwright runs one production deploy per service at a time. The second release waits at the end of staging and continues when the first finishes or is stopped. If the first was stopped, the second is not promoted automatically: someone must decide whether it still makes sense.

**Services that depend on each other.** Shipwright does not coordinate releases across services. Deploy the provider of a new interface first, make the consumer tolerate both the old and the new behaviour, and switch the new path on with a flag. Never plan a change that only works if two services go out in the same minute.

**A canary that fails for reasons outside your change.** It happens: an issuer slows down during your canary and both groups suffer, but not evenly. Read the canary analysis output before trying again. If the baseline was just as bad, run `shipwright retry-canary merchant-api`; the release is the same artefact and needs no rebuild.

**Configuration-only changes.** These are releases too, and they go through all five stages, canary included. That is slower than editing a value in place, and it is meant to be.

**Releases built before a freeze.** A release that was built and staged before a freeze starts gains no right to go out during it.

**Redeploying an earlier release.** This is the one case where Shipwright skips build, test and staging, because the artefact already passed them. When and how to do it is on [Reverting a bad release](reverting-a-release.md).

## History

- **2019.** Shipwright replaces the deploy scripts that each team kept in its own repository.
- **2022.** A canary stage is added, as a manual check.
- **2023.** Deploy windows are introduced after a run of late-evening releases that paged people overnight.
- **2025.** Epic ENG-7 gives the canary its current shape and automated analysis. Epic ENG-8 adds the kill switch audit log to Switchboard.
- **2026.** Epic ENG-10 adds the migration linter to the pipeline (ENG Sprints 22 to 30, February to June 2026).

Questions and suggestions go to `#team-platform`. Changes to this page are reviewed by release engineering.
