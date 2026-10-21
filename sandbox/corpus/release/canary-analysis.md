---
title: "Canary analysis thresholds"
---

# Canary analysis thresholds

Owners: Site Reliability (Lukas Brennand) and Platform. Last reviewed: 2026-06-30.

During the canary stage of a deploy (described on [How code reaches production](deployment-pipeline.md)), Shipwright compares the canary pods, which run the new release, with baseline pods running the current release and receiving the same mix of traffic. The canary **fails**, and Shipwright stops the release, when either signal crosses its threshold:

| Signal | The canary fails when | Example that fails | Example that passes |
|---|---|---|---|
| Error rate | it rises 0.5 points or more above the baseline | baseline 0.2%, canary 0.7% | baseline 0.2%, canary 0.6% |
| p99 latency | it rises 20% or more above the baseline | baseline 180 ms, canary 216 ms | baseline 180 ms, canary 210 ms |

In short: the canary fails when the error rate rises 0.5 points or p99 rises 20%.

"Points" means percentage points, not per cent. An error rate going from 0.2% to 0.3% is half as much again, but only 0.1 points, and passes. We chose points for errors because a relative rule would fail every canary of a service whose baseline error rate is close to zero.

## What counts

- **Error rate** is the share of requests that end in a server error: an HTTP 5xx, or a failed call for services that do not speak HTTP. Client errors are excluded, because a release that rejects bad input more strictly is not broken. A service can opt in to counting specific client errors through `extra_checks`.
- **p99 latency** is measured at the service's own ingress, so a slow dependency counts against you. That is deliberate: if your release calls the dependency twice as often, you made it slow.

## How the verdict is reached

1. The first 5 minutes of the canary are warm-up and are not judged.
2. From then on, Shipwright evaluates both signals every minute over a sliding 5-minute window.
3. A signal must breach on 3 consecutive evaluations to fail the canary; a single noisy minute does not.
4. At the end of the canary the verdict must be "pass" for the rollout to begin.

## Not enough traffic

The canary needs at least 1,000 requests over its run to be judged. Below that, the verdict is **inconclusive**: Shipwright holds the release and asks a human. Someone from the owning team looks at the Lantern dashboard "Canary analysis" and either approves with `shipwright approve-canary <service>` or stops the release. Batch services such as `settlement-batcher` are judged on job success in staging instead and always need that approval.

## Extra checks

Services may add their own signals with `extra_checks` in `shipwright.yaml`, for example `notify`'s webhook delivery success rate. Extra checks can only add reasons to fail. Nobody can loosen or remove the two default thresholds, for one deploy or for good.

## History

The thresholds were set during epic ENG-7 in 2025 by replaying about 200 past deploys, including every one that had led to an incident that year. The first version, in June 2025, used 1 point and 30%. It missed two regressions in its first month, and the thresholds were tightened to their current values before ENG-7 closed in August 2025. Since then, roughly one canary in forty fails, and in reviews of failed canaries about four in five turn out to be real regressions.

If you think a failed canary was wrong, post the Shipwright output in `#team-sre`; disputed verdicts are how the thresholds get better.
