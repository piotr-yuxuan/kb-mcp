---
title: "Runbook: card authorisation latency"
---

*Payments Core runbook. Owner: Nadia Ferreira. Last reviewed 2026-10-14. Questions in `#team-payments-core`; during an incident, in `#inc-payments`.*

Slow authorisations cost merchants sales: buyers abandon a checkout that hangs, and some marketplaces time out their own calls to us after a couple of seconds. This runbook covers what to look at and which levers to pull when `card-auth` gets slow. It assumes you know the authorisation flow; if not, read [Payments platform architecture](platform-architecture.md) first, ideally not during the incident.

## The alert

**`CardAuthP99High`**: `card-auth` p99 over 800 ms for 10 minutes.

800 ms is the p99 budget for `card-auth`, measured from `merchant-api`'s call to `card-auth`'s answer. The alert pages the payments on-call. It is evaluated per region; the active region is the one that matters.

Two error codes usually travel with it:

| Code | Meaning | Typical cause |
|---|---|---|
| `CAU-1207 ISSUER_TIMEOUT` | The issuer did not answer within 3 seconds | One issuer, or the card scheme's network in front of it, is slow or down |
| `CAU-1301 HSM_QUEUE_FULL` | The hardware security module queue is full | More cryptographic work than the modules can absorb: traffic spike, too many pods, or a module out of service |

An authorisation that ends in `CAU-1207` is declined to the merchant with a "try again" response; one that ends in `CAU-1301` is rejected before it reaches the issuer. Both count towards the p99, because both are slow before they fail.

## First five minutes

1. Open the Lantern dashboard **"card-auth overview"** at `lantern.quillmoor.example/d/card-auth-overview`. Set the range to the last hour.
2. Look at the panel **Latency by stage**. It splits each authorisation into the stages below and shows their p99s stacked. Whichever stage grew is your lead.
3. Look at **Deploys and flag changes**, the annotation strip along the top of every panel. A deploy or a Switchboard change in the 30 minutes before the rise is the first suspect.
4. If merchants are affected, open an incident with `/klaxon declare` and follow [Production incident management](../incidents/incident-management.md); it sets the severity, not this page.

### Where the 800 ms goes

The stages, with their usual p99 on a normal weekday afternoon:

| Stage | Usual p99 | Panel |
|---|---|---|
| Request parsing and merchant checks | 15 ms | Internal |
| `risk-scorer` call | 45 ms | Risk score |
| `fx-quote` call, cross-currency only | 20 ms | FX |
| Hardware security module operations | 12 ms | Security module queue |
| 3DS checks, when one is made (the buyer's time on a challenge is not counted) | 250 ms | 3DS |
| Acquiring bank and issuer round trip | 480 ms | Issuer |
| Ledger journal, written asynchronously | not on the path | Ledger writes |

The numbers do not add up to the p99 of the whole, because the slowest requests are rarely slow at every stage. The point of the table is the shape: the issuer is the largest part, and everything we control should stay small.

## Find the stage, pick the lever

```text
Which stage grew?
|
+-- Issuer, with CAU-1207 rising
|      one issuer or a few?   --> Lever C (tell, do not tune)
|      all issuers at once?   --> check the acquiring bank link, page Payments Core
|
+-- Security module queue, with CAU-1301 rising
|      pods near 40?          --> Lever D (do not add pods)
|      traffic spike?         --> Lever A, within the limits, and Lever D
|
+-- 3DS
|      --> Lever B
|
+-- Internal, risk score or FX, rising together with CPU
|      --> Lever A
|
+-- Started just after a deploy
       --> roll the release back first, then look again
```

For the last branch, see [Reverting a bad release](../release/reverting-a-release.md); the general release process applies to `card-auth`.

## Lever A: scale the pods

`card-auth` runs between 12 and 40 pods. A HorizontalPodAutoscaler keeps it inside that range on in-flight requests per pod as well as CPU (since the September 2025 incident, when waiting workers used no CPU), and the range is the contract: never fewer than 12, so a single node failure does not hurt; never more than 40, because each pod holds sessions to the hardware security modules, and beyond 40 the modules spend more time switching between sessions than doing work, which makes `CAU-1301` worse, not better.

If the autoscaler is lagging behind a spike, raise the floor:

```bash
kubectl --context prod-primary -n card-auth patch hpa card-auth \
  --type merge -p '{"spec":{"minReplicas":30}}'
```

New pods take about 90 seconds to warm up. Put the floor back to 12 once the incident is over, and say so in the channel:

```bash
kubectl --context prod-primary -n card-auth patch hpa card-auth \
  --type merge -p '{"spec":{"minReplicas":12}}'
```

Do not set `maxReplicas` above 40, even briefly.

## Lever B: reduce 3DS step-up sampling

When `risk-scorer` flags a transaction as uncertain, `card-auth` can send it to a 3DS step-up instead of authorising it straight away. The share of flagged transactions that get a step-up is set by the Switchboard flag `sb.card-auth.stepup-sampling`, a number between 0 and 1. Its normal value is `1.0`: every flagged transaction is stepped up.

When the 3DS stage itself is slow, reduce 3DS step-up sampling with `sb.card-auth.stepup-sampling`. Each step-up removed takes the slowest stage off that authorisation.

| Value | Effect | Who may set it |
|---|---|---|
| `1.0` | Normal | Anyone, to restore |
| `0.5` | Half of flagged transactions stepped up | Payments on-call |
| `0.25` | A quarter stepped up | Payments on-call, telling `#team-risk-ml` at once |
| below `0.25` | Fraud exposure grows quickly | Only with Mireille Okonkwo or the Risk ML on-call |

Step-ups that the issuer itself requests, and those that regulation requires, are not affected by the flag; they always happen. Lowering the flag shifts some fraud risk back to us, which is why Risk ML must know within minutes and why it goes back to `1.0` as soon as 3DS recovers. The flag change needs no deploy and shows on the dashboard's annotation strip.

## Lever C: issuer timeouts

`CAU-1207` means the issuer did not answer within 3 seconds. There is very little to do about a slow issuer except to be honest about it.

- The panel **Issuer timeouts by issuer** shows whether one issuer or many are affected. One issuer is common and usually brief.
- Do not raise the issuer timeout. It used to be 5 seconds; ENG-3 lowered it to 3 seconds because a buyer who has waited 3 seconds has usually left, and every second we hold a request also holds a pod.
- If one issuer is timing out for more than 15 minutes, post the issuer name and the affected share in `#inc-payments` so that Support can answer merchants, and consider a Beacon notice through the incident process.
- If every issuer is slow at once, the problem is between us and the card schemes. Check the **Acquiring bank link** panel and page the Payments Core rota.

## Lever D: the hardware security module queue

`CAU-1301` means the hardware security module queue is full: requests for cryptographic operations are waiting longer than the queue allows, and new ones are refused.

1. Check **Pods** on the dashboard. If `card-auth` is at or near 40 pods, do not add more (see Lever A).
2. Check **Security module queue** per module. If one module's latency is flat at zero, it is out of service and its share of work is landing on the others; page Payments Core, who will ask Security to bring it back.
3. If all modules are healthy and the queue is full only at the peak of a traffic spike, the spike will pass. Lowering step-up sampling (Lever B) helps a little, since every step-up costs extra cryptographic work.

Load tests during ENG-3 first produced `CAU-1301` at about 2.5 times our normal peak traffic. That is the headroom we plan with; the November peak is the only time we have come close to it.

## What it looks like in practice

A composite of several real evenings, to show the order of work rather than any one incident.

At 19:42 UK time `CardAuthP99High` pages: p99 has been around 1.1 seconds for 10 minutes. The on-call opens "card-auth overview". **Latency by stage** shows the issuer stage doubling while everything else is flat; **Deploys and flag changes** shows nothing since the morning. **Issuer timeouts by issuer** shows `CAU-1207` concentrated on one large issuer, with the rest normal. This is Lever C: nothing to scale, nothing to switch. The on-call posts the issuer and the share of affected authorisations in `#inc-payments`, Support prepares an answer for merchants who ask, and the incident process decides whether it deserves a Beacon notice. At 20:25 the issuer recovers and the alert resolves on its own.

The same evening could have gone differently. Had the 3DS stage grown instead, the on-call would have set `sb.card-auth.stepup-sampling` to `0.5`, told `#team-risk-ml`, and set it back once the stage recovered. Had **Pods** shown `card-auth` pinned at 40 with `CAU-1301` climbing, the right move would have been to leave the pod count alone and look at the security modules, however tempting more pods look.

The lesson in each case is the same: find the stage first. Every lever on this page helps with one stage and does nothing, or harm, for the others.

## Things not to do

- Do not restart all `card-auth` pods at once. Each pod reopens its sessions to the hardware security modules on start-up, and a full restart fills their queue.
- Do not turn off `risk-scorer` calls to save latency. The fraud model's scores are not optional; if `risk-scorer` is slow, page Risk ML.
- Do not change the issuer timeout during an incident.
- Do not leave `sb.card-auth.stepup-sampling` below `1.0` overnight without Risk ML's agreement in writing in the channel.

## After the incident

- Reset the autoscaler floor to 12 and the step-up flag to `1.0`.
- Write a short summary in `#inc-payments`: stage, cause, levers used, how long each lever stayed in place.
- If the incident process calls for a PIR, use the [PIR template](../incidents/post-incident-review.md). The PIR for the September 2025 issuer timeouts, [Incident report 2025-09-17: card authorisation latency](../incidents/report-2025-09-17-card-auth-latency.md), is a good example of how to write up a `CAU-1207` incident.

## History

ENG-3, Card authorisation latency, ran in the second half of 2025 and gave this runbook most of its levers:

- the issuer timeout lowered from 5 to 3 seconds;
- the latency-by-stage panel on "card-auth overview";
- the `sb.card-auth.stepup-sampling` flag, which until then was a configuration value that needed a deploy;
- the 12 to 40 pod range, set after load tests found `CAU-1301` under load and traced it to too many pods sharing the modules.

## Metric reference

| Metric | What it measures |
|---|---|
| `cardauth_request_duration_seconds` | End-to-end authorisation latency, by region and outcome |
| `cardauth_stage_duration_seconds` | Latency of each stage, labelled `stage` |
| `cardauth_issuer_timeouts_total` | `CAU-1207` count, by issuer |
| `cardauth_hsm_queue_depth` | Requests waiting for a hardware security module, by module |
| `cardauth_hsm_rejections_total` | `CAU-1301` count |
| `cardauth_stepups_total` | 3DS step-ups started, by reason (`risk`, `issuer`, `regulatory`) |
