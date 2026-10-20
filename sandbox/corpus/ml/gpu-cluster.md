---
title: "GPU cluster quotas and scheduling"
---

# GPU cluster quotas and scheduling

- **Owner:** Risk ML, who run Kiln; maintainer Matteo Quaye
- **Infrastructure:** Platform runs the Kubernetes node pool underneath
- **Ask in:** `#team-risk-ml`, with "Kiln" in the first line
- **Last reviewed:** 2026-08-27

Kiln is the scheduler for our GPU cluster. Any team may use it: Risk ML trains the
fraud model on it, Data Platform runs a few embedding jobs, and people from other
teams use notebooks for one-off analysis. This page explains the queues, the quotas,
how preemption works, and how to submit a job without upsetting your colleagues.

The quotas and the preemption rules on this page came out of ENG-23 ("Kiln GPU
quotas", sprints 25 to 31, 2026-03-16 to 2026-06-21). Before that, Kiln was first
come, first served, and a single forgotten notebook could hold four GPUs over a bank
holiday weekend.

## The cluster at a glance

| | |
|---|---|
| Nodes | 12, each with 8 GPUs of 80 GB memory |
| GPUs in total | 96 |
| Runs on | A dedicated Kubernetes node pool, `gpu-pool`, managed by Platform |
| Scratch storage | `/kiln/scratch`, shared, files removed after 14 days |
| Home storage | `/kiln/home/$USER`, 200 GB each, backed up nightly |
| Warehouse access | Trino, with your own credentials |
| Container images | `risk-ml-train` and `risk-ml-notebook`, rebuilt monthly |

Kiln runs on Kubernetes like everything else (see
[ADR-010: Run services on Kubernetes](../architecture/adr-010-kubernetes.md)), but you
should never need `kubectl` to use it. If you find yourself reaching for it, ask in
the channel first.

## The three queues

Every job goes to one of three Kiln queues: `train-long`, `train-short` or
`interactive`.

| Queue | Meant for | Longest run | GPUs per job | Can be preempted? |
|---|---|---|---|---|
| `train-long` | Full training runs, multi-node jobs | 72 hours | Up to 16 | No |
| `train-short` | Experiments, tuning sweeps, batch scoring | 6 hours | Up to 8 | Only when running on borrowed GPUs |
| `interactive` | Notebooks, debugging, profiling | 12 hours | Up to 2 per person | Yes, when idle for 4 hours |

### `train-long`

For runs you have tested and expect to finish. A job here is never preempted, which
is why it is also the only queue with a waiting line in a busy week: Kiln will not
start a `train-long` job unless your team has enough quota free for its whole
duration. The fraud model's sequence encoder trains here, on 8 GPUs, for about 9
hours; see [Training the fraud model](fraud-model-training.md).

Jobs that span more than one node (more than 8 GPUs) are allowed only on this queue,
because a multi-node job interrupted halfway wastes every node's work.

### `train-short`

The workhorse. Most experiments, hyperparameter sweeps and batch scoring jobs belong
here. The 6-hour limit is hard: Kiln stops the job at 6 hours whether or not it has
finished, so checkpoint (see below). `train-short` is the only queue where your team
can borrow idle GPUs beyond its quota.

### `interactive`

For notebooks and anything where a person is at the keyboard. Each person may hold at
most 2 GPUs here at a time. Idle interactive jobs are preempted after 4 hours: Kiln
considers a job idle when its GPUs have stayed under 5% utilisation and its notebook
kernel has had no activity for 4 hours in a row. Thirty minutes before that point,
Kiln sends you a chat message; any cell you run resets the clock.

Preemption ends the session. Files in your home directory survive, but anything held
only in the kernel's memory does not. The notebook set-up itself is described on
[Notebook environment](notebooks.md).

### Which queue should I use?

Some examples from the last quarter, to calibrate your instinct:

| Job | Queue | Why |
|---|---|---|
| Final `fraudscore` encoder training, 8 GPUs, about 9 hours | `train-long` | Too long for `train-short`, and must not be interrupted |
| Sweep of 24 tree configurations, 1 GPU each, 40 minutes each | `train-short` | Short, restartable, happy to borrow idle GPUs |
| Scoring 13 months of history with a new candidate | `train-short` | Batch job; split by month so each part fits in 6 hours |
| Exploring merchant graph features in a notebook | `interactive` | A person is at the keyboard |
| Profiling why the encoder is slow on long sequences | `interactive` | Short, hands-on, 1 GPU |
| A 30-hour embedding refresh for Data Platform | `train-long` | Longer than any other queue allows |

If a job does not fit `train-short` only because it is slightly too long, it is
usually better to split it or checkpoint it than to move it to `train-long`, where it
will wait for quota.

## Quotas

Each team gets 8 GPUs by default. The quota counts every GPU your team holds at the
same moment on `train-long` and `train-short` together. Interactive GPUs do not count
against the team quota; they are capped per person instead, so that an analyst's
notebook never stops a training run from starting.

| Team | Quota | Since | Note |
|---|---|---|---|
| Risk ML | 32 GPUs | 2026-06-22 | Raised under ENG-23 for the encoder and experiments |
| Data Platform | 8 GPUs | 2026-06-22 | Default |
| Every other team | 8 GPUs | 2026-06-22 | Default; most teams use none in a typical week |

The totals add up to more than 96 on paper. That is intended: on a normal day most
teams use little or nothing, and Kiln only guarantees what is actually free.

Check where your team stands:

```bash
kiln quota --team risk-ml
```

```text
team        quota  in use  borrowed  waiting
risk-ml     32     24      6         1 job (train-long, 16 GPUs)
```

### Borrowing

When the cluster has idle GPUs, a `train-short` job may run on more GPUs than your
team's quota leaves free. Those borrowed GPUs come back as soon as their owners need
them: Kiln gives the borrowing job 10 minutes' notice with a termination signal, then
stops it. Borrow for work that checkpoints, never for a run you cannot restart.

### Asking for more

Post in `#team-risk-ml` with the team, the number of GPUs, the period, and what you
will run. Use this shape:

```text
Kiln quota request
Team: Data Platform
Asking for: 16 GPUs (8 above default)
Period: 2026-09-07 to 2026-09-25
Why: embedding refresh for the seller catalogue; 3 runs of about 30 hours each on train-long
Cost centre: Data Platform
```

The head of risk ML, Mireille Okonkwo, approves requests up to 16 GPUs for a team.
Above that, Bram Oyelaran, head of platform engineering, also has to agree, because a
larger standing quota usually means more nodes. Temporary increases end on the date
you gave; nobody has to remember to take them back.

## Preemption, in order

When Kiln needs GPUs for a job that is entitled to them, it frees them in this order
and stops as soon as it has enough:

1. Interactive jobs that have been idle for 4 hours or more.
2. `train-short` jobs running on borrowed GPUs, newest first.
3. Nothing else. `train-long` jobs, and `train-short` jobs within their team's quota,
   are never preempted to make room.

A job that is preempted is marked `PREEMPTED`, not `FAILED`, in `kiln status`, and
`train-short` jobs are requeued automatically once, if they were submitted with
`retry_on_preemption: true`.

## Submitting a job

A job is a YAML file and a command. This is a typical `train-short` sweep:

```yaml
name: encoder-sweep-heads
team: risk-ml
queue: train-short
gpus: 4
image: risk-ml-train:2026.08
command: ["python", "-m", "sweeps.encoder", "--heads", "2,4,8"]
retry_on_preemption: true
checkpoint_dir: /kiln/scratch/risk-ml/encoder-sweep-heads
env:
  TRINO_CATALOG: iceberg
labels:
  experiment: sequence-features
```

```bash
kiln submit job.yaml
kiln status --team risk-ml
kiln logs <job-id> --follow
kiln cancel <job-id>
```

Secrets, such as a token for a service you call, come from Strongroom, never from the
YAML file; see [Using Strongroom](../security/strongroom-how-to.md).

### Checkpointing

Any job longer than about 30 minutes should checkpoint. On preemption or at the
`train-short` time limit, Kiln sends the termination signal and waits 10 minutes
before stopping the job. Use them:

```python
import signal
import sys

import torch

stop_requested = False


def request_stop(signum, frame):
    global stop_requested
    stop_requested = True


signal.signal(signal.SIGTERM, request_stop)

for step, batch in enumerate(loader, start=start_step):
    loss = train_step(model, optimiser, batch)
    if step % 500 == 0 or stop_requested:
        torch.save(
            {"step": step, "model": model.state_dict(), "optimiser": optimiser.state_dict()},
            f"{checkpoint_dir}/latest.pt",
        )
    if stop_requested:
        sys.exit(0)
```

On restart, load `latest.pt` if it exists and carry on from `step + 1`.

## Costs

GPU hours are charged to the submitting team's cost centre every month, at an internal
rate per GPU hour that Finance sets. Idle interactive time counts, which is another
reason not to leave notebooks running. How cloud costs are tagged and reviewed is on
[Cloud cost allocation and tagging](../finance/cloud-cost-allocation.md); Kiln adds
the right tags to every job, so you do not need to.

```bash
kiln usage --team data --month 2026-09
```

## Etiquette

- Do not run training in `interactive` to avoid waiting for `train-short`. Kiln
  notices long, busy interactive jobs, and so do we.
- Do not split one job into several to slip under the per-job limit on `train-short`.
- Start `train-long` runs early in the week where you can. A run that fails at 03:00 on
  Saturday waits for Monday.
- Cancel jobs you no longer need instead of waiting for them to time out.
- Clean `/kiln/scratch` yourself when an experiment is over; the 14-day sweep is a
  safety net.

## Maintenance

Platform upgrades the `gpu-pool` node pool with the rest of the cluster. During the
Kubernetes 1.31 upgrade (ENG-9), nodes were drained a few at a time over a week, and
Kiln held new `train-long` jobs until the last node was back. Announcements go to
`#team-risk-ml` and `#team-data` at least five working days ahead.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Job stays `PENDING` on `train-long` | Not enough quota free for the whole job | Check `kiln quota`; wait, or ask for a temporary increase |
| Job `PREEMPTED` on `train-short` | It was on borrowed GPUs | Resubmit with `retry_on_preemption: true` and checkpoints |
| Notebook gone overnight | Idle for 4 hours | Save work to your home directory; see the notebook page |
| Out of GPU memory at start-up | Batch size set for a larger slice | Halve the batch, or ask for more GPUs |
| `kiln submit` rejects the image | Image older than three months | Rebuild from the current base image |
| Trino queries fail inside a job | Expired credentials | Refresh them; see [Requesting warehouse access](../data/warehouse-access.md) |

## Questions

**Can I ask for an exemption from the 4-hour idle rule?** No. A long-running
computation in a notebook is not idle, because its GPUs are busy; a notebook waiting
for you to come back from lunch and a meeting is. Submit long work as a job.

**Does my team's quota reset at any point?** No, it is a ceiling on what you hold at
once, not a monthly allowance. Monthly limits are a matter for your budget.

**Can two teams share one job?** A job belongs to one team and is charged to it. Agree
between yourselves who submits it.

If none of this helps, post the job identifier in `#team-risk-ml`. Matteo Quaye or
whoever is on Kiln duty that week will look within the working day.
