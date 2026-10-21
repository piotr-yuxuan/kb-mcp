---
title: "Model drift monitoring"
---

# Model drift monitoring

Owner: Risk ML. Maintainer: Linnea Barraclough. Last reviewed 2026-10-05.

A fraud model starts going stale the day it is trained. Fraudsters adapt, marketplaces
change what they sell, and our own traffic mix shifts. We cannot measure recall on
recent traffic, because recent payments have no settled labels yet, so drift
monitoring watches the things we can see today and tells us when the champion is
drifting away from the world it was trained on.

## What we watch

| Signal | How often | Compared with | Where |
|---|---|---|---|
| Score distribution | Daily | The holdout's distribution, stored at registration | Lantern, "fraudscore drift" |
| Top 40 features by gain | Daily | The training window's distributions | Lantern, "fraudscore drift" |
| Feature null rates | Hourly | The previous 7 days | Lantern, "risk-scorer overview" |
| Decline rate | Continuously | The same hour over the previous 7 days | Lantern, "risk-scorer overview" |
| Risk Operations review outcomes | Daily | The previous 30 days | Lantern, "fraudscore drift" |
| Recall on matured labels | Weekly | The holdout recall | Lantern, "fraudscore drift" |

The decline-rate signal is the urgent one and has its own alert and runbook:
[Rolling back a model in production](model-rollback.md). Everything else on this page
is slower and is about deciding when the champion needs replacing, not about firefighting.

## Population stability index

For the score and for each of the top 40 features, the daily Conveyor job
`fraudscore_drift` computes the population stability index between yesterday's values
and the reference distribution, over ten bins fixed by the reference's deciles.

```python
import numpy as np


def population_stability_index(reference, current, bins=10, floor=1e-4):
    """Population stability index of `current` against `reference`."""
    edges = np.quantile(reference, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    ref_share = np.histogram(reference, edges)[0] / len(reference)
    cur_share = np.histogram(current, edges)[0] / len(current)
    ref_share = np.clip(ref_share, floor, None)
    cur_share = np.clip(cur_share, floor, None)
    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))
```

| Index | Reading | What happens |
|---|---|---|
| Below 0.10 | Stable | Nothing |
| 0.10 to 0.25 | Moving | Shown amber on the dashboard; discussed at the weekly review |
| Above 0.25 | Shifted | Message in `#team-risk-ml`; someone investigates within two working days |

A feature can shift for good reasons: a new marketplace, a currency growing, a
seasonal peak. An investigation that ends with "this is real and expected" is a
perfectly good outcome; write it in the thread and move on.

## Recall on matured labels

Once a week, the job scores the most recent fully matured week of traffic (the wait is
on [Training the fraud model](fraud-model-training.md)) and computes recall at the
operating point. This is the only true performance number we have, and it is always
weeks old. For `fraudscore-v7`, it has ranged between 68.0% and 72.9% since promotion,
against 71.4% on the holdout.

A weekly recall more than 4 points below the holdout figure for three weeks in a row
is the signal to start training a challenger. That has not happened yet for v7.

## Upstream problems that look like drift

Some "drift" is broken data. Before investigating a shifted feature, check whether
Data Platform has raised a quality alert on `fraud_features_daily`. A column that
changes type upstream raises `DQ-044`, and a late table `DQ-017`; both are explained on
[Data quality alerts](../data/quality-alerts.md). If either is open, the shift is
theirs to fix and ours to wait out; note it on the dashboard's annotation layer so the
weekly review does not chase it again.

The 2026-07-02 rollback is the cautionary tale here: a unit change in a seller feature
showed up first as an index of 3.1 on that feature, hours before the decline rate
moved. Since then, any index above 1.0 on a single feature pages the Risk ML on-call
during working hours rather than waiting for the weekly review.

## Investigating a red signal

Whoever picks up a red signal works through the same steps, and writes what they
found in the alert's thread so the next person does not start from scratch:

1. **Is it one feature or many?** Many features moving together usually means the
   traffic mix changed, for example a large marketplace onboarding. One feature alone
   usually means its definition or its source changed.
2. **Is it in the score?** A feature can shift a lot without moving the score, if the
   model leans on it little. Check the score's own index for the same day.
3. **Where is it concentrated?** Break the index down by currency and by marketplace
   in a [notebook](notebooks.md). A shift confined to one marketplace is often a
   change in how that marketplace integrates with us.
4. **Did anything change on our side?** A new feature definition, a `risk-scorer`
   release, a change in the label build.
5. **Decide.** Expected and harmless; a data problem for its owner; or a real change
   in the world that the next challenger should learn from. Only the third goes on
   the weekly review agenda as a reason to train.

## Weekly review

Mondays at 11:30, in `#team-risk-ml` and a short call. The maintainer of this page
runs it, or delegates. Agenda:

1. Amber and red signals since last week, and their explanations.
2. Weekly recall on matured labels.
3. Risk Operations' legitimate share trend, from
   [Risk operations: reviewing declined payments](risk-ops-reviews.md).
4. Whether anything warrants a challenger. If yes, it goes on the next planning agenda.

## For a new champion

Each registered model stores its own reference distributions. After a promotion,
check that the "fraudscore drift" dashboard has switched references; otherwise every
panel will show the new model drifting from the old one's holdout.
