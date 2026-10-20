---
title: "Experiment notes: sequence features (March 2026)"
---

# Experiment notes: sequence features (March 2026)

Author: Linnea Barraclough. Reviewed by Matteo Quaye. Written up 2026-03-27.
Status: concluded. Last reviewed 2026-06-30.

## Question

`fraudscore-v7`'s sequence encoder reads the last 32 authorisation events of a card
token. Two ideas had been on the list since ENG-21:

1. **Longer sequences.** Would 64 or 128 events help with slow-burn fraud, where a
   stolen card is used sparingly for weeks?
2. **Time-gap encoding.** The encoder sees the order of events but only a coarse
   "time since previous event" bucket. Would a finer encoding of the gaps help with
   card testing, which is mostly about speed?

## Set-up

- Holdout: November 2025, labels matured by the end of January 2026.
- Training window: 13 months ending October 2025, as on
  [Training the fraud model](fraud-model-training.md).
- Everything except the encoder held fixed: same tabular features, same LightGBM
  settings, same calibration.
- Three seeds per arm, median reported, as for any candidate.
- Encoders trained on Kiln `train-long`, 8 GPUs per run; trees on `train-short`.
- Baseline: the v7 configuration retrained on the same window, so that the
  comparison isolates the encoder change rather than fresher data.

## Results

Recall at a 0.5% decline rate on the November 2025 holdout, in points against the
retrained baseline:

| Arm | Events | Time gaps | Recall change | AUC-PR change | Encoder training time | p99 scoring latency |
|---|---|---|---|---|---|---|
| Baseline | 32 | Coarse | 0.0 | 0.000 | 9.1 h | 21 ms |
| A | 64 | Coarse | +0.4 | +0.004 | 15.8 h | 29 ms |
| B | 128 | Coarse | +0.6 | +0.006 | 28.4 h | 48 ms |
| C | 32 | Fine | +1.1 | +0.009 | 9.6 h | 22 ms |
| D | 128 | Fine | +1.4 | +0.012 | 29.0 h | 49 ms |

Seed spread was 0.2 to 0.3 points in every arm, so A is within noise and C is not.

## What we learnt

- **Length buys little.** Going from 32 to 128 events added 0.6 points and cost three
  times the GPU hours. Worse, arm B's p99 scoring latency of 48 ms is over
  `risk-scorer`'s 35 ms budget, which would eat into `card-auth`'s own budget.
- **Time gaps are the real signal.** Arm C gets most of arm D's gain at almost no
  cost. The gain is concentrated where we expected: payments in the first ten
  minutes after a burst of small authorisations improved by 3.8 points.
- **No arm clears the bar alone.** The promotion gate needs 2 points of recall at
  the operating point; see
  [Model evaluation and promotion](evaluation-and-promotion.md). Even arm D falls short.

## Decision

- Keep the fine time-gap encoding for the next challenger.
- Park longer sequences. Revisit only if the latency budget changes.
- Look for a second, independent source of gain to combine with time gaps. That
  became the [merchant graph experiment](experiment-2026-06-merchant-graph.md).

## Loose ends

- Arm D's encoder hit an out-of-memory error at batch size 512 on one seed; we
  dropped to 256 for all its seeds. Worth remembering for any future long-sequence
  work.
- A notebook left open over the weekend of 2026-03-14 held 2 GPUs for two days. That
  episode is quoted in the ENG-23 epic as one reason for the idle preemption rule on
  [GPU cluster quotas and scheduling](gpu-cluster.md).
- Configurations and reports are in the registry under the run names
  `exp-202603-seq-a` to `exp-202603-seq-d`, plus `exp-202603-seq-base`.
