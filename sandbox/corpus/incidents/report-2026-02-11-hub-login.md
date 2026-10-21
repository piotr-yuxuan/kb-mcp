---
title: "Incident report 2026-02-11: Merchant Hub login outage"
---

# Incident report 2026-02-11: Merchant Hub login outage

| Severity | Duration of impact | IC | Author | Review |
|---|---|---|---|---|
| SEV2 | 57 minutes (10:41 to 11:38 UTC) | Teodor Halloran | Malik Fairbairn | 2026-02-16, final |

Channel: `#inc-hub-login`. No error code was involved, which is part of the story.

## Summary

For 57 minutes on Wednesday 11 February 2026, nobody could sign in to Merchant Hub.
Merchants who entered their credentials were sent straight back to the sign-in page.
Merchants who were already signed in were unaffected, and payments, payouts and the
Merchant API worked throughout. The cause was a `merchant-hub` release that upgraded
the session library: the new version named the session cookie in a way browsers
reject when the cookie also carries a domain, and our production configuration sets
one. We redeployed the previous release with Shipwright and sign-ins recovered at
11:38 UTC.

## Impact

- **About 6,800 failed sign-in attempts** by **2,450 merchant users** between 10:41 and
  11:38 UTC.
- Users already signed in kept working; Merchant Hub sessions last 12 hours, so most
  of the morning's users never noticed.
- **37 Harbour tickets**, most of them in the first half hour.
- No effect on payments, payouts, the Merchant API or webhooks.

One product down for everyone trying to reach it: a SEV2.

## Timeline (UTC)

| Time | What happened |
|---|---|
| 10:05 | Release `2026.02.11-1` of `merchant-hub` enters canary on 5% of traffic. It includes a major upgrade of the session library |
| 10:35 | Canary analysis passes: error rate and p99 unchanged |
| 10:41 | Full rollout complete. From here, no new sign-in succeeds |
| 10:58 | First Harbour ticket: "I log in and it takes me back to the login page" |
| 11:09 | Merchant Support escalates to the Merchant Experience on-call after the eighth similar ticket |
| 11:12 | Malik Fairbairn sees sign-in completions at almost zero in Lantern, against about 400 a minute normally |
| 11:16 | SEV2 declared; Teodor Halloran takes IC |
| 11:31 | Beacon: Merchant Hub "Partial outage", with "If you are already signed in, please do not sign out" |
| 11:33 | DECISION: redeploy the previous release with Shipwright now, instead of a revert commit through the pipeline |
| 11:38 | Release `2026.02.10-2` live again; sign-ins recover within a minute |
| 11:52 | Beacon: Monitoring |
| 12:15 | Resolved in Klaxon and on Beacon |
| 14:20 | The revert commit merged and released through the normal pipeline, so that `main` matches production |

## Root cause

The new major version of the session library prefixes the session cookie's name with
`__Host-` by default. Browsers accept a cookie with that prefix only if it has no
`Domain` attribute. Our production configuration sets `Domain` so that the cookie works
across Merchant Hub's subdomains. Browsers therefore silently refused the new cookie;
after a successful sign-in the next request arrived without a session, and
`merchant-hub` redirected it to the sign-in page. Existing sessions used the old cookie
name and kept working.

**Why staging did not catch it.** `staging-eu` sets no `Domain` attribute, so the new
cookie was accepted there and every test passed. See
[staging environments](../release/staging-environments.md).

**Why the canary did not catch it.** The canary compares error rate and p99 latency
(see [canary analysis thresholds](../release/canary-analysis.md)). A sign-in loop
produces redirects and successful page loads, not errors, and is fast. By both
measures the release was healthy.

## Detection

Merchants told us, 17 minutes after full rollout and 53 minutes after the first canary
users were affected. Nothing alerted on sign-in completions.

## Response

The decision at 11:33 followed [reverting a bad release](../release/reverting-a-release.md):
a revert commit through the pipeline is the normal route, but its canary alone takes
30 minutes, and merchants were locked out. Redeploying the previous release took five
minutes. The release had run no database migration, so going back was safe.

## What went well

- "Please do not sign out" on Beacon and in the Harbour macro kept most signed-in
  merchants out of the problem.
- Once declared, the incident was mitigated in 22 minutes.
- Support spotted the pattern from eight tickets and escalated without waiting for a
  ninth.

## What was difficult

- The 18 minutes between the first ticket and the declaration. Each ticket on its own
  looked like a single merchant's browser problem.

## Actions

| Action | Type | Owner | Status |
|---|---|---|---|
| Synthetic sign-in from outside our network every minute, paging `merchant-exp-primary` after three failures | Detect | Malik Fairbairn | Done |
| Sign-in completion rate added to `merchant-hub`'s canary analysis | Detect | Malik Fairbairn | In Progress |
| `staging-eu` cookie configuration aligned with production | Prevent | Teodor Halloran | Done |
| Library upgrades that change cookie or session handling ship behind a Switchboard flag | Prevent | Malik Fairbairn | Done |
| Harbour macro for sign-in loops, pointing to Beacon | Process | Femi Haldane | Done |

Each is an ENG ticket labelled `pir-action`, without an epic.
