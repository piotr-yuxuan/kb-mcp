---
title: "Incident report 2026-08-08: stale FX quotes"
---

# Incident report 2026-08-08: stale FX quotes

> [!NOTE]
> SEV2. `FXQ-2002 STALE_RATE`. `#inc-stale-fx`. IC: Teodor Halloran. Operations lead
> and author: Corinne Aske. Reviewed 2026-08-13; approved by Nadia Ferreira. One
> action in progress, one open.

## Summary

On Saturday 8 August 2026, `fx-quote` issued currency quotes from a frozen set of
rates for 2 hours 12 minutes. The connection to the rate feed was dropped at the
provider's end without being closed, and our consumer waited on it indefinitely.
`fx-quote` flagged every affected quote with `FXQ-2002`, but at the time the flag was
only logged, not acted on, and the alert for it did not page. The ledger's hourly FX
check paged us at 11:02 UTC. A restart of `fx-quote` reconnected the feed at 11:24.
Every quote was honoured; Quillmoor absorbed the difference.

## Impact

| | |
|---|---|
| Window | 09:13 to 11:25 UTC |
| Quotes on stale rates | 14,260: 11,900 for card payments, 2,360 for EUR payouts |
| Largest deviation from the market rate | 0.71% |
| Net cost to Quillmoor | £3,870, booked by Finance on 10 August |
| Merchant effect | None visible. Buyers paid, and sellers received, the quoted amounts |

**Why SEV2 when every request succeeded?** For two hours every conversion between GBP
and EUR was priced wrongly, with money at stake on each one. Incident management treats
that as a major degradation: see rule 5 in
[production incident management](incident-management.md). No Beacon update was posted,
because merchants felt no effect; Support was briefed in case anyone asked.

## Timeline (UTC)

| Time | Event |
|---|---|
| 09:12:04 | Last rate received from the feed. The provider's load balancer drops the connection silently during their maintenance |
| 09:13 | `FXQ-2002` raised on every new cross-currency quote. The alert posts to `#team-payments-core` as a low-urgency notification; nobody is reading on a Saturday |
| 10:00 | Ledger's hourly FX check runs; the deviation is under its 0.25% threshold |
| 11:00 | The check runs again; deviation 0.58% |
| 11:02 | The check pages `payments-primary` as SEV2 |
| 11:06 | Corinne Aske acknowledges |
| 11:11 | Lantern shows `FXQ-2002` on every quote since 09:13, and the feed's last message at 09:12 |
| 11:15 | SEV2 declared; Teodor Halloran takes IC from the IC rota |
| 11:21 | `fx-quote` restarted with a Shipwright redeploy of the running release |
| 11:24 | Feed reconnected; fresh rates |
| 11:25 | `FXQ-2002` stops. Impact ends |
| 11:40 | DECISION, with Nadia Ferreira on the phone: turn on `sb.fx-quote.refuse-stale-rates` |
| 11:55 | DECISION: no Beacon update; Support briefed |
| 12:30 | Arjun Pelletier given the exposure estimate |
| 12:45 | Resolved |

## Root cause

Three things had to be true at once.

1. **The feed consumer had no read deadline.** When the provider's load balancer
   dropped the connection without closing it, the consumer kept waiting for the next
   message. The quote path kept serving the last rates it had.
2. **The staleness guard only flagged.** The rewrite under ENG-5 made `fx-quote` raise
   `FXQ-2002` whenever a quote uses a rate older than 60 seconds. Whether such a quote
   is refused or merely flagged is set by `sb.fx-quote.refuse-stale-rates`, which was
   off: during the rewrite's first months we preferred a slightly stale quote to a
   declined payment. Note that a quote's own validity, 30 seconds, is a different
   clock: every stale quote here was still a valid quote.
3. **The `FXQ-2002` alert did not page.** It was set to low urgency during the bedding-in
   period and never raised afterwards.

ENG-5 had fixed `FXQ-2002` errors when the feed lags, that is, when rates arrive late.
It had not covered a feed that stops.

## What went well

- The ledger's FX check, built for a different purpose, caught the problem.
- One restart fixed it, and the IC got the right decision-maker on the phone for the
  policy question within 25 minutes on a Saturday.
- Finance had the exposure figure the same day.

## Where we got lucky

Saturday volumes are about a third of a weekday's, and rates moved little that
morning. On a weekday with a moving market, the same two hours could have cost many
times as much.

## Actions

| Action | Type | Owner | Status |
|---|---|---|---|
| Read deadline and heartbeat on the feed connection; reconnect after 10 seconds of silence | Prevent | Corinne Aske | Done |
| Page `payments-primary` when `FXQ-2002` exceeds 1% of quotes for 2 minutes | Detect | Corinne Aske | Done |
| Decide the permanent setting of `sb.fx-quote.refuse-stale-rates` and record it on the [fx-quote service page](../payments/fx-quote-service.md) | Process | Nadia Ferreira | In Progress |
| A second rate feed, with failover between the two | Mitigate | Corinne Aske | To Do |
| Weekend review of low-urgency notifications in payments channels | Process | Lukas Brennand | Won't Do: superseded by the paging action above |

Each is an ENG ticket labelled `pir-action`; ENG-5 had closed in May, so none has an
epic.
