---
title: "API design guidelines"
---

# API design guidelines

Owners: Merchant Experience for the public Merchant API, and the backend guild for internal APIs. Last reviewed: 2026-09-23.

These guidelines apply to `merchant-api` and to every internal HTTP API. A new public endpoint is reviewed against them before it is built, in `#team-merchant-hub`; internal endpoints are reviewed with the change that adds them.

## Decisions already made

| Topic | Decision | Recorded in |
|---|---|---|
| Style | Resource-oriented JSON over HTTPS; no GraphQL | [ADR-016](../architecture/adr-016-no-graphql.md) |
| Versioning of the public API | By date, in the `Quillmoor-Version` header | [ADR-023](../architecture/adr-023-api-versioning.md) |
| Retrying writes | An idempotency key on every write | [ADR-008](../architecture/adr-008-idempotency-keys.md) |
| Money | Integer minor units with a currency code | [ADR-017](../architecture/adr-017-money-minor-units.md) |

The rollout of date-based versioning in `merchant-api` is epic ENG-30, under way this quarter. Until it finishes, ask in `#team-merchant-hub` before adding a field that changes the meaning of an existing one.

## Resources and paths

- Plural nouns for collections, identifiers for members: `/payouts`, `/payouts/{payout_id}`.
- Lower-case, hyphenated path segments: `/payout-holds`.
- An operation that is not create, read, update or delete becomes a sub-resource named as a noun: `POST /payments/{payment_id}/captures`, not `POST /payments/{payment_id}/capture-now`.
- Nest one level at most. `/merchants/{merchant_id}/payouts` is fine; anything deeper becomes a filter on the collection.

## Bodies

- JSON, with `snake_case` field names.
- Timestamps in RFC 3339, in UTC: `2026-09-23T14:05:00Z`.
- Money as an object holding integer minor units and an ISO 4217 code.
- Enumerations are lower-case strings, and clients must accept values they do not yet know.
- Card details in a response go no further than the scheme and the last four digits.

```json
{
  "id": "7c1e9a52f04b",
  "object": "refund",
  "payment_id": "3b88d0c4e7a1",
  "amount": { "minor": 2599, "currency": "GBP" },
  "status": "pending",
  "created_at": "2026-09-23T14:05:00Z"
}
```

## Errors

Every API returns errors in one shape, with an HTTP status that matches the class of problem and a stable code from the service's error catalogue, as the [coding standards](coding-standards.md) require.

```json
{
  "error": {
    "code": "FXQ-2002",
    "name": "STALE_RATE",
    "message": "This quote can no longer be used. Request a new quote.",
    "request_id": "a91f03d2"
  }
}
```

| Status | Use it when |
|---|---|
| 400 | The request is malformed or fails validation |
| 401 and 403 | Authentication is missing, or does not allow this |
| 404 | The resource does not exist, or this caller may not see it |
| 409 | The request conflicts with the current state, including an idempotency key reused with a different body |
| 422 | The request is valid but a business rule refuses it |
| 429 | Rate limited; `Retry-After` says when to try again |
| 500 to 599 | Our fault; safe to retry with the same idempotency key |

Messages are written for the developer integrating with us: say what happened and what to do next, in plain British English, without internal service names.

## Lists

Lists are paginated with cursors: `limit` (default 50, maximum 200) and `starting_after`, with `has_more` in the response. We never paginate by offset over a table that grows. Filters are query parameters named after the fields they filter: `?status=pending&created_after=2026-09-01T00:00:00Z`.

## Compatibility

Within a version, changes are additive only: new optional fields, new endpoints, new enumeration values. Renaming or removing a field, or changing what it means, needs a new dated version under ADR-023. Internal APIs follow the same rule, enforced by the contract tests in the [testing strategy](testing-strategy.md).

## Checklist for a new endpoint

- [ ] The path and resource names follow the conventions above.
- [ ] Every write takes an idempotency key.
- [ ] Errors use the shared shape and catalogued codes.
- [ ] Amounts are in minor units, with a currency.
- [ ] Every list is paginated.
- [ ] The endpoint is in the API reference before it is released.
- [ ] Requests are traced and logged as [logging and tracing](logging-and-tracing.md) describes.
