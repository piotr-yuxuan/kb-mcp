---
title: "Staging environments"
---

# Staging environments

Owner: Platform. Last reviewed: 2026-08-26.

## staging-eu

`staging-eu` is Quillmoor's single shared staging environment. Every service runs there, deployed by the staging stage of Shipwright ([How code reaches production](deployment-pipeline.md)), on its own Kubernetes cluster with its own databases, Switchboard values and Strongroom paths. Nothing in it can reach production, and nothing in production can reach it.

| What | Where |
|---|---|
| Services | `https://<service>.staging-eu.quillmoor.example` |
| Merchant Hub | `https://hub.staging-eu.quillmoor.example` |
| Emails sent by `notify` | `https://mail.staging-eu.quillmoor.example`, a sink that catches every message |
| Dashboards | Lantern, with the environment selector set to `staging-eu` |

## Data is refreshed weekly

Every Sunday from 20:00 UK time, all `staging-eu` databases are reset to the synthetic seed set, and the test merchants are recreated ([Test merchants and test cards](../payments/test-merchants.md)). The refresh takes about two hours, during which staging is unavailable and staging deploys wait.

What that means for you:

- Anything you created during the week, such as merchants, payments, payouts or webhooks, is gone on Monday morning.
- If a test needs data that survives, add it to the seed set with a pull request to the `staging-seed` repository. It will then be there after every refresh.
- Do not plan a staging soak or a long-running experiment across Sunday evening.

The data is synthetic. Staging holds no real merchant data, no personal data and no PANs, and nobody may copy any of those into it, even "just for one test".

## What is simulated

Outside parties are replaced by simulators, so that tests behave the same way every time:

- an issuer simulator, which approves, declines or times out according to the test card used;
- a settlement bank simulator, which accepts settlement files and produces statements;
- a webhook receiver that merchants' test endpoints can point at.

Simulated latency is low. Staging tells you whether something works, not how fast it will be in production; that is the canary's job.

## Flags in staging

Switchboard values in `staging-eu` are independent of production and are not reset by the weekly refresh. If you turn a flag on in staging to test it, turn it off again, or leave a note in your team channel. How flags work is on [Feature flags and kill switches](feature-flags.md).

## Preview environments

Merchant Hub pull requests get a preview at `https://pr-<number>.hub.preview.quillmoor.example`: the front end only, built from the branch and talking to the `staging-eu` APIs. Previews are deleted when the pull request closes.

## Sharing nicely

- Load tests in staging need a slot agreed in `#team-platform`, because they slow everyone's staging stage.
- Do not leave a service scaled to zero or pinned to an old release in staging; the next person's deploy will fail in confusing ways.

## History

There used to be a `staging-uk` as well. It was retired in March 2025 to stop two environments drifting apart. Any runbook that still mentions it is out of date; please fix it or tell its owner.
