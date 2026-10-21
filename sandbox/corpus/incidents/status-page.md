---
title: "Status page communications"
---

# Status page communications

- **Owners:** Femi Haldane (head of customer support) and Lukas Brennand (site reliability lead)
- **Last reviewed:** 2026-09-02, after ENG-13 shipped
- **Ask in:** `#team-sre`

Beacon is Quillmoor's public status page, at `status.quillmoor.example`. Merchants
check it when something looks wrong, their engineers subscribe to it by email and
webhook, and Merchant Support links to it from Harbour. When we are in an incident,
Beacon is the one place where we tell every merchant the same thing at the same time.
That makes each update a public statement by the company: it is written carefully,
approved by two people, and posted on a schedule.

This page covers when to post, who writes and who approves, how to write an update,
and the templates. How incidents are declared and graded is on
[production incident management](incident-management.md).

## The two rules everyone remembers

1. **SEV1: first update within 15 minutes, then every 30 minutes.** The clock starts
   when the incident is declared in Klaxon, not when the cause is known. "We are
   investigating" is a perfectly good first update.
2. **Nothing goes on Beacon without the IC and the communications lead.** Both approve
   every update, every time.

## What Beacon shows

| Component | What it covers | Services behind it (never shown publicly) |
|---|---|---|
| Card payments | Authorisations, captures and 3DS for Quillmoor Pay | `card-auth`, `risk-scorer`, `fx-quote` |
| Payouts | Payouts to sellers in GBP and EUR | `payout-gateway`, `settlement-batcher` |
| Merchant Hub | The dashboard, including sign-in | `merchant-hub` |
| Merchant API | The public API | `merchant-api` |
| Webhooks and emails | Event notifications to merchants | `notify` |

Each component has a state: **Operational**, **Degraded performance**, **Partial
outage**, **Major outage** or **Under maintenance**. Each incident on Beacon moves
through **Investigating**, **Identified**, **Monitoring** and **Resolved**.

Choose the component state from what merchants experience. If payouts are flowing but
late, Payouts is "Degraded performance", not "Major outage", even when the incident
channel is in uproar.

## When to post

| Severity | Post on Beacon? | First update | Then |
|---|---|---|---|
| SEV1 | Always | Within 15 minutes of declaration | Every 30 minutes until resolved |
| SEV2 | When merchants can see the effect | Within 30 minutes of declaration | Every 60 minutes until resolved |
| SEV3 | Only if merchants are contacting support about it | When the IC decides | When something changes |
| SEV4 | Never | | |

"When merchants can see the effect" is a judgement for the IC and the communications
lead together. Late payouts, failed sign-ins and declined payments are visible. A
problem that we absorb ourselves, such as quotes priced on stale rates that we honour
at our own cost, may not be; see the 2026-08-08 example below.

If an update falls due and nothing has changed, post anyway and say so. Silence on a
status page reads as "they have forgotten us".

**Security incidents.** Beacon is updated only when merchants feel an effect, and a
security cause is never named without the general counsel's approval. The
[security incident response plan](../security/incident-response-plan.md) covers the
rest; the communications lead follows the SIRT's lead on wording.

## Who writes and who approves

- **The communications lead** drafts every update and posts it once approved. For
  SEV1 and SEV2 incidents Klaxon pages the `comms-lead` rota, staffed by Merchant
  Support. The communications lead also keeps support agents briefed so that what
  they tell merchants in Harbour matches Beacon.
- **The IC** approves every update for accuracy: is this what we know, and are we
  promising only what we can keep?
- **The communications lead** approves it for tone and clarity. Both approvals are
  recorded in Klaxon with one click each.

If the communications lead has not joined within 10 minutes of a SEV1 page, the IC
names a stand-in from the channel: any support team lead, or the IC rota secondary.
The stand-in approves in the communications lead's place until the rota answers. The
IC never approves alone.

### The automated first update for a SEV1

Since ENG-13, the Beacon status page automation epic completed in ENG Sprint 36, a
SEV1 declared in Klaxon arrives with its first Beacon update already drafted from the
template below, with the component chosen from the services named in the declaration.
The communications lead checks the component and the wording, the IC approves, and
the update is posted from Klaxon. In the two rehearsals held since then, the draft was
ready for approval within 4 minutes of declaration.

The draft is a starting point. If the template does not fit, change it; do not post
something inaccurate to save two minutes.

## Writing an update

Write for a merchant's operations manager reading on a phone between other things.

- **Say what merchants see, not what broke inside.** "Some card payments are being
  declined" rather than "elevated issuer timeouts on the authorisation path".
- **Say what they can do,** if anything: retry later, use the API instead of the
  dashboard, expect payouts later today.
- **Say when the next update will be,** as a time in UTC.
- **Do not name anyone outside Quillmoor.** Not the issuer, not the card schemes, not
  the acquiring bank, not our settlement bank. "A third party" or "a banking partner"
  is enough, and even that only once the cause is confirmed.
- **Do not guess at causes.** "We have identified the cause" is fine; the cause itself
  goes in the summary after the PIR, if at all.
- **Do not promise a time to recovery** unless the IC is confident of it. Promise the
  next update instead.
- **No internal names**: no service names, no error codes, no tool names.
- Follow the [content style guide](../design/content-style.md): British English,
  sentence case, plain words.

Updates are in English. For SEV1 incidents, and for any incident affecting EUR
payouts, the support team in Paris adds a French version to the following update; see
[supporting French-speaking merchants](../support/french-speaking-merchants.md).

## Templates

Square brackets mark what you fill in. Delete any line that does not apply.

### SEV1, first update (Investigating)

This is the template Klaxon drafts from.

```text
Title: [Component] disruption

We are investigating a problem affecting [what merchants see, e.g. "card
payments for some merchants"]. It started at about [HH:MM] UTC.

Our engineers are working on it now. We will post our next update by
[HH:MM] UTC.
```

### Follow-up while investigating

```text
We are still investigating the problem affecting [what merchants see].
[One sentence on what has changed, e.g. "The share of declined payments
has fallen since 18:20 UTC, but has not returned to normal."]

Next update by [HH:MM] UTC.
```

### Identified

```text
We have identified the cause of the problem affecting [what merchants see]
and are [applying a fix / working with a banking partner to resolve it].
[What merchants can do, if anything.]

Next update by [HH:MM] UTC.
```

### Monitoring

```text
A fix is in place and [what merchants see] has been working normally since
[HH:MM] UTC. We are monitoring to make sure it stays that way.

[If payouts or payments need no action from merchants, say so.]
Next update by [HH:MM] UTC.
```

### Resolved

```text
This incident is resolved. Between [HH:MM] and [HH:MM] UTC, [what merchants
experienced]. [What happens to affected payments or payouts, e.g. "All
delayed payouts were sent the same day; no action is needed."]

We are sorry for the disruption. [For SEV1: "We will publish a summary of
what happened here within 10 business days."]
```

### Payouts delayed

```text
Title: Payouts delayed

Payouts to sellers are being sent later than usual. No payout has been
lost, and payouts will be sent as soon as the delay is resolved. [If a
cut-off is at risk: "Some payouts may arrive on the next business day."]

Next update by [HH:MM] UTC.
```

Support's answers to merchants for this case are on
[payout delays: what to tell merchants](../support/payout-delay-faq.md); keep the two
consistent.

### Merchant Hub sign-in

```text
Title: Merchant Hub sign-in problems

Some merchants cannot sign in to Merchant Hub. If you are already signed
in, the dashboard works normally; please do not sign out. Payments, payouts
and the Merchant API are not affected.

Next update by [HH:MM] UTC.
```

### Scheduled maintenance

```text
Title: Scheduled maintenance: [component]

On [date], between [HH:MM] and [HH:MM] UTC, we will carry out planned
maintenance on [component]. [Expected effect, e.g. "Merchant Hub may be
unavailable for up to 5 minutes. Payments are not affected."]
```

Planned work that merchants could notice is announced at least 5 business days ahead.
The [region failover game day of April 2026](game-day-2026-04.md) was announced this
way.

## After the incident

- **Resolve on Beacon** when the IC resolves in Klaxon, not before.
- **For SEV1**, publish a short public summary within 10 business days, once the PIR
  has met. The communications lead drafts it from the PIR's summary; the IC, Femi
  Haldane and Legal (legal@quillmoor.example) approve it. It says what merchants
  experienced, broadly why, and what we are changing, and nothing more.
- **Strategic merchants** hear from their account managers directly, before the public
  summary; see [strategic merchants](../support/strategic-merchants.md).

## Edge cases

**The incident is over before the first update is due.** For a SEV1, post anyway,
straight to Resolved, with what merchants experienced. Merchants who saw failures
will look for an explanation.

**Only a few merchants are affected.** If it is a SEV2 because a single product is
down for a handful of large merchants, those merchants hear from Support directly and
Beacon stays quiet, unless others start asking.

**The severity changes.** A SEV2 that becomes a SEV1 starts the 15-minute clock from
the change, and moves to 30-minute updates.

**Beacon itself is unavailable.** Beacon is hosted outside our production regions for
this reason, but if it cannot be reached, the communications lead asks Merchant
Experience to put a banner on Merchant Hub and briefs Support to answer by email. The
updates are posted on Beacon later, with their original times.

**Two incidents at once.** Two Beacon incidents, one per component, each with its own
communications lead if possible. Never merge them into one update because they
happened on the same afternoon.

## Examples from past incidents

| Incident | What we posted | What we learnt |
|---|---|---|
| [2025-06-03, payouts delayed](report-2025-06-03-payouts-delayed.md), SEV2 | Payouts "Degraded performance", 20 minutes after declaration, then hourly | The payouts template above came out of this incident |
| [2025-09-17, card authorisation latency](report-2025-09-17-card-auth-latency.md), SEV1 | Card payments "Partial outage"; first update 22 minutes after declaration | Too slow: the first update was written from scratch while the IC was busy. This led to ENG-13 |
| [2026-02-11, Merchant Hub login outage](report-2026-02-11-hub-login.md), SEV2 | Merchant Hub "Partial outage", 15 minutes after declaration | "Please do not sign out" was the most useful sentence we wrote all year |
| [2026-08-08, stale FX quotes](report-2026-08-08-stale-fx.md), SEV2 | Nothing | Payments succeeded and every quote was honoured, so merchants felt no effect. Support was briefed in case anyone asked |

## Checklist for the communications lead

- [ ] Joined the incident channel and said so
- [ ] Component and state chosen from merchant impact
- [ ] First update approved by the IC and posted within the time limit
- [ ] Next update time written down in the channel
- [ ] Support agents briefed in Harbour with the same wording
- [ ] French version arranged for SEV1 or EUR payout incidents
- [ ] Resolved on Beacon at the same time as in Klaxon
- [ ] Public summary scheduled, for SEV1
