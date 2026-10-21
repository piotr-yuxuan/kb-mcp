---
title: "Model card: fraudscore-v7"
---

# Model card: fraudscore-v7

| | |
|---|---|
| Model | `fraudscore`, version `v7` |
| Status | Champion, serving all traffic through `risk-scorer` |
| Promoted | 2026-02-04 |
| Registry run name | `cand-20251103-a` |
| Owner | Risk ML; signed off by Mireille Okonkwo |
| Last reviewed | 2026-10-12 |

## Purpose

Scores every card authorisation on Quillmoor Pay for the likelihood that it is
fraudulent. `card-auth` declines payments whose score is at or above the model's
decline threshold, which is set to decline about 0.5% of authorisations.

## Not intended for

- Deciding on payouts to sellers or on releasing payout holds.
- Judging a merchant's or seller's overall risk; the score is per payment.
- Any use outside the authorisation path without a new evaluation.

## Architecture

Gradient-boosted trees (LightGBM) on 286 tabular features, plus a 64-dimensional
sequence embedding of the card token's last 32 authorisation events, produced by a
two-layer PyTorch encoder trained on Kiln. Isotonic calibration on top. How it is
trained is on [Training the fraud model](fraud-model-training.md).

## Training data

| | |
|---|---|
| Training window | 2024-07-01 to 2025-07-31 |
| Holdout | 2025-08-01 to 2025-08-31, out of time |
| Training run | 2025-11-03, three seeds, median registered |
| Features | `fraudscore_v7` feature set, from `fraud_features_daily` |
| Labels | Chargebacks, Risk Operations findings, confirmed merchant reports |
| Excluded | Test merchants; retried authorisations after the first |

## Evaluation

On the August 2025 holdout, against `fraudscore-v6` scored on the same month:

| Metric | v7 | v6 |
|---|---|---|
| AUC-PR | 0.482 | 0.418 |
| Recall at a 0.5% decline rate | 71.4% | 66.1% |
| Value-weighted recall at the same rate | 63.0% | 58.7% |

| Slice | Frauds in holdout | Recall, v7 | Change against v6 |
|---|---|---|---|
| GBP payments | 6,840 | 72.6% | +5.5 points |
| EUR payments | 2,310 | 67.9% | +4.6 points |
| First-seen card tokens | 1,120 | 58.3% | +0.8 points |
| With 3DS | 2,050 | 61.2% | +3.9 points |
| Without 3DS | 7,100 | 74.3% | +5.7 points |

Shadow mode ran from 2026-01-19 to 2026-02-01 with a would-be decline rate between
0.47% and 0.53%. The gates it passed are described on
[Model evaluation and promotion](evaluation-and-promotion.md).

## Serving

- p99 scoring latency in `risk-scorer`: 21 ms, within the 35 ms budget.
- Rollback target: `fraudscore-v6`, kept loaded. See
  [Rolling back a model in production](model-rollback.md).

## Known limitations

- **First-seen card tokens.** With no history, the embedding carries no signal, and
  v7 is barely better than v6 on these payments.
- **Unusual event types.** The encoder reacts badly to authorisation types it has not
  seen in training. Zero-amount verifications caused the rollback of 2026-03-18 and
  are now filtered out of the sequence.
- **EUR coverage.** EUR payments are about a quarter of the training data, and recall
  is lower there.
- **Seasonality.** The window holds one late-year sales season, plus the month before
  the holdout twice; the next sales season is the first real test of calibration at
  volume.

## Monitoring

Score and feature drift against the training reference, daily; decline rate against
baseline, continuously. See [Model drift monitoring](drift-monitoring.md).

## Change history

| Date | Change |
|---|---|
| 2026-02-04 | Promoted to champion |
| 2026-03-18 | Pinned to v6 for about six hours; zero-amount verifications filtered from the sequence |
| 2026-07-02 | Pinned to v6 for about forty minutes after an upstream unit change |
