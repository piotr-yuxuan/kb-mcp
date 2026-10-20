---
title: "Notebook environment"
---

# Notebook environment

Owner: Risk ML (Kiln maintainers). Last reviewed 2026-07-30.

We run JupyterLab on Kiln, the GPU cluster's scheduler. Anyone with a Kiln account can
start a notebook; you do not need to be in Risk ML. This page covers starting one,
what is inside, and the rules that keep notebooks from becoming a data leak or a GPU
hoard.

## Starting a notebook

```bash
kiln notebook start --gpus 1 --image risk-ml-notebook:2026.07
kiln notebook list
kiln notebook stop <notebook-id>
```

`start` prints a link on `kiln.quillmoor.example`. Sign in with your usual company
account. Ask for `--gpus 0` if you only need to query the warehouse and plot things;
it starts faster and costs your team nothing in GPU time.

Notebooks run on Kiln's `interactive` queue, which has a per-person GPU cap and an
idle limit. Both are on [GPU cluster quotas and scheduling](gpu-cluster.md). When the
idle limit is reached the notebook is stopped, and the kernel's memory goes with it,
so save anything you care about.

## What is in the image

| Category | Included |
|---|---|
| Language | Python 3.12 |
| Data | pandas, Polars, PyArrow, the Trino client |
| Modelling | LightGBM, XGBoost, scikit-learn, PyTorch |
| Our packages | `qm_features` (see the [feature store guide](feature-store.md)) and the `modelctl` client |
| Plotting | matplotlib, seaborn |

The image is rebuilt on the first working day of each month. Pin the tag in anything
you will want to rerun; `latest` moves under your feet.

Need another package? Install it into your own environment for a quick look:

```bash
python -m pip install --user some-package
```

For anything you will use again, open a pull request against the image definition in
the `risk-ml` repository, so that everyone gets it and Security sees it.

## Storage

- `/kiln/home/$USER` survives restarts and is backed up. Keep notebooks and small
  outputs here.
- `/kiln/scratch` is shared and swept every 14 days. Large intermediate files go here.
- Do not save extracts of warehouse tables to your home directory for longer than the
  analysis needs. If you need a durable dataset, it belongs in the warehouse with an
  owner.

## Querying the warehouse

Your notebook queries Trino as you, with your own warehouse permissions. If you
cannot see a table, request access as described on
[Requesting warehouse access](../data/warehouse-access.md); do not borrow a colleague's
credentials or a service account.

```python
import pandas as pd
import trino

conn = trino.dbapi.connect(
    host="trino.quillmoor.example",
    port=443,
    http_scheme="https",
    catalog="iceberg",
    schema="marts",
    auth=trino.auth.OAuth2Authentication(),
)
frame = pd.read_sql("SELECT * FROM fraud_labels LIMIT 1000", conn)
```

Keep queries cheap: filter on the partition column, select only the columns you need,
and avoid `SELECT *` on large tables (the example above is limited on purpose).
[Keeping warehouse queries cheap](../data/query-costs.md) has more.

## Data rules

- Restricted data never comes into a notebook. Card tokens are fine; anything from the
  card data environment is not. See [Data classification](../security/data-classification.md).
- Personal data columns may be used when your access allows it, but outputs you share
  (charts in chat, exports to a slide) must be aggregated.
- Secrets come from Strongroom at run time, never pasted into a cell.
- Notebooks are not version control. Anything that becomes part of training or
  monitoring moves into the `risk-ml` repository as code with tests.

## When something breaks

| Problem | Try |
|---|---|
| Notebook will not start | `kiln notebook list`: you may already be at your GPU cap |
| Kernel dies on a large query | Read fewer columns, or use Polars' lazy reads |
| Trino authentication loops | Sign out of `kiln.quillmoor.example` and back in |
| Notebook gone in the morning | It was stopped for being idle; reopen and rerun |

Ask in `#team-risk-ml` if none of this works.
