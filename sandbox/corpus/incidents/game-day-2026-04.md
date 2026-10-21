---
title: "Game day April 2026: region failover"
---

# Game day April 2026: region failover

- **Date:** Wednesday 22 April 2026, 06:00 to 09:10 UTC
- **Organised by:** Lukas Brennand (Site Reliability), sponsored by Bram Oyelaran
- **Taking part:** Corinne Aske (Payments Core), Jonah Treadwell (Payouts), Rafe
  Lindgren (Ledger), Femi Haldane (communications)
- **Notes by:** Teodor Halloran (Platform); last reviewed 2026-10-07, when the action
  statuses were updated

## Why we did it

[ADR-021](../architecture/adr-021-active-passive-regions.md) commits us to running
production in a primary region with a warm standby in the secondary region. Until this
game day, the payments services had only ever failed over in staging. We wanted to know
three things: how long a real failover takes, whether we lose any ledger data, and
which steps exist only in people's heads.

## How it was set up

- **Declared as an incident.** Failover is always a declared incident, never an
  automatic one, so the game day ran as a SEV4 in `#inc-gameday-failover`, with Lukas
  as IC. A SEV4 declaration pages nobody, which was the point.
- **Announced to merchants** on Beacon as scheduled maintenance five business days
  ahead, following [status page communications](status-page.md).
- **Change ticket** raised in the Change Register and approved the week before.
- **Scope:** `card-auth`, `fx-quote`, `payout-gateway`, `settlement-batcher` and
  `ledger`. `merchant-api` and `merchant-hub` were left in the primary region and
  pointed across.
- **Targets:** failover complete within 30 minutes, with no ledger journal lost.

## What happened

| Time (UTC) | Step |
|---|---|
| 06:00 | SEV4 declared; everyone in the channel; Beacon maintenance window opens |
| 06:04 | `ks.payout-gateway.batch-scheduler` flipped to killed; queue drained with `pgw-admin drain --wait` |
| 06:11 | Drain complete: 3 batches acknowledged, none stuck |
| 06:12 | Ledger writes stopped in the primary region; replication lag to the secondary read at 0 seconds |
| 06:15 | Ledger standby promoted in the secondary region |
| 06:19 | `card-auth`, `fx-quote`, `payout-gateway` and `settlement-batcher` scaled up in the secondary region |
| 06:24 | Traffic switched to the secondary region |
| 06:24 to 06:26 | `card-auth` error rate 0.8% for about 90 seconds while connections moved |
| 06:31 | Kill switch back to live; first payout batch acknowledged at 06:44 |
| 06:38 | Failover declared complete: **26 minutes** from the first step |
| 06:38 to 08:15 | Running in the secondary region; checks below |
| 08:15 | Failback started, same steps in reverse |
| 08:49 | Failback complete: **34 minutes** |
| 09:10 | Beacon maintenance closed; SEV4 resolved |

The nightly reconciliation the following morning found no breaks, and no journal was
missing on either side.

## What we found

**Worked as written**

- The pause and drain before moving `payout-gateway`, exactly as in the
  [payout-gateway rollback runbook](../payments/payout-gateway-rollback.md). Nobody was
  tempted to skip it, because the runbook had been rehearsed.
- Ledger promotion: the standby was current, and the promotion took three minutes.
- Klaxon and Beacon, which are hosted outside both regions, were unaffected.

**Did not work, or only with help**

1. **Switchboard served stale values** in the secondary region for about four minutes
   after the switch: its cache there had not been refreshed since the previous
   evening. Nothing important had changed overnight, so no harm was done, but a kill
   switch flipped during a real incident might not have taken effect.
2. **Strongroom in the secondary region was read-only.** `settlement-batcher` tries to
   renew a short-lived credential on start-up and failed until Platform renewed it by
   hand at 06:22. In a real failover this would have delayed the first settlement file.
3. **Three Lantern dashboards**, including "payout-gateway overview", were hard-wired to
   the primary region and showed nothing during the test. The operations lead flew
   partly blind for an hour.
4. **The failback was slower** than the failover because the order of steps had never
   been written down; we worked it out in the channel.

## Actions

| Action | Owner | Status |
|---|---|---|
| Switchboard refreshes its cache in the standby region continuously, and reports its age | Teodor Halloran | Done |
| Strongroom's secondary region allows credential renewal during failover | Teodor Halloran | Done |
| Lantern dashboards take the region as a variable, defaulting to the active one | Lukas Brennand | Done |
| Failback written up as its own runbook | Teodor Halloran | In Progress |

All four are ENG tickets labelled `pir-action`, since the game day was a declared
incident; they appear on the [PIR actions tracker](pir-actions-tracker.md).

## Next time

The next game day, planned for November, before the year-end change freeze,
moves `merchant-api` and `merchant-hub` as well, and will be run by an IC who has not
done one before. Anyone who wants to observe can ask Lukas Brennand.
