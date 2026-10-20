---
title: "ML reading group notes"
---

# ML reading group notes

Every other Thursday, 16:00 to 17:00 UK time, on a video call, with a room booked in
Perch for whoever is in London. Open to anyone; you do not need to have read the paper,
but it helps. Organiser: Matteo Quaye. Notes taken by whoever presented.
Last updated 2026-10-15.

How it works: the presenter picks a paper or a chapter a fortnight ahead and posts it
in `#team-risk-ml`. Twenty minutes of summary, thirty of discussion, ten on "would
this change anything we do?". That last part is the reason the group exists.

## 2026-10-15: conformal prediction for score thresholds

Presenter: Sunniva Holt. A tutorial on conformal methods for setting a threshold with
a guaranteed error rate. Interesting for the decline threshold, which today is a
plain quantile on the holdout. Consensus: the guarantee assumes exchangeable data,
which fraud traffic around a sales event is not. **Action:** Sunniva to compare
conformal thresholds with ours on the shadow data of `cand-20260720-b`, the candidate
that overshot the decline rate at a weekend.

## 2026-10-01: graph neural networks for fraud rings

Presenter: Matteo Quaye. A survey of graph models applied to fraud between accounts.
Most of the gains reported come from graph features that a hand-built approach also
captures, which matches what we saw in the
[merchant graph experiment](experiment-2026-06-merchant-graph.md). Nobody was keen to
bring back the node embedding. **Action:** none.

## 2026-09-17: label delay and its effect on evaluation

Presenter: Linnea Barraclough. A paper on learning when labels arrive late, with
methods that use partial labels instead of waiting. Lively discussion about whether
we could shorten our wait; see [Labelling fraud from chargebacks](chargeback-labels.md)
for the arrival curve we compared against. Conclusion: possible for monitoring, not
for training, where a mislabel costs more than a few weeks. **Action:** Linnea to try
a partially labelled recall estimate on the drift dashboard.

## 2026-09-03: gradient-boosted trees versus deep tabular models

Presenter: guest from Data Platform. A benchmark study that again finds trees hard to
beat on tabular data of our size. Reassuring, and a reminder that our neural part
earns its place only because sequences are not tabular. **Action:** none.

## 2026-08-20: no session

Half the regulars were on annual leave. Skipped.

## 2026-08-06: calibration under shift

Presenter: Sunniva Holt. Why calibrated scores drift when the mix of traffic changes,
and how isotonic calibration behaves at the extremes. Directly relevant to the failure
of `cand-20260720-b`. **Action:** add a calibration check by day of week to the shadow
report, done 2026-08-20.

## 2026-07-23: no session

Clashed with the quarterly rollback drill planning. Skipped.

## 2026-07-09: sequence models for transaction data

Presenter: Linnea Barraclough. Transformer encoders over card transactions, with
self-supervised pre-training. Close to what `fraudscore-v7` does; the paper's longer
sequences echo our [March experiment](experiment-2026-03-sequence-features.md), where
length bought little. **Action:** none.

## Older sessions

Notes before July 2026 are in the page history. Suggestions for future sessions go in
the pinned thread in `#team-risk-ml`.
