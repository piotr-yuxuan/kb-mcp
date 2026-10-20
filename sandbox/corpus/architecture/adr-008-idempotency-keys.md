---
title: "ADR-008: Idempotency keys on every write API"
---

- **Status:** Accepted, 2018-07-09
- **Author:** Nadia Ferreira
- **Deciders:** Ottilie Marsh, Yusuf Achterberg, Kwabena Stroud, Bram Oyelaran

## Context

On 14 May a marketplace's integration sent payout instructions to `merchant-api`,
timed out waiting for the answers, and sent them again. The first requests had
succeeded. Eleven sellers were paid twice, and we recovered the money by hand over the
following fortnight, with the marketplace's help and some embarrassment on both
sides.

Nothing about this was unusual. Networks drop answers, clients retry, and a client
cannot tell "the request never arrived" from "the request succeeded and the answer was
lost". The same is true inside our own systems: the event consumers introduced by
[ADR-007](adr-007-message-broker.md) receive each message at least once, and our
services retry calls to each other.

Some of our endpoints already guard against duplicates with a natural key, such as the
marketplace's own order reference. Most do not, and the ones that do each do it
differently.

## Decision

Every API that writes, public or internal, accepts an idempotency key, and honours it
in the same way.

- **The header.** The client sends `Idempotency-Key` with a value it chooses: any
  string of up to 255 characters, in practice a random identifier generated once per
  logical operation and reused on every retry of that operation.
- **Where it is required.** On `merchant-api`, every `POST` that creates a payment
  or a payout, or moves money in any other way, must carry the header; a
  request without it is rejected with `400`. On other write endpoints, and on internal
  APIs, it is optional but always honoured.
- **Scope.** On `merchant-api`, a key is scoped to the merchant account. Internally,
  it is scoped to the calling service.
- **What we store.** For each key, the server stores a fingerprint of the request
  (method, path and body) and, once processing has finished, the response. Keys are
  kept for 24 hours.

How the server answers:

| Situation | Answer |
|---|---|
| First request with this key | Processed normally; the response is stored |
| Same key and same request, first one finished | The stored response, replayed, with `Idempotent-Replayed: true` |
| Same key and same request, first one still running | `409`, and the client retries later |
| Same key, different request | `422`, error code `idempotency_key_reused` |
| Same key, more than 24 hours later | Treated as a new request |

For example:

```bash
curl https://api.quillmoor.example/v1/payouts \
  -H "Authorization: Bearer $QM_SECRET_KEY" \
  -H "Idempotency-Key: 9b2e4c7a-51f3-4d0e-8a6b-2f1c9d3e7a10" \
  -H "Content-Type: application/json" \
  -d '{"seller_id": "sel_4Kq81z", "amount": 2500, "currency": "GBP"}'
```

Event consumers apply the same idea with the event's own identifier: a consumer keeps
the `event_id` values it has processed for at least as long as the event could be
delivered to it again, and skips repeats.

## Consequences

- Every service that writes keeps an idempotency table in its own database
  ([ADR-004](adr-004-postgresql.md)), with a nightly job that removes keys older than
  24 hours. A shared library in each language does the bookkeeping.
- Merchants must generate and keep keys. The public documentation explains how, and
  our client examples always send one. Request and response conventions for our APIs
  are gathered in [API design guidelines](../engineering/api-design.md).
- A replayed response is the stored one, even if the resource has changed since. This
  surprises people once; the documentation says so.
- Idempotency protects calls into our APIs. It does not protect calls we make to
  parties that ignore our keys. The files we send to our settlement bank are one such
  case, which is why [Runbook: rolling back payout-gateway](../payments/payout-gateway-rollback.md)
  insists on draining in-flight batches first.

## Alternatives considered

- **Natural keys only.** Not every operation has one, and a marketplace's order
  reference is not unique across all of its sellers.
- **Exactly-once delivery.** Not something any network or broker can promise end to
  end. We stopped looking.
- **Asking clients not to retry.** They will retry anyway, and they should.

## Related ADRs

- [ADR-007](adr-007-message-broker.md): at-least-once delivery of domain events.
- [ADR-017](adr-017-money-minor-units.md): the `amount` in the example is in minor
  units.
- [ADR-019](adr-019-replicated-event-log.md): consumers of the replicated log still
  deduplicate by `event_id`.
- [ADR-023](adr-023-api-versioning.md): the API version is part of the request
  fingerprint.
