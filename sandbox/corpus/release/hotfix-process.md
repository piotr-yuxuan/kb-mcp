---
title: "Hotfix process"
---

# Hotfix process

Owner: Platform (release engineering). Last reviewed: 2026-09-03.

A hotfix is a minimal change shipped on top of the release that is in production now, rather than from main. You need one when production must change and main is not in a state you want to ship.

## Is it a hotfix?

It is a hotfix when **both** are true:

- production has a bug that matters now: an open SEV1 or SEV2, or a SEV3 that the IC or your team lead wants fixed before the next release train; **and**
- main holds other changes that are not ready to ship, or you are rolling forward after a release that ran a migration ([Reverting a bad release](reverting-a-release.md) explains when).

If main is clean, it is not a hotfix: merge the fix to main and deploy it the normal way. If the faulty behaviour is behind a flag, switch the flag off first; you may not need a hotfix at all.

## Steps

1. **Say so.** In the incident channel if there is one, otherwise in your team channel: what is broken, which release you are fixing, who is doing it.

2. **Start the hotfix branch from the release in production.** Shipwright registers the branch, so that it will build from it:

   ```bash
   shipwright hotfix start merchant-api --from 12.6.0
   git fetch origin
   git switch hotfix/merchant-api-12.6.1
   ```

3. **Make the smallest fix that works.** No refactoring, no "while I was there". Bump the patch version in `shipwright.yaml`; Shipwright has already proposed it in the branch name.

4. **Open a pull request against the hotfix branch.** The usual approvals apply ([Code review guidelines](../engineering/code-review.md)); say in the title that it is a hotfix and reviewers will pick it up first.

5. **Merge and deploy.** Shipwright builds the merge commit on the hotfix branch and takes it through every stage. **The canary still runs.** Nothing skips it for a hotfix; a fix that makes things worse is worse during an incident, not better.

   ```bash
   shipwright deploy merchant-api --release 12.6.1 --env production
   ```

6. **Outside the deploy windows**, production stages need `--incident` naming the channel of a declared SEV1 or SEV2, and the IC's approval in Shipwright. A SEV3 waits for the next window.

7. **During a change freeze**, you also need a `CHG-` ticket; see [Change freeze calendar 2026](change-freeze-2026.md).

8. **Bring the fix to main within one working day.** Cherry-pick it, or merge the hotfix branch, then run:

   ```bash
   shipwright hotfix finish merchant-api
   ```

   Shipwright checks that the fix is on main and closes the branch. Until then it reminds your team channel every morning, because the next release from main would otherwise undo your fix.

## Afterwards

- If there was an incident, the hotfix goes in the timeline of its PIR ([template](../incidents/post-incident-review.md)), and any follow-up work becomes ENG tickets.
- If the hotfix was a stopgap, raise the ticket for the proper fix before you close your laptop.

## Numbers

Between January and September 2026 there were 23 hotfixes across all services. The median time from `hotfix start` to 100% of traffic was 1 hour 52 minutes, of which 30 minutes is the canary. Three were outside the deploy windows, all during SEV1 or SEV2 incidents.
