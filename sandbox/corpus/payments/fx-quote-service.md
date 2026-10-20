---
title: "fx-quote service"
---

*Owner: Payments Core (`#team-payments-core`). Last reviewed: 2026-09-08. Written in Go.*

`fx-quote` gives other services a rate to convert an amount between two currencies, and promises to honour it for a short time. Quotes are valid for 30 seconds.

## How a quote works

A caller asks for a quote, gets back an identifier, a rate and an expiry, and passes the identifier when it books the conversion. The ledger refuses a conversion whose quote has expired, so a caller that waits too long must ask again.

```json
{
  "quote_id": "fxq_8Tn42LwB",
  "sell_currency": "GBP",
  "buy_currency": "EUR",
  "rate": "1.168400",
  "rate_timestamp": "2026-09-08T09:41:12.408Z",
  "issued_at": "2026-09-08T09:41:13.002Z",
  "expires_at": "2026-09-08T09:41:43.002Z"
}
```

Rates are decimal strings with six places; amounts converted with them are rounded half-even to minor units by the ledger, not by the caller.

The callers today are `card-auth`, when a buyer pays in a currency the merchant does not settle in, and `payout-gateway`, when a seller's balance and bank account are in different currencies.

## The rate feed

`fx-quote` takes mid-market rates from an external rate provider over a streaming feed, normally updated several times a second for GBP and EUR. Each rate carries the provider's own timestamp, and `fx-quote` judges a rate's age by that timestamp, not by when the rate arrived.

## FXQ-2002 STALE_RATE

`FXQ-2002 STALE_RATE` means that a quote used a rate older than 60 seconds.

Two limits are easy to confuse:

| Limit | Applies to | Value |
|---|---|---|
| Quote validity | How long a caller may use a quote after it is issued | 30 seconds |
| Rate freshness | How old the underlying rate may be when the quote is issued | 60 seconds |

Since the rewrite, `fx-quote` checks the rate's age before it issues a quote. If the newest rate for the pair is older than 60 seconds, it refuses to quote and returns `FXQ-2002` to the caller, rather than issuing a quote nobody should trust. Callers handle the refusal in their own way: `card-auth` declines the cross-currency authorisation with a retryable reason, and `payout-gateway` leaves the payout queued for the next cycle.

The Lantern dashboard "fx-quote overview" shows `fxquote_rate_age_seconds` per currency pair and the rate of `FXQ-2002` refusals. A rate age climbing steadily past 10 seconds is the early warning; by 60 it is an incident.

## History

The service was rewritten under ENG-5, finished in May 2026. The old service cached rates for each caller and could not say how old a rate was. During the rewrite, a bug produced `FXQ-2002` when the rate feed lagged: the new service kept quoting from the last rate it had received, and the staleness was only caught when the quote was booked, by which time the payment had gone through. The fix moved the age check to the moment of quoting, as described above.

The stale quotes incident of August 2026 is written up in [Incident report 2026-08-08: stale FX quotes](../incidents/report-2026-08-08-stale-fx.md).

## See also

- [Payments platform architecture](platform-architecture.md)
- [Runbook: card authorisation latency](card-auth-latency.md), where `fx-quote` is one stage of an authorisation
