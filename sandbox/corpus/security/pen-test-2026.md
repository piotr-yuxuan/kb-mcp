---
title: "Penetration test 2026 summary"
---

# Penetration test 2026 summary

Written by Callum Ibe for engineering leads and the leadership team. Last updated
2026-08-17, when the last finding was closed.

The full report is Confidential and available from Security on request. This page
summarises what was tested, what was found and where each finding stands.

## At a glance

- **Test window:** 9 to 27 March 2026, by an external testing firm under contract.
- **Retest:** 15 to 17 June 2026.
- **Findings:** no critical, 1 high, 4 medium, 5 low, 3 informational.
- **Card data environment segmentation:** passed. The testers found no route from the
  corporate network, the offices' guest Wi-Fi or `staging-eu` into the card data
  environment.
- **Status on 2026-08-17:** every high and medium finding closed.

## Scope

| In scope | Approach |
|---|---|
| `merchant-api`, every public endpoint | Grey box, with API keys for two sandbox merchants |
| Merchant Hub | Grey box, with accounts at each role, from viewer to owner |
| The card data environment boundary | Segmentation test from each network zone, as PCI DSS requires |
| Identity provider configuration | Review of policies, factors and sessions |
| Office networks in London and Paris | On site, one day each |

Out of scope: denial-of-service testing, and phishing or phone pretexting, which our
own simulations cover (see the [phishing playbook](phishing.md)).

## Findings

Deadlines follow the [vulnerability management SLAs](vulnerability-slas.md), counted
from the day Security triaged each finding.

| Ref | Severity | Finding | Owner | Status |
|---|---|---|---|---|
| PT26-01 | High | A Merchant Hub user with the viewer role could download payout reports for every account in the merchant's group, not only their own | Merchant Experience | Fixed on 2026-03-18, six days after the testers reported it |
| PT26-02 | Medium | `merchant-api` returned internal host names in the error body when the `Quillmoor-Version` header was malformed | Merchant Experience | Fixed on 2026-04-21 |
| PT26-03 | Medium | Merchant Hub sessions stayed valid for 12 hours of inactivity | Merchant Experience | Fixed on 2026-05-06; idle sessions now end after 30 minutes |
| PT26-04 | Medium | Three production administrators could still sign in with push approvals instead of hardware security keys | Security | Closed on 2026-08-14, when enrolment under ENG-16 finished; covered by a risk acceptance from 2026-06-26 |
| PT26-05 | Medium | No rate limit on the endpoint that creates new API keys | Merchant Experience | Fixed on 2026-04-28 |
| PT26-06 to PT26-10 | Low | Missing security headers on two static pages, verbose server banners, an outdated TLS cipher offered on one internal endpoint, two cosmetic issues | Various | Four fixed; one accepted, as the page is being retired |
| PT26-11 to PT26-13 | Informational | Observations on logging coverage and on password-reset wording | Security | Noted |

### What we learned

**PT26-01 was the important one.** The export endpoint checked that the user was signed
in to the merchant group, but not which account in the group they could see. Two other
endpoints were found with the same pattern during the fix. Object-level authorisation
is now the first item under "Authorisation" in the
[secure code review checklist](secure-code-review.md), with a required test.

**PT26-04 needed an exception.** The 90-day deadline for a medium fell before ENG-16
could enrol the last administrators, who were waiting for keys to be delivered to
remote staff. A risk acceptance signed by the head of security, and countersigned by
the chief technology officer because Security owned the finding, covered the gap; in
the meantime the three accounts were limited to sign-ins from managed laptops. The
[password and MFA standard](password-and-mfa.md) now requires keys before any
privileged entitlement is granted.

**The segmentation result held.** It is the third year running that the card data
environment boundary has passed without findings.

## Next steps

- The next test will add the `payout-gateway` operator tools and Harbour's
  administrator functions to the scope.
- Teams with fixes recorded here should keep the regression tests that prove them; the
  retest checked that each one exists.
- Questions about a specific finding go to `#team-security`. Do not paste details from
  the full report into public channels.
