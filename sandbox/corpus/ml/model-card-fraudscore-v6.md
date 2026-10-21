---
title: "Model card: fraudscore-v6"
---

# Model card: fraudscore-v6

| | |
|---|---|
| Model | `fraudscore`, version `v6` |
| Status | Previous champion; kept loaded in `risk-scorer` as the rollback target |
| Promoted | 2024-05-13 |
| Champion until | 2026-02-04, replaced by `fraudscore-v7` |
| Registry run name | None; registered before run names existed |
| Owner | Risk ML |
| Last reviewed | 2026-08-19 |

> [!NOTE]
> v6 no longer decides payments unless someone has pinned it during a rollback. It is
> not retrained. This card is kept up to date because v6 must remain servable.

## Purpose

Scored every card authorisation on Quillmoor Pay for the likelihood of fraud from May
2024 until February 2026. `card-auth` declined payments whose score was at or above
v6's own threshold, set for a decline rate of about 0.5%.

## Not intended for

- Deciding on payouts to sellers or on releasing payout holds.
- Judging a merchant's or seller's overall risk.
- Serving as the champion again without passing today's gates.

## Architecture

Gradient-boosted trees (LightGBM) on 212 tabular features, with sigmoid calibration.
No sequence embedding: v6 sees each payment through aggregates only, never the order
of a card's recent events. It was trained in a single process on Conveyor's general
workers, before Kiln existed.

## Training data

| | |
|---|---|
| Training window | 2023-01-01 to 2023-12-31, twelve months |
| Holdout | 2024-01-01 to 2024-01-31, out of time |
| Training run | 2024-04-08, one seed |
| Features | An early version of today's feature set, from `fraud_features_daily` |
| Labels | Chargebacks only, with a 45-day wait |
| Excluded | Test merchants; retries were not removed |

The 45-day wait turned out to be too short. When ENG-21 rebuilt the pipeline, about 8%
of fraud chargebacks in the old data arrived after day 45, so v6 learnt from labels
that called some fraud legitimate. The current rules are on
[Labelling fraud from chargebacks](chargeback-labels.md).

## Evaluation

At its own promotion, on the January 2024 holdout:

| Metric | v6 |
|---|---|
| AUC-PR | 0.447 |
| Recall at a 0.5% decline rate | 68.9% |

On the August 2025 holdout used for v7's promotion, v6 scored an AUC-PR of 0.418 and
a recall of 66.1%, 5.3 points below v7. The fall from its own figures is partly drift
and partly a harder month.

v6 was promoted after a one-week side-by-side comparison. It predates the 2-point
gate and the shadow-mode period; see
[Model evaluation and promotion](evaluation-and-promotion.md) for the rules that apply
now.

## Serving

- p99 scoring latency in `risk-scorer`: 9 ms.
- A nightly `modelctl check fraudscore --version v6` confirms that it can still score
  today's features.

## Known limitations

- **No sequence information.** Weak on card testing and on bursts of small payments
  across sellers, where the order of events is the signal.
- **Retries counted.** Repeated attempts by the same fraudster weigh several times in
  its training data, which skews it towards a few loud patterns.
- **EUR coverage.** Trained when EUR was under a fifth of volume; recall on EUR
  payments is noticeably lower than on GBP.
- **Stale world.** Its training data ends in December 2023.

## Monitoring

v6 is not monitored for drift. The nightly check is the only routine monitoring, and
its failure pages Risk ML in working hours.

## Change history

| Date | Change |
|---|---|
| 2024-05-13 | Promoted to champion |
| 2026-02-04 | Replaced by v7; kept as rollback target |
| 2026-03-18 | Served all traffic for about six hours during a rollback |
| 2026-07-02 | Served all traffic for about forty minutes during a rollback |
