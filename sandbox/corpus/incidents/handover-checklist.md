---
title: "On-call handover checklist"
---

# On-call handover checklist

Rotas hand over on Mondays at 10:00 UK time; the rules are in the
[on-call policy](on-call.md). This checklist is what the outgoing and incoming person
go through together. Copy it into the hand-over thread in your team channel and tick
it off there, so that the next person can see what was said.

*Owner: Site Reliability. Last reviewed 2026-09-14, when the Switchboard step was
added.*

## Before the call (outgoing)

- [ ] Write a short summary of the week in the team channel: pages, incidents, anything
      odd. Three to ten lines is plenty.
- [ ] Check that your own Klaxon overrides for the coming week are gone.
- [ ] Note any page you acknowledged but did not finish.

## On the call (both)

**Open work**

- [ ] Open incidents: channel, severity, who is IC, what is left to do.
- [ ] Incidents waiting for a PIR: who is the author, when the review meets.
- [ ] `pir-action` tickets owned by the team and due this week (the
      [PIR actions tracker](pir-actions-tracker.md) lists them).
- [ ] Anything handed to another team that may come back.

**State of production**

- [ ] Alerts silenced in Lantern, and when each silence ends. Silences that outlive
      their reason have caused incidents before.
- [ ] Kill switches currently flipped and flags changed by hand in Switchboard during
      the week, with the reason recorded on each.
- [ ] Releases blocked or held back, and why.
- [ ] Error budgets close to exhaustion on the [SLO catalogue](slo-catalogue.md)
      dashboard.

**The coming week**

- [ ] `CHG-` tickets scheduled in the Change Register for the week, and who is running
      each one.
- [ ] Planned maintenance by other teams that may page you: broker restarts, database
      upgrades, node pool upgrades.
- [ ] Change freezes starting or ending in the week; see the
      [2026 change freeze calendar](../release/change-freeze-2026.md).
- [ ] Bank holidays in the week, and cut-offs that move because of them.
- [ ] Known merchant events: a large marketplace launching, a sales weekend.

**The incoming person**

- [ ] Klaxon shows you as on call from 10:00, primary or secondary as expected.
- [ ] A test page sent and received on your phone, through silent mode. If it does not
      break through, fix it now with [setting up Klaxon on your phone](klaxon-setup.md).
- [ ] Laptop charged, remote access working, and access to Shipwright, Switchboard and
      Lantern checked. Payments rotas run one read-only command to prove it:

```bash
shipwright exec payout-gateway -- pgw-admin status
```

- [ ] Swaps agreed for the week, in Klaxon, at least 24 hours ahead.

## After the call (outgoing)

- [ ] Post "Handed over to [name]" in the team channel.
- [ ] Record any time off in lieu from the week in Haven.
- [ ] Hand any incident you are still IC or operations lead on explicitly, in its own
      channel.

## When there is an incident at 10:00

Do not hand over in the middle of a SEV1 or SEV2. The outgoing person stays with the
incident; the incoming person takes new pages from 10:00 and joins the incident as a
second pair of hands. Hand over the incident role later, explicitly, when there is a
quiet moment.
