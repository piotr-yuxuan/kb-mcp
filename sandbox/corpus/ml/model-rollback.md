---
title: "Rolling back a model in production"
---

# Rolling back a model in production

- Owner: Risk ML on-call (Klaxon rota `risk-ml-primary`)
- Escalation: Mireille Okonkwo, head of risk ML
- Last reviewed: 2026-10-07, after the September drill

> [!IMPORTANT]
> The rollback is one command: `modelctl pin fraudscore --version v6`. It takes effect
> within 2 minutes, with no deploy. Then tell Risk Operations in `#risk-ops`. Roll
> back when the decline rate jumps more than 30% and the checks below do not point
> to a real attack.

This runbook is for the fraud model served by `risk-scorer`. It assumes the champion
is `fraudscore-v7` and the rollback target is `fraudscore-v6`, which `risk-scorer`
keeps loaded in memory for exactly this purpose. When a future promotion changes the
pair, this page changes with it.

## When to roll back

### The main trigger

Roll back when the decline rate jumps more than 30%. The decline rate is the share of
authorisations that `card-auth` declines because the model's score is above its
threshold; issuer declines and rules-based declines are not part of it. The model is
tuned to decline about 0.5% of authorisations, so in practice a 30% jump means the
rate has gone above roughly 0.65%.

"Jumps" is measured against the same hour of the day averaged over the previous
seven days, so that a busy Saturday evening is compared with other Saturday evenings
rather than with a quiet Tuesday morning. The Lantern alert `RiskDeclineRateJump`
fires when the jump has lasted 15 minutes, and pages the Risk ML on-call. The panel
"Model decline rate against baseline" on the "risk-scorer overview" dashboard shows
the same comparison.

### Other reasons that justify a rollback

These need judgement, and a second opinion in `#team-risk-ml` if you can get one
within ten minutes:

- **The decline rate falls by half or more.** The model may be letting fraud through.
  This is quieter than a jump and does not page, but it is just as serious.
- **The score distribution collapses.** Most scores piling up near 0 or near 1 on the
  "Score histogram" panel usually means a feature has gone missing or changed unit.
- **A promotion in the last 48 hours** followed by complaints from merchants about
  declines, even below the 30% line.

### When not to roll back

- **A real attack.** If the extra declines are concentrated on a handful of sellers
  or a single marketplace, the model is probably doing its job. Rolling back would
  let the attack through. Tell Risk Operations and leave the model alone.
- **A `card-auth` problem.** If authorisations are timing out or failing more widely,
  start from [Runbook: card authorisation latency](../payments/card-auth-latency.md)
  instead.
- **Missing features for both models.** `v6` and `v7` read most of the same features.
  If a feature table is late or broken, pinning `v6` changes nothing; follow
  [Data quality alerts](../data/quality-alerts.md) and talk to `#team-data`.

| What you see | Spread across merchants? | Recent promotion? | Action |
|---|---|---|---|
| Decline rate up more than 30% | Yes | Either | Roll back |
| Decline rate up more than 30% | No, a few sellers | Either | Do not roll back; tell Risk Operations |
| Decline rate down by half | Yes | Yes | Roll back |
| Decline rate down by half | Yes | No | Check features first, then decide |
| Score histogram collapsed | Yes | Either | Check features; roll back if they look healthy |

## Before you pin: three checks, five minutes at most

Do not let these checks delay a clear case by more than five minutes. A rollback is
cheap to undo.

**1. Is it broad?** Run this in Trino, or use the "Declines by seller" panel:

```sql
SELECT seller_id,
       count(*) AS model_declines
FROM raw.risk_scorer_decisions
WHERE decided_at >= current_timestamp - INTERVAL '1' HOUR
  AND decision = 'decline_model'
GROUP BY seller_id
ORDER BY model_declines DESC
LIMIT 20;
```

If the top five sellers hold more than half of the declines, suspect an attack, not
the model.

**2. Are the features healthy?** Look at the "Feature null rates" panel. If one
feature has gone from almost never null to mostly null in the last few hours, the
cause is upstream, and rollback probably will not help (see above).

**3. What changed?**

```bash
modelctl history fraudscore --since 48h
```

A promotion, a threshold change or a pin by someone else in that window is the
likeliest cause of trouble.

## Rolling back

```bash
modelctl pin fraudscore --version v6 \
  --reason "Decline rate +41% against baseline since 14:05 UTC, broad across sellers"
```

What happens next:

1. The registry records a pin on `fraudscore`, which overrides the champion alias.
2. Every `risk-scorer` pod checks the registry every 30 seconds, sees the pin and
   switches to `v6`, which it already holds in memory.
3. `v6`'s own decline threshold comes with it. You do not set a threshold by hand.
4. Within 2 minutes every pod is scoring with `v6`. Nothing is deployed and no pod
   restarts.

Check that it worked:

```bash
modelctl status fraudscore
```

```text
model:      fraudscore
champion:   v7
pinned:     v6  (by risk-ml-oncall, 2026-09-09 14:22 UTC)
reason:     Rollback drill on staging
serving:    v6 on 18/18 pods
threshold:  v6 operating point
```

`serving: v6 on 18/18 pods` is what you are waiting for. On the dashboard, the
"Serving version by pod" panel turns from v7 to v6, and the decline rate should head
back towards its baseline within ten to fifteen minutes.

## Tell Risk Operations

Risk Operations must hear about every rollback straight away, before you start
investigating. `v6` declines a different set of honest buyers from `v7`, so the cases
they review change, merchants may ask about payments they did not expect to be
declined, and their daily figures will move.

Post in `#risk-ops` and mention the on-duty Risk Operations lead:

```text
Fraud model rolled back: fraudscore pinned to v6 at 14:22 UTC.
Why: model decline rate +41% against baseline since 14:05, broad across sellers.
Expect: declines back near normal by 14:40; v6 declines a different mix of payments.
Next update: 15:30 UTC, or sooner if anything changes.
Contact: Risk ML on-call in #team-risk-ml.
```

If merchants are affected, also declare an incident with `/klaxon declare` and follow
[Production incident management](../incidents/incident-management.md). The IC sets the
severity. A decline-rate jump that has reached many merchants' buyers is rarely
treated as minor; let the IC judge it. Your duties as the on-call engineer during
the incident are on [On-call rota and paging policy](../incidents/on-call.md).

## After the rollback

**Leave the pin in place.** A pin does not expire. It stays until someone removes it
on purpose, which is what you want while the cause is unknown.

**Find the cause.** The usual suspects, in the order we have met them:

1. A feature changed meaning upstream: a new currency, a renamed category, a unit
   change from pounds to pence.
2. A merchant integration change that altered the event sequence `v7` reads, such as
   a marketplace starting to send zero-amount verification authorisations.
3. Calibration drift after a large shift in traffic mix; see
   [Model drift monitoring](drift-monitoring.md).

**Undo the rollback** only when the cause is understood and fixed, and only with the
head of risk ML's agreement:

```bash
modelctl unpin fraudscore --reason "Upstream unit fix deployed; v7 scores checked on the last 6 hours"
```

Unpinning returns serving to the champion alias, again within 2 minutes. Tell Risk
Operations again, with the same template.

**If `v7` cannot come back**, the head of risk ML decides whether `v6` becomes the
champion again. That is a registry change recorded with a note, not something to do
from the on-call shift.

**Review.** If an incident was declared, the PIR follows the process on
[the PIR template page](../incidents/post-incident-review.md). Even without
an incident, write three lines in `#team-risk-ml` on what happened.

## Edge cases

**A pod reports that it does not hold `v6`.** New pods load both the champion and the
rollback target at start-up, but if one has been evicted and rescheduled mid-switch,
it fetches `v6` from the registry. That takes up to 90 seconds and still fits within
the 2 minutes. If `serving` stays short of all pods after 3 minutes, page the Risk ML
secondary.

**`v6` can no longer read today's features.** A nightly job runs
`modelctl check fraudscore --version v6`, which scores a sample of yesterday's
traffic with `v6`. If it fails, it pages Risk ML during working hours, because a
rollback target that cannot serve is no rollback target. Fix it before you need it.

**You want a version older than `v6`.** You can pin any registered version, but only
`v6` is kept loaded; anything older has to be fetched, may not match today's features,
and has not been checked. Do not do it without the head of risk ML.

**Both `v6` and `v7` are misbehaving.** Then the problem is almost certainly in the
features, not the models. If declines must stop while that is fixed, the kill switch
`ks.risk-scorer.score-declines` tells `card-auth` to stop declining on model scores
and keep only the rules. Flipping it needs the IC or the head of risk ML, and Payments
Core must be told; see [Feature flags and kill switches](../release/feature-flags.md)
for how kill switches work. Fraud losses rise while it is on, so it is a matter of
hours, not days.

**Someone else already pinned.** `modelctl status` shows who and why. Talk to them
before changing anything; two people pinning in turn is how a ten-minute problem
becomes an hour.

**During shadow mode of a new challenger.** Pinning does not stop shadow scoring. The
shadow period continues, but note the rollback in the challenger's shadow report,
because the comparison baseline changed.

## Who does what

| Role | During a rollback |
|---|---|
| Risk ML on-call | Runs the checks, pins, verifies, posts in `#risk-ops` |
| Risk ML secondary | Second opinion on borderline cases; takes over if pods do not switch |
| Head of risk ML | Agrees to any unpin; decides on the kill switch or on making `v6` champion |
| Risk Operations lead on duty | Adjusts the day's reviews; answers merchants through Support |
| IC, if an incident is declared | Owns severity and communication; you report to them |

## Past rollbacks

We have pinned `v6` twice since `v7` became champion on 2026-02-04. Both are worth
reading before your first on-call week.

**2026-03-18, about six hours.** A large marketplace began sending zero-amount card
verification authorisations ahead of every purchase. The sequence encoder had never
seen such events, read them as card testing, and the decline rate rose 52% against
baseline across that marketplace's sellers, then across others as buyers moved
between them. The on-call engineer pinned `v6` within 12 minutes of the page. Risk ML
filtered zero-amount verifications out of the event sequence, checked `v7` on the
afternoon's traffic, and unpinned at 21:40 UTC.

**2026-07-02, about forty minutes.** A feature describing the seller's account age
switched from days to seconds after an upstream change. Both models were affected,
but `v7` far more, because it relied on that feature for new sellers. The rollback
contained most of the damage; the real fix was upstream, and the unpin followed as
soon as Data Platform had corrected the column.

Neither became a declared incident: in both, the decline rate was back near its
baseline within 25 minutes of the page. Both times Risk Operations heard within five
minutes, which is the standard to keep.

## Questions

**Do I need approval to pin?** No. The on-call engineer may pin on their own judgement.
Approval is for unpinning.

**Does a pin survive a `risk-scorer` restart?** Yes. The pin lives in the registry,
and pods read it on start-up before they serve anything.

**Can I pin only some merchants?** No. The pin applies to all traffic. If only some
merchants are affected, that is a sign to look harder at whether it is an attack.

## Drills

We rehearse this runbook every quarter in staging (see
[Staging environments](../release/staging-environments.md)). At the last drill, on
2026-09-09, the pin took 74 seconds to reach every pod and the unpin 68 seconds. The
on-call engineer of the week runs the drill; the steps are exactly the ones above,
with "drill" in every `--reason`.
