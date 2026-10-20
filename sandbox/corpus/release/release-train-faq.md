---
title: "Release train FAQ"
---

# Release train FAQ

Owner: Platform (release engineering). Last reviewed: 2026-10-08. Ask anything that is not here in `#team-platform`, and we will add it.

### What is the release train?

An automatic release for every service that opts in. At each departure, Shipwright looks at every service with `train: true` in its `shipwright.yaml`, cuts a release from main for each one that has new merged commits, bumps its minor version, and sends it down the pipeline. Nobody has to remember to deploy, and changes go out in small batches instead of piling up.

### When does it leave?

Twice a day, Monday to Thursday: at **10:00** and at **13:30** UK time. The 13:30 train reaches its canary at around 14:10 and finishes its rollout before the deploy windows close at 16:00. There is no Friday train, because there are no Friday deploys; the windows themselves are on [How code reaches production](deployment-pipeline.md).

### Which services ride it?

Most of them. Services marked `risk: high` do not, because their production deploys need a `CHG-` ticket and a named person watching; their teams deploy by hand. Anyone can deploy a train service by hand too, inside the windows.

### I missed the train. What now?

Take the next one, or deploy your service yourself with `shipwright deploy` if it cannot wait three hours. The train is a convenience, not a gate.

### How do I see what is on the next train?

```bash
shipwright train show --next
```

It lists each service, the release it will cut and the commits it will include, with their authors.

### Can I keep my service off a train?

Yes, for the day:

```bash
shipwright train hold merchant-api --reason "waiting on ENG-30 contract tests"
```

A hold lasts until you release it with `shipwright train release merchant-api`, or until the end of the day, whichever comes first. Holds are listed in `#deploys` so that nobody is surprised.

### Who watches a train release?

Shipwright posts each stage in the owning team's channel and tags the authors of the commits on board. The team's on-call engineer is expected to watch the canary; the authors are expected to be reachable. Release engineering watches the train as a whole, not each service.

### The canary failed and my commit is innocent. What happens?

The canary failure stops that service's release only. The commits stay on main, and the service is held off later trains until someone from the team has looked. Find the culprit, revert it or fix it, and release the hold. If the failure was noise, [Canary analysis thresholds](canary-analysis.md) explains how to ask for a second look.

### How are train releases numbered?

The train bumps the minor version: 12.4.0, then 12.5.0. Hotfixes bump the patch version (12.5.1); see the [hotfix process](hotfix-process.md). Major versions are always bumped by hand.

### Does the train run during a change freeze?

No. It stops on the first day of each freeze and restarts on the first deploy day after it; see [Change freeze calendar 2026](change-freeze-2026.md).

### Do flag changes ride the train?

No. Flag values change in Switchboard, not in a release; see [Feature flags and kill switches](feature-flags.md). Declaring a new flag in `switchboard.yaml` does ride the train, because it is part of the code.

### My service has a migration on main. Will the train run it?

Yes, as part of the release, before the canary, exactly as a manual deploy would. If the migration makes the release high-risk, the train skips the service and tells you to deploy it by hand with a ticket.

### Why 10:00 and 13:30, not every hour?

We tried hourly trains for two months in 2025. Releases overlapped, canaries ran on top of each other's rollouts, and nobody could tell which train had caused what. Two a day is enough for most teams, and anyone can deploy by hand in between.
