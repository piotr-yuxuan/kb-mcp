---
title: "Runbook: rolling back payout-gateway"
---

> [!IMPORTANT]
> Pause, drain, then roll back. Rolling `payout-gateway` back while batches are in flight can pay sellers twice.

| | |
|---|---|
| Service | `payout-gateway` |
| Owner | Payouts, `#team-payouts` (lead: Yusuf Achterberg) |
| Who runs this | The payments on-call, with a Payouts engineer if one is awake |
| Last reviewed | 2026-09-29, by Yusuf Achterberg |
| Time needed | 20 to 40 minutes, most of it waiting for the drain |

This runbook takes `payout-gateway` back to an earlier release safely. It is written for the payments on-call at three in the morning, so it is deliberately prescriptive: follow the steps in order, and if something does not match what the page says, stop and ask in `#inc-payments` before improvising. Paging, acknowledgement and escalation rules are in [On-call rota and paging policy](../incidents/on-call.md); this page does not repeat them.

## When to roll back

Roll back `payout-gateway` when either of these is true:

1. **`PGW-5021` errors exceed 2% of batches for 5 minutes after a deploy.**
2. **`PayoutQueueBacklog` fires.**

Both triggers assume that a recent release is the likely cause. If nothing has been deployed to `payout-gateway` in the last 24 hours, a rollback has nothing to go back to; go to "When rolling back will not help" below instead.

### Reading the first trigger

`PGW-5021 PAYOUT_BATCH_STUCK` means that a payout batch has not been acknowledged by the bank after 10 minutes. Every 15 minutes the scheduler cuts at least one batch per marketplace and currency, each of at most 500 payouts, so a normal cycle submits somewhere between 40 and 80 batches, not one. The Lantern dashboard "payout-gateway overview" has a panel, **Stuck batch ratio**, which divides the batches in `PGW-5021` by the batches submitted over the last two cycles. The trigger is that ratio staying above 2% for 5 consecutive minutes.

Because a batch can only become stuck 10 minutes after it was submitted, the first signal arrives at least 10 minutes after the first post-deploy batch, and often 20. A deploy that looked clean for a quarter of an hour is not yet in the clear.

### Reading the second trigger

`PayoutQueueBacklog` fires when more than 2,000 payouts are queued. A backlog means batches are not leaving fast enough: either the scheduler has stopped cutting them, or the bank is not acknowledging them, or a release has slowed down the batch builder. During a large marketplace's end-of-day burst the queue can briefly approach the threshold; if the alert fires and resolves within one cycle, note it in `#team-payouts` and do nothing else.

## Before you start

Take two minutes for these. They prevent the two expensive mistakes: paying twice, and breaking the ledger.

- [ ] **Open an incident** if merchants are affected, with `/klaxon declare`, and work in `#inc-payments`. Severity is set by the incident process in [Production incident management](../incidents/incident-management.md), not by this runbook.
- [ ] **Find the target release.** It is normally the release that was running before the last deploy. The deploy notifications in `#team-payouts` list each release with its predecessor, and the running release is reported by `pgw-admin status` (below).
- [ ] **Check for a ledger schema migration** between the target release and the current one. Never roll back across a ledger schema migration without the Ledger team. An older `payout-gateway` writes payout journals in the shape the ledger expected at the time; after the migration, the ledger may reject those journals or, worse, accept and misfile them. Each release note has a "Migrations" line, and Shipwright can list what has run:

  ```bash
  shipwright migrate ledger --status
  ```

  If a ledger migration ran after the target release was built, stop here and page the Ledger rota in Klaxon. Expand-then-contract migrations, as described in [Database migrations](../release/database-migrations.md), usually make the rollback safe, but the Ledger team decides that, not the on-call.
- [ ] **Note the time against the cut-offs.** Pausing batches close to a currency's cut-off moves payouts to the next business day. See [Settlement windows and cut-off times](settlement-cutoffs.md), and tell `#inc-payments` if a cut-off will be missed.

## Step 1: pause the batch scheduler

In Switchboard, open the kill switch `ks.payout-gateway.batch-scheduler` and flip it to **killed**. Put the incident channel in the reason field.

With the switch flipped, the scheduler stops cutting new batches. Nothing is lost: `merchant-api` keeps accepting payouts, the ledger keeps reserving the amounts, and the payouts wait in the queue until the scheduler resumes.

Confirm the pause:

```bash
shipwright exec payout-gateway -- pgw-admin status
```

```text
release:            4.38.2
scheduler:          paused (ks.payout-gateway.batch-scheduler)
queued payouts:     2,418
in-flight batches:  7
oldest in-flight:   4m12s
stuck batches:      0
```

`PayoutQueueBacklog` will keep firing while the scheduler is paused, because the queue can only grow. Acknowledge it in Klaxon and say so in the channel; do not change its threshold.

## Step 2: drain the payout queue

```bash
shipwright exec payout-gateway -- pgw-admin drain --wait
```

**Why this step exists.** When Shipwright replaces the pods, the new pods run `payout-gateway`'s start-up recovery, which resubmits every batch that has no recorded acknowledgement. If the bank had already accepted the original file, it now receives a second file for the same payouts, with a new file reference from `settlement-batcher`, and its duplicate check does not catch it. In-flight batches would be resubmitted and paid twice. Draining first means there is nothing in flight for recovery to find.

`drain --wait` takes no new work from the queue and blocks until every in-flight batch has either been acknowledged by the bank or has passed the 10-minute mark and been marked stuck. It gives up after 20 minutes. A healthy drain looks like this:

```text
draining payout-gateway (release 4.38.2)
  in-flight batches: 7
  12:04:10  batch b_9f2c41 acknowledged
  12:04:52  batch b_9f2c47 acknowledged
  ...
  12:09:31  batch b_9f2c58 stuck (PGW-5021), left for manual resolution
drained: 6 acknowledged, 1 stuck, 0 in flight
```

Batches marked stuck are safe for the next step. No release of `payout-gateway` resubmits a stuck batch on its own; a Payouts engineer resolves each one with our settlement bank's operations desk, and only then is it either confirmed or released back to the queue.

If the drain gives up with batches still in flight, do not continue. Post the output in `#inc-payments` and page the Payouts rota: a batch that is neither acknowledged nor stuck after 20 minutes means something other than the release is wrong.

## Step 3: roll back

```bash
shipwright rollback payout-gateway --to <release>
```

For example, `--to 4.38.1`. Shipwright replaces the pods one at a time and reports when the rollout is complete; for `payout-gateway` that takes about four minutes. Leave the kill switch flipped throughout.

## Step 4: check, then resume

1. Run `pgw-admin status` again. Expect the target release, the scheduler still paused, nothing in flight.
2. Flip `ks.payout-gateway.batch-scheduler` back to **live**.
3. Watch the next two cycles, 30 minutes in all, on "payout-gateway overview":
   - **Stuck batch ratio** stays at or near zero;
   - **Queued payouts** falls with each cycle;
   - `PayoutQueueBacklog` resolves once the queue drops back under 2,000.

A backlog of 5,000 payouts usually clears in two or three cycles. If the stuck ratio climbs again on the earlier release, the release was not the cause: pause the scheduler once more and treat it as "When rolling back will not help".

## Step 5: afterwards

- **Tell Support** in `#inc-payments` how long payouts were paused and whether any missed a cut-off; they answer merchants from [Payout delays: what to tell merchants](../support/payout-delay-faq.md).
- **Resolve stuck batches** with Payouts during business hours, one by one, before the end of the day.
- **Watch the next reconciliation.** The nightly run compares our payout journals with the bank's statement, and a rollback is exactly the kind of event that produces breaks. See [Runbook: ledger reconciliation breaks](ledger-reconciliation.md).
- **Block the bad release.** Say in the `#team-payouts` deploy thread that the release must not be deployed again, and open a ticket for the fix.
- **Review.** If the incident process calls for a PIR, use the [PIR template](../incidents/post-incident-review.md), and include the drain output and the kill switch timings.

## When rolling back will not help

| Situation | What it usually means | What to do |
|---|---|---|
| Backlog or stuck batches with no deploy in the last 24 hours | The bank or the link to it is slow or down | Pause the scheduler, keep it paused, page Payouts; they call the settlement bank's operations desk |
| Drain never finishes | Acknowledgements are not arriving at all | Same as above; do not roll back |
| Stuck ratio rises again after the rollback | The release was a coincidence | Pause, then investigate with Payouts |
| Every batch for one currency is stuck | That currency's rail or file format | Check `settlement-batcher` logs for the currency; page Payouts |

## Edge cases

**Someone already flipped the kill switch.** Read the reason on the switch in Switchboard and find that person in the channel before doing anything else. Two people running this runbook in parallel is how drains get interrupted.

**Rolling back more than one release.** The steps are the same. Check for ledger migrations across the whole range, not just the last step.

**The target is older than 4.13.** Do not go below 4.13. Releases before it can start a retry storm after `PGW-5021`; see [payout-gateway 4.13 release notes](release-notes-payout-gateway-4-13.md).

**The deploy itself ran a migration on `payout-gateway`'s own database.** Shipwright refuses to roll back past a migration it has recorded for the service. That refusal is correct; page Payouts.

**A cut-off is close.** If the drain and rollback would run past a cut-off anyway, finish them properly. A day's delay is recoverable; a double payment to a few thousand sellers takes weeks of clawbacks.

## Things not to do

- Do not restart or delete `payout-gateway` pods to "unstick" batches. A restart is a small rollback without the drain: recovery resubmits whatever was in flight.
- Do not purge or edit the payout queue by hand.
- Do not resubmit a stuck batch yourself, with `pgw-admin` or any other way.
- Do not skip the drain because "it is only one batch". One batch is up to 500 payouts.

## Why the runbook is shaped like this

The pause, the drain and the stuck state all came out of ENG-1, the payout-gateway resilience epic of spring 2025. Before it, the only way to stop payouts quickly was to scale the service to zero, which left batches half-recorded, and a rollback was a plain redeploy. The kill switch arrived in 4.11 and the drain command in 4.10; the batch cap in 4.12 limits how much a single stuck batch can hold. The [payout-gateway 4.10 release notes](release-notes-payout-gateway-4-10.md) and their successors describe each change.

## Related pages

- [Payments platform architecture](platform-architecture.md), for where `payout-gateway` and `settlement-batcher` sit
- [Settlement windows and cut-off times](settlement-cutoffs.md)
- [Database migrations](../release/database-migrations.md)
- [On-call rota and paging policy](../incidents/on-call.md)
