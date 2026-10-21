---
title: "Model evaluation and promotion"
---

# Model evaluation and promotion

**Owner:** Mireille Okonkwo, head of risk ML. **Last reviewed:** 2026-09-22.
**Applies to:** every model that `risk-scorer` serves, starting with `fraudscore`.

This is the contract a new fraud model has to meet before it decides real payments.
It was written during ENG-22 ("Shadow mode and promotion gates", sprints 13 to 21) and
has been applied to every candidate since, including the one that became
`fraudscore-v7`. If you are training a candidate, start with
[Training the fraud model](fraud-model-training.md); if a promoted model is
misbehaving, go straight to [Rolling back a model in production](model-rollback.md).

The short version:

1. Offline, on the out-of-time holdout, the challenger must beat the champion by 2
   points of recall at a 0.5% decline rate, and must not lose AUC-PR.
2. It then runs for 14 days in shadow mode, scoring live traffic without deciding
   anything.
3. The head of risk ML signs it off.
4. `modelctl promote` makes it the champion.

There are no shortcuts, and the rest of this page explains why each step exists.

## Vocabulary

- **Champion**: the model whose scores decide payments today. Currently `v7`.
- **Challenger** or **candidate**: a registered model that is going through the gates.
  A retrain of the champion on fresher data is a challenger like any other.
- **Decline rate**: the share of authorisations that `card-auth` declines because the
  model's score is at or above the decline threshold. Rules-based declines and issuer
  declines do not count.
- **Operating point**: the decline threshold that produces a 0.5% decline rate on the
  holdout. Every model gets its own threshold, stored with it in the registry.

## The two metrics

### AUC-PR

AUC-PR summarises precision and recall across every possible threshold. With fraud at
roughly 0.3% of authorisations, it is far more sensitive to what matters than any
metric that rewards getting the 99.7% of legitimate payments right. We use it as a
health check: a challenger whose AUC-PR is lower than the champion's on the same
holdout is rejected, whatever else it does.

### Recall at a 0.5% decline rate

This is the number the gate is built on. We agreed with Risk Operations and Payments
Core that the model may decline at most 0.5% of authorisations; beyond that, the cost
to honest buyers and to our merchants' conversion outweighs the fraud stopped. Given
that budget, the only question is how much fraud the model catches inside it.

Recall here is counted in payments, not in money: a fraudulent payment of £12 and
one of £1,200 count the same. We report value-weighted recall alongside it, because
Finance asks, but it is not part of the gate. Value-weighted recall is easy to inflate
by focusing the model on a few large sellers.

The calculation, as the `report` stage does it:

```python
import numpy as np

DECLINE_RATE = 0.005


def recall_at_decline_rate(scores, is_fraud, decline_rate=DECLINE_RATE):
    """Recall when the top `decline_rate` share of payments is declined.

    Returns the recall and the threshold, which becomes the model's
    operating point if it is promoted.
    """
    scores = np.asarray(scores, dtype=float)
    is_fraud = np.asarray(is_fraud, dtype=bool)
    threshold = np.quantile(scores, 1.0 - decline_rate, method="higher")
    declined = scores >= threshold
    return declined[is_fraud].mean(), threshold
```

Two details matter. `method="higher"` keeps the realised decline rate at or below
0.5% when many payments share a score, which happens with calibrated tree models.
And the champion is rescored on the challenger's holdout; we never compare against
numbers from the champion's own report, which used a different month.

## Offline evaluation

The `report` stage of the training pipeline writes an evaluation report to the
registry. A reviewer from Risk ML, not the candidate's author, checks it against this
list:

| Check | Pass condition |
|---|---|
| Holdout | Out-of-time, after the training window, labels matured |
| Recall at a 0.5% decline rate | Challenger at least 2 points above the champion |
| Confidence | Lower bound of the 95% bootstrap interval of the gain above 0 |
| AUC-PR | Not lower than the champion's |
| Slices | No slice with 500 or more frauds loses more than 3 points of recall |
| Latency | p99 within `risk-scorer`'s 35 ms budget on the load test |
| Features | Every feature registered in the feature store |

The bootstrap resamples whole days, 1,000 times, because payments on the same day
are not independent: one fraud ring can fill an afternoon.

The slices we report are currency (GBP, EUR), merchant segment, card tokens seen for
the first time, payments with and without 3DS, and five amount bands. The
3-point slice rule exists because an average gain can hide a loss on a group we care
about. When `v7` was evaluated, its weakest slice was first-seen card tokens, where
the sequence embedding has nothing to read; it still gained 0.8 points there.

### Why 2 points

Two points of recall at the operating point is about the smallest gain that survives
the noise of a single month's holdout and a change of seed. Smaller gains were often
gone by the time shadow mode finished, and every promotion carries a cost: Risk
Operations retunes its reviews, and the new model declines different honest buyers
from the old one. A 1.8-point gain with a splendid AUC-PR still fails. Bundle it with
the next improvement instead.

## Shadow mode

A challenger that passes offline runs for 14 days in shadow mode. `risk-scorer` scores
every authorisation with both models; only the champion's score reaches `card-auth`.
The challenger's scores and would-be decisions are written to the warehouse for
analysis.

```bash
modelctl shadow fraudscore --candidate cand-20251103-a --days 14
modelctl status fraudscore
```

Shadow mode cannot measure recall: the labels for those 14 days will not settle for
weeks, for the reasons on the training page. What it does measure:

- **Would-be decline rate.** It must stay between 0.4% and 0.6% on every day. A
  calibration problem shows up here first.
- **Overlap.** The share of the champion's declines that the challenger would also
  decline. Below 50% means the two models disagree about who is a fraudster, and
  someone must explain why before sign-off.
- **Unique declines.** Risk Operations reviews 300 payments that only the challenger
  would have declined, using the process on
  [Risk operations: reviewing declined payments](risk-ops-reviews.md). Their
  judgement is the closest thing to fresh labels that we have.
- **Latency and errors.** `risk-scorer`'s p99 with both models loaded, and any
  scoring errors.

The 14 days restart from zero if the challenger changes in any way, including a new
threshold or a recalibration. Fourteen days always includes two full weekends, and
weekend traffic on our marketplaces looks different enough to matter.

## Sign-off

Sign-off is by the head of risk ML, Mireille Okonkwo, and by nobody else. She reads
the evaluation report, the shadow report and the Risk Operations review, and records
the decision in the registry:

```bash
modelctl approve fraudscore --candidate cand-20251103-a \
  --note "Offline +5.3 pts recall at 0.5%; shadow 2026-01-19 to 2026-02-01 clean"
```

There is no deputy. When she is away, promotions wait; a model that is genuinely
better will still be better a week later.

## Promotion

```bash
modelctl promote fraudscore --candidate cand-20251103-a
```

`promote` assigns the next version label, moves the champion alias to it, and keeps
the previous champion loaded in `risk-scorer` as the rollback target. The switch
reaches every pod within a couple of minutes. Promote on a Tuesday, Wednesday or
Thursday morning, when Risk Operations is fully staffed, and tell them in their
channel the day before.

After promotion:

- Update the model cards: a new card for the new champion, and a status line on the
  old one.
- Watch the decline rate on the "risk-scorer overview" dashboard in Lantern for the
  rest of the day. The rollback criteria are on
  [Rolling back a model in production](model-rollback.md).
- Make sure [drift monitoring](drift-monitoring.md) has a reference distribution for
  the new version; the `register` stage writes one, but check.

## Worked example: v7 against v6

| | `fraudscore-v6` (champion) | `fraudscore-v7` (challenger) |
|---|---|---|
| Holdout | August 2025 | August 2025 |
| AUC-PR | 0.418 | 0.482 |
| Recall at a 0.5% decline rate | 66.1% | 71.4% |
| Gain | | +5.3 points, interval 4.1 to 6.4 |
| Shadow mode | | 2026-01-19 to 2026-02-01 |
| Would-be decline rate in shadow | | 0.47% to 0.53% |
| Signed off | | 2026-02-03 |
| Promoted | | 2026-02-04 |

The gap between training (November 2025) and shadow mode (January 2026) was the
shadow-mode tooling itself, which ENG-22 finished in its last sprint. Details of both
models are on [Model card: fraudscore-v7](model-card-fraudscore-v7.md) and
[Model card: fraudscore-v6](model-card-fraudscore-v6.md).

## Candidates that did not make it

The gate is not a formality. Since ENG-22 put it in place, more candidates have
failed than passed, and the reasons are instructive:

| Candidate | Offline gain | Stopped at | Reason |
|---|---|---|---|
| `cand-20251006-a` | +6.0 points | Offline review | A merchant feature used month-end values; leakage |
| `cand-20251103-a` | +5.3 points | Promoted as `v7` | |
| `cand-20260413-a` | +0.9 points | Offline review | Fresher window only; below the 2-point bar |
| `cand-20260720-b` | +2.2 points | Shadow mode, day 6 | Would-be decline rate reached 0.68% on a Saturday |
| `cand-20260720-c` | +2.1 points | Offline review | Lost 4.2 points on EUR payments, a slice with 1,900 frauds |

`cand-20260720-b` is the example we use in onboarding: it passed every offline check
and would have declined far too many payments on its first weekend in production.
Its calibration had been fitted on weeks with no marketplace sales event. The
recalibrated version, `cand-20260720-c`, then failed on a slice. Both came out of the
[merchant graph experiment](experiment-2026-06-merchant-graph.md), whose page records
what was learnt and what is being tried next.

## A typical timeline

From the end of a training run to promotion usually takes three to four weeks:

| Step | Typical duration | Who |
|---|---|---|
| Offline review of the report | 2 to 4 working days | A Risk ML reviewer who did not train the model |
| Load test of `risk-scorer` with both models | 1 day | Risk ML, with Site Reliability watching |
| Shadow mode | 14 days, never less | `risk-scorer`, automatically |
| Risk Operations review of unique declines | 3 working days, overlapping shadow mode | Risk Operations |
| Sign-off | 1 to 5 working days | Head of risk ML |
| Promotion | Under an hour, on a Tuesday to Thursday morning | Risk ML |

## What the evaluation report contains

The `report` stage writes one document per candidate, attached to it in the registry
and readable with `modelctl report fraudscore --candidate` and the run name. Reviewers
expect, in this order: the configuration and lineage; the headline table of AUC-PR
and recall at a 0.5% decline rate for champion and challenger; the bootstrap interval
of the gain; the slice table; the precision-recall curves of both models; the twenty
features with the most gain; the score histograms on the holdout; and the latency
figures from the load test. A report missing any of these is sent back unread.

## Questions people ask

**Can we shorten shadow mode when the offline gain is huge?** No. A huge offline gain
is more often leakage than genius, and shadow mode is where it shows.

**The champion has drifted; can a retrain skip the gate?** No. A retrain that cannot
beat a drifted champion by 2 points is not worth the churn. Drift is handled by
monitoring and, if it comes to that, by rollback.

**Can a candidate run in shadow mode before its offline review is complete?** Yes,
to save time, but the 14 days only count once the offline checks pass and nothing
about the model has changed since.

**Who can promote?** Anyone in Risk ML with the `promoter` role in the registry, but
only a candidate with an approval recorded; `modelctl promote` refuses otherwise.
