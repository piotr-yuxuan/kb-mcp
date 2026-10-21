---
title: "Production incident management"
---

# Production incident management

| | |
|---|---|
| Owner | Site Reliability, `#team-sre` (Lukas Brennand, site reliability lead) |
| Approved by | Bram Oyelaran, head of platform engineering |
| Applies to | Every engineering team, and anyone from Merchant Support, Finance or Product who joins an incident channel |
| Last reviewed | 2026-09-29, by Lukas Brennand |
| Review cycle | Every six months, and after any SEV1 |

This page is Quillmoor's policy for production incidents: how we grade them, who is in
charge, and how we declare, run and close them. The person in charge is the incident
commander (IC), whose role is described below. The runbooks for individual services
tell you what to do with your hands; this page tells you how the people around you
are organised while you do it.

> [!IMPORTANT]
> If merchants cannot take payments, sellers are not being paid, or you think data may
> have been lost, declare an incident now with `/klaxon declare` and sort out the
> details afterwards. Nobody at Quillmoor has been criticised for declaring too early.

## What counts as a production incident

A production incident is any unplanned event that degrades, or is about to degrade,
Quillmoor Pay, Quillmoor Payouts, Merchant Hub or the Merchant API, or that loses data
we are responsible for. A bad deploy that the canary caught is not an incident; a bad
deploy that reached merchants is. A slow issuer, a throttling settlement bank or a
failing card scheme is our incident too, as soon as our merchants feel it.

Two neighbouring processes have their own scales and their own pages:

- **Security incidents**, such as a suspected compromise, a leaked credential or
  possible exposure of cardholder or personal data, belong to the SIRT. Their scale
  and procedure are in the
  [security incident response plan](../security/incident-response-plan.md).
- **Merchant support tickets** carry a priority set in Harbour, described in
  [ticket priorities](../support/priorities-and-slas.md).

We keep the three scales apart and never translate one into another. A P1 ticket can
turn out to be a SEV3, and a SEV1 can start from an ordinary ticket. When one event is
both a production incident and a security incident, it gets a SEV from this page and
a separate rating from the SIRT, and the two leads work side by side in the same
channel.

## Severity levels

The severity describes the impact on merchants now, or the impact we expect within the
hour if nothing is done. It does not describe the cause, the number of alerts or how
worried you feel.

| Level | Definition | Examples from our own history | What it sets in motion |
|---|---|---|---|
| SEV1 | Payments or payouts down for many merchants, or data lost | Authorisations failing across every issuer on 2025-09-17 | IC from the IC rota, communications lead, Beacon updates, the CTO told, PIR |
| SEV2 | A major degradation, or one product down | Payouts delayed for hours on 2025-06-03; nobody able to sign in to Merchant Hub on 2026-02-11; quotes priced on stale rates on 2026-08-08 | IC from the IC rota, communications lead, Beacon when merchants can see it, PIR |
| SEV3 | A minor degradation with a workaround | Fee invoices held back by a ledger break on 2025-12-02; a late finance mart on 2026-05-20 | The on-call engineer acts as IC; a PIR if the IC asks for one |
| SEV4 | No merchant impact | Staging down for a morning; an internal job failing and retrying successfully | A ticket for the owning team; a channel only if it helps |

### Choosing the level

1. **Grade by merchant impact.** Ask what merchants and their buyers or sellers are
   experiencing, not what is broken inside.
2. **"Many merchants" means more than about 50**, or any strategic merchant (see
   [strategic merchants](../support/strategic-merchants.md)). A total outage for a
   handful of merchants is usually a SEV2.
3. **"Data lost" means data we cannot rebuild**: ledger journals, payment or payout
   records, merchant settings. A warehouse table that can be rebuilt from the event
   log is not lost, although the time a rebuild takes may still justify a SEV2.
4. **Choose the higher level when in doubt**, and downgrade once you know more. An
   over-graded incident costs a few people an hour; an under-graded one costs
   merchants an afternoon.
5. **Money at risk raises the level.** A double payment, a mispriced conversion or a
   journal that does not balance is at least a SEV2 if it is still happening, even
   when every request returns success.

### Situations people ask about

| Situation | Level | Why |
|---|---|---|
| Payouts still flowing, but hours late | SEV2 | A major degradation, not a product down |
| One merchant cannot take payments because of its own integration | Not an incident | A support ticket, unless our platform turns out to be the cause |
| A late finance mart in the warehouse | SEV3 | Data Platform's standing rule; see [data quality alerts](../data/quality-alerts.md) |
| Lantern or Klaxon down, services healthy | SEV4, staffed like a SEV3 | No merchant impact yet, but we would not see the next incident |
| A planned region failover, as in a game day | SEV4, declared | Failover is always a declared incident, even when rehearsed |
| A suspected data exposure with no production effect | No SEV | Hand it to the SIRT through security@quillmoor.example |

### Changing the level

The IC can raise or lower the level at any time in the Klaxon incident record. Klaxon
then pages or stands down people according to the new level and posts the change in
the channel. Say why in one line ("SEV2 to SEV1: declines now across all issuers, not
one"); the reason ends up in the PIR timeline.

## Declaring an incident

Anyone can declare, including people outside engineering. In any chat channel:

```text
/klaxon declare
```

Klaxon asks four questions: the severity, a short name, the affected services, and a
one-line summary of what merchants see. People who declare often type it in one go:

```text
/klaxon declare sev2 hub-login "Merchants cannot sign in to Merchant Hub; existing sessions work"
```

Klaxon then:

1. creates the channel `#inc-hub-login` and invites you and the owning team's on-call;
2. opens an incident record with a timeline that starts at the moment you declared;
3. for a SEV1 or SEV2, pages the IC rota and the communications lead rota;
4. for a SEV1, drafts the first Beacon update from the template, ready for approval
   (see [status page communications](status-page.md));
5. posts a one-line notice in `#team-sre` and in the owning team's channel.

**Short names describe the symptom**, not the suspected cause: `#inc-payouts-delayed`,
not `#inc-bank-throttling`. Causes change during an incident; symptoms rarely do.

**If Klaxon itself is down**, create the channel by hand, email
payments-oncall@quillmoor.example for anything touching payments or payouts, and call
the people on [escalation contacts](escalation-contacts.md). Note the time you started;
the scribe enters everything into Klaxon once it is back.

## The incident commander

Every SEV1 and SEV2 has an **incident commander**, the IC: the single person in charge
of the response. The IC decides what happens next, keeps the people involved working on
the right things and makes sure everyone else knows what is going on. The IC does
**not** debug. The moment an IC opens a terminal, nobody is in charge.

The IC is responsible for:

- confirming the severity and changing it when the picture changes;
- naming the other roles, and filling them from the channel if the rotas are slow;
- choosing between mitigations, with the owning team's advice, and saying so plainly
  ("We are pausing the scheduler. Yusuf, go.");
- approving every Beacon update together with the communications lead;
- telling executives at the points listed under "Who else to tell" below;
- declaring the incident mitigated, then resolved;
- naming the author of the PIR before the channel goes quiet.

ICs for SEV1 and SEV2 come from the IC rota in Klaxon, which hands over with every
other rota on Mondays (see [on-call rota and paging policy](on-call.md)). To join the
rota you attend the half-day IC workshop, shadow two incidents and then lead one with
an experienced IC shadowing you. There are 16 trained ICs at present, drawn from Site
Reliability, Payments Core, Payouts, Ledger, Platform and Merchant Experience.

For SEV3 and SEV4, the on-call engineer who declared is the IC by default. They may
ask the IC rota for help at any time, and should once an incident runs beyond two
hours.

### Handing over the IC role

Handovers are explicit. The outgoing IC writes in the channel "Handing IC to Ffion
Arkwright", Ffion replies "I am IC", and Ffion updates the Klaxon record. Nobody stays
IC on a SEV1 for more than four hours; the IC rota's secondary takes over, or the IC
asks in `#team-sre`.

### The other roles

| Role | In one line |
|---|---|
| Operations lead | Runs the hands-on work; usually the owning team's on-call |
| Communications lead | Drafts Beacon updates and keeps Merchant Support informed |
| Scribe | Keeps the timeline in UTC and records decisions |
| Subject experts | Brought in by the operations lead for specific questions |

[Incident roles quick reference](roles-quick-reference.md) has a card for each role,
including what each one should not do.

## Running the incident

### The first 15 minutes

1. Declare, or join the channel if someone else has.
2. Confirm the IC and the operations lead in the channel.
3. State the impact in one sentence: who is affected, how, since when.
4. Check what changed: Shipwright deploys, Switchboard flips, `CHG-` tickets in the
   Change Register, and any database migration in the last 24 hours.
5. Pick the first mitigation and assign it to a named person.
6. For a SEV1, make sure the first Beacon update is on its way.

### Mitigate before you diagnose

Stop the damage first; understand it later. Prefer levers that are quick to pull and
quick to undo:

- flip a kill switch or a flag (see [feature flags and kill switches](../release/feature-flags.md));
- redeploy the previous release (see [reverting a bad release](../release/reverting-a-release.md));
- scale out a service that is short of capacity;
- shed optional work, such as a lower 3DS step-up sampling rate on `card-auth`.

Some services have their own sequence, and it must be followed exactly. For
`payout-gateway`, pause, drain and only then roll back, as set out in
[the payout-gateway rollback runbook](../payments/payout-gateway-rollback.md); a
shortcut can pay sellers twice. Never roll anything back across a ledger schema
migration without the Ledger team.

### Keeping the channel useful

For SEV1 and SEV2 the IC, or the scribe on the IC's behalf, posts an internal update
in the channel every 30 minutes, and whenever something important changes:

```text
Status: mitigating
Impact: about 9% of authorisations declining, all merchants, since 17:44 UTC
Since last update: card-auth scaled to 40 pods; latency back under budget for other issuers
Next: confirm the issuer's status with the acquiring bank; next update 18:45 UTC
IC: Lukas Brennand / Ops: Corinne Aske / Comms: Femi Haldane
```

Keep side conversations in threads. Prefix decisions with `DECISION:` so the scribe
can find them. Times are always UTC in the channel, even when the merchant-facing
cut-offs are in UK or CET time.

### Who else to tell

| When | Who | How |
|---|---|---|
| SEV1, within 30 minutes | Ottilie Marsh, CTO, who tells the chief executive | Klaxon pages the executive rota; the IC follows up in the channel |
| SEV2 | The head of the owning department | A mention in the channel, or a call out of hours |
| Money paid or priced wrongly | Finance | finance@quillmoor.example and Arjun Pelletier in the channel |
| Merchants likely to call | Merchant Support | The communications lead, through `#inc-` and Harbour |
| Possible exposure of data | The SIRT | security@quillmoor.example, and a page to `security-oncall` |
| A contractual commitment at risk | Legal | legal@quillmoor.example |

Beacon, our public status page, has its own rules, owned jointly by the IC and the
communications lead: see [status page communications](status-page.md).

## Resolving and following up

An incident is **mitigated** when merchants stop feeling it, and **resolved** when it
needs no further action to stay that way. Watch a SEV1 for at least 30 minutes after
mitigation before resolving it. Resolve in the Klaxon record; the channel stays open
for the review and is archived when the last action is filed.

Every SEV1 and SEV2 has a PIR within 5 business days, following the
[PIR template](post-incident-review.md). For a SEV3 the IC decides; most get a short
one, especially when they reveal a gap in alerting. SEV4s get a ticket and, at most,
a paragraph in the owning team's channel.

The write-up is published in this section as `report-YYYY-MM-DD-short-name`, and its
actions become ENG tickets labelled `pir-action`, followed on the
[PIR actions tracker](pir-actions-tracker.md).

## Recent incidents

| Date | Report | Level | Identifier |
|---|---|---|---|
| 2025-06-03 | [Payouts delayed](report-2025-06-03-payouts-delayed.md) | SEV2 | `PGW-5021` |
| 2025-09-17 | [Card authorisation latency](report-2025-09-17-card-auth-latency.md) | SEV1 | `CAU-1207` |
| 2025-12-02 | [Ledger reconciliation break](report-2025-12-02-ledger-break.md) | SEV3 | `LDG-4091` |
| 2026-02-11 | [Merchant Hub login outage](report-2026-02-11-hub-login.md) | SEV2 | none |
| 2026-05-20 | [merchant_orders_daily late](report-2026-05-20-orders-late.md) | SEV3 | `DQ-017` |
| 2026-08-08 | [Stale FX quotes](report-2026-08-08-stale-fx.md) | SEV2 | `FXQ-2002` |

## History of this policy

- **Before April 2024**, incidents were graded "critical", "high", "medium" and
  "low", and those words were also used for support tickets and vulnerabilities. The
  SEV scale replaced them so that nobody could mistake one for another.
- **2025, ENG Sprints 2 to 7:** the Klaxon paging migration (ENG-11) moved the IC rota,
  with every other rota, to weekly hand-overs on Mondays at 10:00.
- **2025-09:** after the SEV1 of 2025-09-17 the first Beacon update arrived late; the
  executive notification step above was added at the same time.
- **2026, ENG Sprints 30 to 36:** Beacon status page automation (ENG-13) made Klaxon
  draft the first SEV1 update from a template.
- An idea to merge the incident, security and support scales into one sits on the
  ideas board in `PRB` (see [product discovery](../product/discovery-process.md)).
  Until a decision is made, this page's scale stands, and the other two stay separate.

## Questions people ask

**I am not sure it is an incident. Should I declare?** Yes. Declaring costs a channel;
a SEV4 that turns out to be nothing is closed in a minute.

**Who sets the severity?** The person declaring proposes it; the IC confirms or
changes it. Anyone may suggest a change in the channel.

**A merchant's P1 ticket paged me. Is it automatically a SEV1?** No. Harbour pages the
payments on-call for P1 tickets (ENG-27), and the on-call decides whether there is an
incident and of what level, using the table above.

**Can I fix it quietly and skip the declaration?** For a SEV4 that you resolve in
minutes, yes, with a note in your team's channel. For anything a merchant could
notice, no: the record is what lets us see patterns.

**What if the IC rota does not answer?** Klaxon escalates on its own. If you are still
alone after the escalation, be the IC yourself until someone arrives, and say so in
the channel.
