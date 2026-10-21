---
title: "Reverting a bad release"
---

# Reverting a bad release

> [!NOTE]
> Maintained by release engineering (Platform) with Site Reliability. Contacts: Bram Oyelaran and Lukas Brennand. Last reviewed on 2026-08-12.

A release is out and something is wrong. Before you touch anything, take thirty seconds to choose the right way out, because the fastest-looking option is not always the safest one. In order of preference:

1. **A revert commit through the pipeline.** The default. Main and production stay in agreement, and the revert is tested like any other change.
2. **Redeploy the previous release with Shipwright.** For urgency only: merchants are being hurt and 90 minutes is too long to wait.
3. **Roll forward.** When the bad release ran a database migration, going back to the old code is often worse than the bug. Fix forward instead.

One thing comes before all three whenever it applies: if the new behaviour is behind a Switchboard flag, switch the flag off. That takes seconds and needs no deploy.

## Decide

| What you know | Release ran a migration? | Impact | Do this |
|---|---|---|---|
| The new behaviour is behind a flag | Either | Any | Turn the flag off first, then decide whether anything else is needed |
| Canary analysis stopped the release | Either | Canary traffic only | Nothing to undo in production; land a revert commit or a fix on main |
| Bug found after full rollout, a workaround exists | No | SEV3, SEV4 or none | Revert commit through the pipeline |
| Bug found after full rollout, merchants affected | No | SEV1 or SEV2 | Redeploy the previous release, then land the revert commit |
| Any bug | Yes | Any | Roll forward with a fix through the [hotfix process](hotfix-process.md) |
| Only a configuration value changed | No | Any | Revert commit for the configuration change; redeploy the previous release if SEV1 or SEV2 |
| Two services were changed together | Either | Any | Undo the consumer first, then the provider, or neither; ask in `#team-platform` |

Severities follow [Production incident management](../incidents/incident-management.md). If you cannot tell a SEV2 from a SEV3, use the higher one for this table and let the IC decide the rest.

## First, is it the release?

A good share of "bad releases" are coincidences. Before undoing anything, check two things on Lantern:

- **Timing.** Every Shipwright stage is drawn as an annotation on the service's graphs. Did the symptom start with the canary or a rollout wave, or before it? A symptom that began twenty minutes before your canary is not your release.
- **Shape.** If errors are spread evenly across old and new pods during a partial rollout, the cause is probably elsewhere: an upstream dependency, a traffic spike, the issuer. If they concentrate on the new pods, it is the release.

`shipwright status <service>` shows which release each group of pods runs, which helps during a partial rollout.

Undoing a release that did not cause the problem costs you twice: the time spent undoing it, and the false comfort afterwards while the real cause carries on.

## Option 1: a revert commit through the pipeline

This is the default because it keeps everything honest. Main stops containing the bad change, so the next release from main will not bring it back, and the revert itself is built, tested, staged and put through the canary like any other change.

```bash
git switch main
git pull --ff-only
git log --oneline merchant-api-12.3.2..merchant-api-12.4.0   # what shipped
git revert --no-edit 3f9c2a1
git push origin HEAD:revert/merchant-api-12.4.0
```

For a squash-merged pull request, revert the single squash commit. For a merge commit, name the parent you are going back to: `git revert -m 1 <merge-sha>`. If several commits shipped in the release and only one is at fault, revert only that one. Reverting the whole release throws away good work and usually conflicts with something.

Open a pull request titled `Revert "<original title>"`, link the incident channel or the bug ticket, and ask for review in your team channel. A pure revert still needs the usual approvals ([Code review guidelines](../engineering/code-review.md)), but reviewers drop what they are doing for one. Do not mix a fix into a revert: a revert should be reviewable in under a minute.

Once merged, the revert becomes a new release (12.4.1 in the example above) and goes through the five stages described on [How code reaches production](deployment-pipeline.md). Allow about 90 minutes from merge to full rollout. The deploy windows apply.

## Option 2: redeploying the previous release

Use this when merchants are being hurt now: a SEV1 or SEV2, or whenever the IC asks for it. It is faster because the previous release already exists and has already run in production.

```bash
# What ran before?
shipwright releases notify --env production --limit 5

# Put it back
shipwright deploy notify --release 3.8.4 --env production \
  --reason "revert 3.9.0: webhook signatures rejected" \
  --incident inc-webhook-signatures
```

What Shipwright does differently for a redeploy of an earlier release:

- It skips build, test and staging, because the artefact already passed them.
- It skips the canary and goes out in two waves, 50% then 100%, with a 3-minute pause. It usually completes in under 10 minutes.
- It allows this outside the deploy window when `--incident` names the channel of an open SEV1 or SEV2 and the IC approves in Shipwright.
- It accepts only a release that ran in production in the last 14 days. Anything older has not met today's dependencies and must go through the full pipeline.
- It refuses a release older than the latest migration applied for that service. See option 3.

After the redeploy, production runs older code than main. Shipwright marks the service as **diverged** and will not deploy it from main again until a revert commit for the bad change has merged, because the next release would otherwise ship the bug a second time. A redeploy is therefore always followed by option 1. The divergence shows in `shipwright status` and is announced in `#deploys` every morning until it is resolved.

If you really must deploy from main while diverged (an unrelated security fix, say), a platform engineer can clear the mark with `shipwright clear-divergence <service> --reason "..."`. That is logged and reviewed.

## Option 3: roll forward when the release ran a migration

If the bad release applied a database migration, the old code may not understand the schema it now finds. Typical failures: the old release writes rows without a value for a column that is now `NOT NULL`, reads a column that has been renamed, or fails its start-up check because the migration history is ahead of anything it knows about. Shipwright refuses the redeploy outright:

```text
error: release 12.5.2 predates migration 0142_add_refund_reason (applied with 12.6.0)
hint: roll forward with a fix; see "Down migrations" on the database migrations page
```

So you roll forward:

1. Switch off the new behaviour with its flag, if it has one.
2. Write the smallest fix on top of the bad release and ship it through the [hotfix process](hotfix-process.md).
3. If the migration itself is wrong, write a new migration that corrects it. Never edit or delete a migration that has already run.

Down migrations exist, but they are a last resort with their own approval; the reasons are on [Database migrations](database-migrations.md). An expand-only migration (a new nullable column, a new table) is usually harmless to the previous release, which is exactly why the expand then contract pattern exists. Even so, proving that the old code copes takes longer than a careful forward fix, so rolling forward is the rule.

## Telling people

During an incident, communication runs through the IC. Say in the incident channel what you are about to do before you do it, and again when it is done. Status page updates are not your job; see [Status page communications](../incidents/status-page.md).

Outside an incident, post in your team channel and in `#deploys`: what you are reverting, why, and which option you chose. One line is enough:

```text
Reverting merchant-api 12.4.0 (partial refunds in EUR return 500). Revert commit, no migration involved. Expect 12.4.1 at 100% around 14:30.
```

## After the revert

- Raise or update the ENG ticket for the real fix, and link the revert pull request to it.
- If there was an incident, the revert belongs in the timeline of its PIR ([template](../incidents/post-incident-review.md)).
- Re-land the change later by reverting the revert and adding the fix in the same pull request, so that the history shows what changed the second time.
- Check every flag you touched. A flag switched off in a hurry and then forgotten is a common reason for "the feature never came back".

## Three examples from this year

**merchant-api 12.4.0, July 2026.** Partial refunds in EUR returned 500 errors for merchants still sending an older API version. No migration was involved, about forty merchants were affected, and a workaround existed (a full refund followed by a new charge), so it was a SEV3. The engineer landed a revert commit, and 12.4.1 reached 100% of traffic 95 minutes after the merge. The fix shipped the following week in 12.5.0.

**notify 3.9.0, June 2026.** Webhook signatures were computed over the wrong body for one event type, and merchants' endpoints began rejecting them. The IC declared a SEV2. The on-call engineer redeployed 3.8.4 with `--incident`, and it was back at 100% eleven minutes after the decision. The revert commit merged the same afternoon and cleared the divergence.

**merchant-api 12.6.0, September 2026.** The release added a `refund_reason` column and the code that filled it. The code had a bug; the migration did not. Redeploying 12.5.2 was refused because of the migration, so the team switched off `sb.merchant-api.refund-reasons`, shipped 12.6.1 with the fix through the hotfix process, and switched the flag back on the next morning.

## Mistakes we have made so you do not have to

- **Reverting a commit that added a migration file.** The revert deletes the file, but the schema change stays in the database. Shipwright then finds a migration in the database's history that no longer exists in the repository, and stops. Write a new migration instead.
- **Undoing one half of a pair.** If service A's release only works with service B's, undoing B alone breaks A. The last row of the decision table exists for this reason.
- **Reverting the release instead of the commit.** Reverting six commits to undo one throws away five pieces of good work, and three people's afternoon.
- **Redeploying and walking away.** The divergence mark exists because people did exactly that. Land the revert commit.
- **A stale build cache.** Rarely, a revert build picks up a cached layer from the bad release. If the revert behaves exactly like the release it reverts, see [Build cache troubleshooting](build-cache.md).
