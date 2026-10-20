---
title: "Training the fraud model"
---

# Training the fraud model

| | |
|---|---|
| Owner | Risk ML (`#team-risk-ml`) |
| Maintainer | Linnea Barraclough |
| Approver | Mireille Okonkwo, head of risk and fraud machine learning |
| Last reviewed | 2026-10-14 |

This page explains how `fraudscore-v7`, the fraud model that `risk-scorer` serves
today, was trained, and how to produce a new training run of the same family. It
stops at the moment a candidate lands in the model registry. Everything after that,
from the offline gate to shadow mode and promotion, is on
[Model evaluation and promotion](evaluation-and-promotion.md).

If you only need the headline numbers for the model in production, read the
[model card for fraudscore-v7](model-card-fraudscore-v7.md) instead.

## The model in one paragraph

`fraudscore-v7` is gradient-boosted trees with a sequence embedding trained on Kiln.
A small PyTorch encoder reads the most recent authorisation events of the card token
and turns them into a 64-dimensional embedding. LightGBM then trains gradient-boosted
trees on the tabular features plus those 64 dimensions, and an isotonic calibration
step turns the raw tree output into a score between 0 and 1. The encoder is what
`fraudscore-v6` did not have: v6 was trees alone, and the sequence embedding is most
of the recall that v7 gained over it.

| Component | Library | Trains on | Artefact in the registry |
|---|---|---|---|
| Sequence encoder | PyTorch | Kiln, `train-long`, 8 GPUs | `encoder.pt` |
| Gradient-boosted trees | LightGBM | Kiln, `train-short`, 1 GPU | `trees.txt` |
| Calibration | scikit-learn, isotonic | Kiln, `train-short` | `calibration.joblib` |
| Decline threshold | our own code | computed from the holdout | `threshold.json` |

The model never sees a PAN. Sequences are keyed on the card token that `card-auth`
issues, and the token never leaves the scoring path; see the
[payments platform architecture](../payments/platform-architecture.md) for where the
boundary sits.

## Data

### Features

Every tabular feature comes from `fraud_features_daily`, the Data Platform pipeline
that builds one row per authorisation with its aggregates as they stood at
authorisation time. Its schedule, owner and quality checks are on
[Pipeline: fraud_features_daily](../data/pipeline-fraud-features-daily.md); this page
does not repeat them. We read the table through the feature definitions described in
the [feature store guide](feature-store.md), never with hand-written SQL, so that the
training set and the online scores use the same definitions.

The `fraudscore_v7` feature set holds 286 tabular features. Roughly a third are
velocity counts (authorisations per card token, per device and per seller over 1
hour, 24 hours and 7 days), a third are merchant and seller history, and the rest
describe the payment itself: amount band, currency, whether 3DS was attempted, and
whether the issuing country matches the seller's country.

### The 13-month training window

We train on a 13-month training window that ends where the out-of-time holdout
begins. Thirteen rather than twelve is deliberate: every calendar month appears at
least once, and the month just before the holdout appears twice, once in each year.
That month is usually the closest in behaviour to the holdout, and seasonal patterns
around marketplace sales events show up clearly in it. Going longer than 13 months
did not help in the ENG-21 experiments: the oldest months describe fraud patterns that
the card schemes and our merchants have since closed off, and recall at the operating
point fell slightly.

### Labels and the 60-day wait

A payment is labelled fraudulent when a fraud chargeback, a Risk Operations finding
or a merchant's confirmed report says so. The rules are on
[Labelling fraud from chargebacks](chargeback-labels.md). What matters for training
is time: labels wait 60 days for chargebacks. A payment authorised less than 60 days
before the training run has no settled label yet, because most fraud chargebacks have
not arrived, and treating it as legitimate would teach the model that recent fraud is
fine.

The practical consequence is that the newest example in any training run is at least
60 days old, and the holdout must have matured as well. For the v7 run the dates were:

| Item | Dates |
|---|---|
| Training window, 13 months | 2024-07-01 to 2025-07-31 |
| Out-of-time holdout | 2025-08-01 to 2025-08-31 |
| Holdout labels matured | 2025-10-30 |
| Final training run | 2025-11-03 |

The pipeline refuses to start when the holdout's last day plus 60 days falls after the
run date. The check is short enough to quote:

```python
from datetime import date, timedelta

LABEL_MATURITY_DAYS = 60


def check_label_maturity(holdout_end: date, run_date: date) -> None:
    """Refuse a run whose holdout still has unsettled chargeback labels."""
    matured_on = holdout_end + timedelta(days=LABEL_MATURITY_DAYS)
    if matured_on > run_date:
        raise ValueError(f"holdout labels mature on {matured_on}; rerun on or after that date")
```

## Running a training job

A training run is a Conveyor pipeline, `fraudscore_training`, whose stages submit
work to Kiln. You need membership of the `risk-ml` Kiln team and read access to the
`marts` layer; see [Requesting warehouse access](../data/warehouse-access.md) if you
are new.

### 1. Write the configuration

Configurations live in the `risk-ml` repository under `training/`. Copy the last one
and change only what you mean to change. This is the v7 run's file, trimmed of
comments:

```yaml
run_name: cand-20251103-a
model: fraudscore
window:
  months: 13
  end: 2025-07-31
holdout:
  start: 2025-08-01
  end: 2025-08-31
label_maturity_days: 60
features:
  table: marts.fraud_features_daily
  feature_set: fraudscore_v7
  snapshot_id: 7342918840012655311
exclude:
  test_merchants: true
  duplicate_retries: keep_first
sequence_encoder:
  events_per_card: 32
  embedding_dim: 64
  layers: 2
  heads: 4
  epochs: 6
  kiln:
    queue: train-long
    gpus: 8
trees:
  library: lightgbm
  num_leaves: 255
  learning_rate: 0.03
  num_boost_round: 4000
  early_stopping_rounds: 200
  scale_pos_weight: 20
  kiln:
    queue: train-short
    gpus: 1
seeds: [20251103, 20251104, 20251105]
```

The `snapshot_id` pins the Apache Iceberg snapshot of the feature table, so that a
rerun next month reads exactly the same rows even after late data has landed. Take it
from the `snapshot` stage of a dry run (below) and paste it in.

### 2. Dry run, then run

```bash
# Resolve the window, the snapshot and the row counts without training anything.
conveyor run fraudscore_training --config training/cand-20251103-a.yaml --dry-run

# The real run.
conveyor run fraudscore_training --config training/cand-20251103-a.yaml
```

The pipeline's stages, in order:

1. `snapshot`: resolves the Iceberg snapshot and checks that every daily partition in
   the window and the holdout is present.
2. `labels`: joins matured labels, applying the 60-day rule.
3. `encoder`: trains the sequence encoder on Kiln's `train-long` queue, once per seed,
   with the three seeds running side by side.
4. `trees`: trains LightGBM on `train-short`, once per seed, with the encoder frozen.
5. `calibrate`: fits isotonic calibration on the last two weeks of the training
   window, which the trees never saw.
6. `report`: scores the holdout and writes the evaluation report.
7. `register`: calls `modelctl register` with the median seed's artefacts.

### 3. Watch it

```bash
kiln status --team risk-ml
kiln logs <job-id> --follow
conveyor run fraudscore_training --status
```

A full run takes about 14 hours: roughly 9 for the encoder on 8 GPUs, 2 for the trees,
and the rest for joins and scoring. Queue limits and quotas are on
[GPU cluster quotas and scheduling](gpu-cluster.md).

### 4. Check what was registered

```bash
modelctl list fraudscore --candidates
modelctl describe fraudscore --candidate cand-20251103-a
```

`describe` prints the lineage: the configuration's commit, the Iceberg snapshot, the
container image digest, the seeds and the holdout metrics. A candidate has a run name
but no version label; `modelctl promote` assigns the label (`v7` was assigned that
way) once the candidate has passed the gates.

## Reproducibility

- **Data.** The Iceberg snapshot is pinned; the window and holdout are in the
  configuration. Never train against "latest".
- **Code.** The `register` stage refuses a dirty working tree.
- **Randomness.** The encoder is not bit-for-bit deterministic on GPUs. Across seeds,
  recall at the operating point varies by about 0.2 points, so we train three seeds
  and register the median, not the best. Picking the best seed flatters the candidate
  and the gate would be measuring luck.
- **Environment.** The image digest is recorded; rebuild from it rather than from the
  current base image.

## Traps we have fallen into

**Features from the future.** Any aggregate must be computed as of the authorisation
time. The feature store's point-in-time join handles this for registered features; a
feature you compute yourself in a notebook almost certainly does not.

**Chargeback features leaking labels.** A seller's chargeback rate is a strong
feature, but only the chargebacks known at authorisation time may count. In an early
ENG-21 run, a version that used the month-end chargeback rate scored 9 points higher
on the holdout and was useless in practice.

**Missing partitions.** If the `snapshot` stage reports missing days, do not drop
them. Ask Data Platform in `#team-data` for a backfill; the procedure is on
[Backfilling historical partitions](../data/backfills.md). A window with holes
quietly underweights whatever happened on those days.

**Test merchants.** Sandbox merchants generate synthetic fraud patterns on purpose.
`exclude.test_merchants` must stay `true`; the list is on
[Test merchants and test cards](../payments/test-merchants.md).

**Retries.** A declined payment retried by the marketplace appears as several
authorisations. We keep the first attempt only, otherwise one fraudster's retries
count many times.

**Class imbalance.** Fraud is about 0.3% of authorisations. We weight positives with
`scale_pos_weight` rather than downsampling legitimate payments, because downsampling
distorted the calibration and moved the decline threshold.

## Before you hand a candidate over

The evaluation reviewer will check the gate. You are responsible for everything that
makes the gate meaningful. Go through this list before you post the candidate's run
name in `#team-risk-ml`:

- [ ] The holdout is the month straight after the window, and its labels had matured
      on the run date.
- [ ] All three seeds used the same `snapshot_id`, and their recall at the operating
      point lies within 0.5 points of one another.
- [ ] No feature outside the registered feature set was used. `modelctl describe`
      lists the feature set; compare it with the configuration.
- [ ] The top twenty features by gain look sensible to someone who knows the domain.
      A feature you have never heard of in first place deserves an explanation.
- [ ] The decline threshold in `threshold.json` produces a decline rate within 0.45%
      to 0.5% on the holdout.
- [ ] The report's slice table has no empty rows; an empty slice usually means a join
      dropped data.

The feature check is quick to script against the registered artefact:

```python
import lightgbm as lgb

booster = lgb.Booster(model_file="trees.txt")
gains = booster.feature_importance(importance_type="gain")
names = booster.feature_name()
top = sorted(zip(names, gains), key=lambda pair: pair[1], reverse=True)[:20]
for name, gain in top:
    print(f"{name:<48} {gain:>14,.0f}")
```

For `v7`, the embedding dimensions take six of the top twenty places, alongside the
24-hour velocity counts per card token and per device. If your candidate's list looks
very different from that, find out why before anyone else does.

## Who may change what

| Setting | Who decides | Why it is controlled |
|---|---|---|
| Window length (13 months) | Head of risk ML | Changes what the holdout comparison means |
| Label wait (60 days) | Head of risk ML, with Risk Operations | Shorter waits mislabel recent fraud |
| Feature set | Any Risk ML engineer, through the feature store | Reviewed like code |
| Encoder and tree hyperparameters | The candidate's author | Judged by the gate, not in advance |
| Seeds and seed count | Fixed at three | Keeps the median honest |

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `snapshot` fails with missing partitions | Upstream gap in `fraud_features_daily` | Ask `#team-data` for a backfill; rerun after it lands |
| `labels` refuses to start | Holdout labels not matured | Wait, or move the holdout one month earlier |
| `encoder` sits pending for hours | Team over its Kiln quota | Check `kiln quota --team risk-ml`; see the GPU cluster page |
| Holdout recall far above the champion | Almost always leakage | Check every new feature's as-of time before celebrating |
| Seeds disagree by more than 1 point | Data changed between seeds | Confirm all seeds used the same `snapshot_id` |

## History

- **v6** was trained in a single LightGBM process on a 12-month window, without
  Kiln. Its card is [Model card: fraudscore-v6](model-card-fraudscore-v6.md).
- **ENG-21** (sprints 4 to 12, 2025-05-26 to 2025-09-28) built this pipeline: the
  Conveyor stages, the 13-month window, the label maturity check and the sequence
  encoder on Kiln.
- **ENG-22** then added shadow mode and the promotion gates, so that the v7 candidate
  trained on 2025-11-03 could be promoted under the rules on
  [Model evaluation and promotion](evaluation-and-promotion.md).

Questions go to `#team-risk-ml`. Changes to this page need Mireille Okonkwo's review,
because the window and the label wait are part of how the gate is measured.
