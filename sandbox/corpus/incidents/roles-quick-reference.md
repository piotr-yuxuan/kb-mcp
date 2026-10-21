---
title: "Incident roles quick reference"
---

# Incident roles quick reference

One card per role, to keep open during an incident. The policy behind it is
[production incident management](incident-management.md). Maintained by Site
Reliability; last reviewed 2026-08-24.

## IC

**Who:** from the `ic-primary` rota for SEV1 and SEV2; the on-call who declared, for
SEV3 and SEV4.

**Does:**
- confirms the severity, and changes it when the facts change;
- names the operations lead, communications lead and scribe in the channel;
- chooses the mitigation, on the operations lead's advice, and assigns it to a person;
- approves every Beacon update with the communications lead;
- tells the CTO within 30 minutes of a SEV1;
- resolves the incident and names the PIR author.

**Does not:** debug, type commands, or run two incidents at once.

**Says things like:** "Status check: what do we know, what are we trying, who is on
it?" and "Let us decide in the next two minutes, not the next twenty."

## Operations lead

**Who:** usually the owning team's on-call; for payments, the payments on-call.

**Does:**
- runs the hands-on work and the runbooks;
- brings in subject experts and says what each is looking at;
- tells the IC what each mitigation will do and how to undo it;
- reports results, including "that did not work".

**Does not:** post on Beacon, or argue about severity while mitigating.

## Communications lead

**Who:** the `comms-lead` rota, staffed by Merchant Support.

**Does:**
- drafts Beacon updates from the templates and posts them once approved;
- keeps the next update time visible in the channel;
- briefs support agents so that Harbour replies match Beacon;
- arranges the French version when needed.

**Does not:** publish without the IC's approval, or speculate on causes in public.
The rules and templates are on [status page communications](status-page.md).

## Scribe

**Who:** anyone in the channel the IC asks; often the on-call's secondary.

**Does:**
- keeps the timeline in the Klaxon record, in UTC;
- copies every line marked `DECISION:` into the record;
- posts the 30-minute internal update when the IC is busy.

**Does not:** filter. If in doubt, record it; the PIR author can trim later.

## Subject experts

**Who:** whoever the operations lead asks for: the Ledger team for anything that
touches journals, Platform for Kubernetes or Kafka, the SIRT for anything that might be
a security matter.

**Does:** answers the question asked, says when they are done, and leaves the channel
or stays quiet.

## Everyone else in the channel

- Keep the main channel for the incident; use threads for side questions.
- Do not flip switches, deploy or roll anything back unless the IC asked you to.
- If you know something relevant, say it once, clearly, and tag the operations lead.
- Leave when you are not needed. A quiet channel is a working channel.

## The first five minutes as IC

```text
1. "I am IC." (say it in the channel)
2. Severity confirmed? Change it now if not.
3. Who is operations lead? Who is comms (SEV1, SEV2)? Who is scribe?
4. Impact in one sentence: who, what, since when.
5. What changed recently? Deploys, flags, CHG- tickets, migrations.
6. First mitigation chosen and assigned to a named person.
7. Next internal update time posted.
```

## Handing over a role

Every handover is said aloud in the channel: "Handing operations lead to Jonah",
"Jonah, operations lead". Whoever takes over reads the last 30 minutes of the channel
first. For how rotas themselves hand over each Monday, see the
[on-call policy](on-call.md).
