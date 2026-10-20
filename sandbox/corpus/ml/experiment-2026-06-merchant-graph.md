---
title: "Experiment notes: merchant graph features (June 2026)"
---

# Experiment notes: merchant graph features (June 2026)

- Authors: Sunniva Holt and Matteo Quaye
- Written up: 2026-06-26, updated 2026-09-15 with the outcome of the July candidates
- Last reviewed: 2026-09-15

## Why we tried this

The [March sequence experiment](experiment-2026-03-sequence-features.md) found a real
but small gain from finer time-gap encoding, short of the 2-point gate on its own. We
needed a second source of signal that did not overlap with the card's own history.
Risk Operations had been pointing at one for months: fraudulent sellers on our
marketplaces rarely act alone. They reuse payout bank accounts, devices and addresses,
and a new seller who shares a payout account with a seller banned last month is a
very different proposition from a genuinely new one.

## The graph

- **Nodes:** sellers, plus hashed payout bank accounts, hashed device fingerprints and
  hashed postal addresses. No raw values enter the graph.
- **Edges:** a seller used this account, logged in from this device, or registered
  this address. Each edge carries the date it was first seen.
- **Size:** about 1.9 million nodes and 4.6 million edges for the 13 months of the
  window.
- **Build:** a daily job on Kiln `train-short`, rebuilding the graph as of each day so
  that features can be read point in time.

The DPO's team reviewed the hashing before we started: the hashes are salted with a
key held in Strongroom, and the hashed columns are tagged as personal data in the
warehouse. Nothing in the graph can be reversed to an account number without that key.

## Features tried

| Feature | Meaning |
|---|---|
| `seller__component_size__90d` | Sellers connected to this one through shared accounts, devices or addresses |
| `seller__fraud_neighbours__90d` | Of those, sellers with confirmed fraud known at the time |
| `seller__hops_to_fraud__90d` | Shortest path to a seller with confirmed fraud, capped at 4 |
| `seller__shared_accounts__30d` | Payout accounts shared with any other seller |
| Node embedding, 16 dimensions | Learnt from the graph structure with a small graph neural network |

"Known at the time" is the trap. A neighbour whose fraud was confirmed after the
payment must not count. Our first attempt got this wrong and showed a 7-point gain;
the corrected one is below.

## Results

Holdout March 2026, labels matured by the end of May. Training window 13 months
ending February 2026. Recall at a 0.5% decline rate, in points against the v7
configuration retrained on the same window:

| Arm | Recall change | AUC-PR change | Note |
|---|---|---|---|
| Hand-built graph features | +1.7 | +0.013 | |
| Hand-built plus node embedding | +1.9 | +0.014 | Embedding adds a day to every build |
| Hand-built plus March time gaps | +2.6 | +0.021 | Best value |
| All of the above | +2.7 | +0.022 | Not worth the embedding |

On sellers whose accounts were under 30 days old, the best arm gained 4.9 points.
That is where the money is: new sellers are where marketplaces lose most to fraud, and
where the card sequence has least to say.

## Decision in June

Build a challenger from "hand-built plus March time gaps", register the four graph
features in the [feature store](feature-store.md), and drop the node embedding.

## Update, September 2026

Two candidates came out of this in July, `cand-20260720-b` and `cand-20260720-c`.
Neither was promoted; the details are on
[Model evaluation and promotion](evaluation-and-promotion.md). In short, `-b` was
miscalibrated at weekends and `-c` lost recall on EUR payments.

The EUR loss is now understood. Most sellers paid out in EUR joined Quillmoor Payouts
in the last eighteen months, and the graph has far fewer edges around them, so the
graph features are mostly empty for their payments. The model learnt to treat an
empty graph as a sign of safety, which is true for GBP sellers and false for EUR ones.
The next attempt makes "no graph data" an explicit value rather than zero, and trains
with currency as an interaction. Work continues in `#team-risk-ml`; there is no
candidate yet.
