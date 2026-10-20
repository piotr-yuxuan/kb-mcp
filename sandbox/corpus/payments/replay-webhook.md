---
title: "How to replay a merchant webhook"
---

`notify` belongs to Merchant Experience (`#team-merchant-hub`), but most replay requests are about payment and payout events and land on the payments on-call, so this how-to lives here. Written by Payments Core, checked by Merchant Experience. Last reviewed 2026-08-26.

## When a replay is the answer

A merchant's endpoint was down or returning errors, `notify` exhausted its retries (it retries with backoff for 24 hours, then marks the delivery `failed`), and the merchant now wants the events they missed. The request usually arrives as a Harbour ticket from Support, with a merchant identifier and either event identifiers or a time range.

A replay resends **the original event, unchanged**: same identifier, same payload, same timestamp, plus a `replayed: true` field. It does not tell the merchant the current state of a payment or payout. If a merchant wants the current state, point them to the Merchant API instead.

## Before you replay

1. **Is the endpoint healthy now?** Replaying into an endpoint that is still failing only adds failures.

   ```bash
   shipwright exec notify -- notify-admin endpoints show --merchant-id mer_7Qa21xPd
   ```

   Look at the last five deliveries. If they are not `2xx`, ask the merchant to fix their endpoint first.

2. **Which events?** If the ticket gives a payment or payout identifier rather than event identifiers, list the events for it:

   ```bash
   shipwright exec notify -- notify-admin events list --object-id po_5Kq81mZt
   ```

   ```text
   evt_2Wc8RkQ0  payout.batched  2026-08-24T10:15:03Z  delivered (200)
   evt_2Wc9Lm1T  payout.paid     2026-08-24T10:19:47Z  failed (503 x 14)
   ```

## Replay one event

```bash
shipwright exec notify -- notify-admin replay --event-id evt_2Wc9Lm1T
```

```text
replaying evt_2Wc9Lm1T (payout.paid) to endpoint we_41Hd0aZr
  attempt 1: 200 OK in 212 ms
done: 1 delivered, 0 failed
```

The replay is signed with the endpoint's **current** signing secret. If the merchant has rotated their secret since the original delivery, that is what they want; if they verify against an old one, the replay will look forged to them.

## Replay several events

For a handful of events, loop over a file with one identifier per line. Keep it gentle: one event a second is plenty, and a merchant's endpoint that has just recovered may not enjoy a burst.

```bash
while read -r event_id; do
  shipwright exec notify -- notify-admin replay --event-id "$event_id"
  sleep 1
done < events-to-replay.txt
```

For more than about 500 events, or a whole day's traffic, ask Merchant Experience in `#team-merchant-hub` instead. They have a bulk tool that respects each merchant's rate limits.

## Edge cases

- **Events older than 45 days** are no longer in `notify`'s event store and cannot be replayed. Merchant Experience can reconstruct some of them from the event log; ask them.
- **Duplicates.** A merchant who received the original and the replay sees the same event identifier twice. Merchants are told to deduplicate by event identifier; if one does not, that is a conversation for Support, not a reason to refuse the replay.
- **Endpoint deleted.** If the merchant deleted the endpoint and created a new one, replay with `--endpoint-id` set to the new one; otherwise `notify` replays to the endpoint of the original delivery, and fails.
- **The event is wrong, not missing.** If the original event carried a wrong amount or status, replaying it repeats the mistake. Raise it with the owning team (`#team-payouts` for payouts, `#team-payments-core` for payments) instead.

## Afterwards

Note the replayed identifiers in the Harbour ticket so that Support can tell the merchant exactly what was resent. If the merchant's endpoint was down for more than a few hours, Support may want to follow the escalation route in [Support escalation playbook](../support/escalation.md).

For how `notify` fits into the payment and payout flows, see [Payments platform architecture](platform-architecture.md).
