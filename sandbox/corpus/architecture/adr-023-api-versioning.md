---
title: "ADR-023: Version public APIs by date"
---

- **Status:** Accepted, 2026-02-23. Implementation in progress under ENG-30.
- **Author:** Ama Rowntree, head of product
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Yusuf Achterberg, Bram Oyelaran,
  Oskar Ngata

## Context

The Merchant API has lived under `https://api.quillmoor.example/v1/` since 2017. Our
promise to merchants has been simple: within `/v1`, we only ever add. New endpoints,
new optional fields and new optional parameters arrive; nothing is renamed, removed or
changed in meaning.

That promise has served merchants well, and it is now costing us more than it saves.

### What "only add" has left behind

- **Names we cannot fix.** `payout.arrival_date` is the date a payout leaves our
  settlement bank, not the date it reaches the seller. Merchant Support explains the
  difference several times a week. We cannot rename it.
- **Defaults we regret.** List endpoints return 10 items by default. Most integrations
  page through hundreds, one request at a time, because changing the default would
  change what existing code receives.
- **Accidents.** In 2024 a field that had always been a string started, in one rare
  case, to be `null`. It was additive in our eyes, and it broke the nightly jobs of
  four merchants. We have no mechanism to give a change only to merchants who are
  ready for it.

### What is waiting on it

- **Self-serve refunds** (ENG-6, [the product brief](../product/brief-self-serve-refunds.md))
  adds refunds that wait for a second approval. Showing that state properly on the
  existing payment resource means a status value that existing integrations do not
  expect, and many of them treat the status as a closed list.
- **Multi-currency settlement** (ENG-4, [the product brief](../product/brief-multi-currency.md))
  gives merchants balances in more than one currency. The balance resource holds a
  single amount, in the settlement currency, and cannot show the others without a
  breaking change.

### Why not `/v2`

A new path version would fork the entire surface at once: every endpoint, every
document, every example. A merchant who wants one change would have to move
everything, and we would run two APIs side by side for years. Merchants have told us,
through Merchant Support and in reviews with our largest accounts, that they want to
take changes one at a time, on their own schedule, and to try a change on a single
request before committing to it.

## Decision

The Merchant API is versioned by date. A version is named after the day it was
released, and a client chooses it with a header:

```text
Quillmoor-Version: 2026-04-01
```

### The rules

1. **The path stays `/v1`**, for good. It is a namespace now, not a version.
2. **Versions are dates**, written `YYYY-MM-DD`, named after the day they are released.
   A later date is always a later version.
3. **The first dated version is `2026-04-01`**. It is the Merchant API exactly as it
   behaves on that day, frozen. Every merchant account that exists before then is
   pinned to it.
4. **Each account is pinned to a version.** A request without the header is served at
   the account's pinned version. A new account is pinned to the newest version on the
   day it is created. A merchant moves its pin forward in Merchant Hub; for 72 hours
   after a move, it can move the pin back.
5. **The header overrides the pin**, for that request only. This is how a merchant
   tests a new version before moving to it.
6. **Each version is supported for 24 months** from its release date. While it is
   supported, it behaves as documented, and fixes to security issues and outright bugs
   are applied to it.
7. **At most four new versions a year.** Changes that break nothing ship to every
   version continuously and need no new version.
8. **Every response says which version served it**, in its own `Quillmoor-Version`
   header.
9. **An unknown or malformed version** is rejected with `400` and the error code
   `invalid_version`. A version past its support period is rejected with `400` and
   `version_retired`.

### What counts as breaking

| Change | Breaking? |
|---|---|
| A new endpoint | No |
| A new optional request parameter or field | No |
| A new field in a response | No |
| A new value in an enumeration that clients are documented to treat as open | No |
| A new value in any other enumeration, such as a status | Yes |
| Renaming or removing a field, parameter or endpoint | Yes |
| Changing a field's type, format or meaning | Yes |
| A field that could be absent or `null` and was not before | Yes |
| A new required parameter, or a stricter validation | Yes |
| A changed default, such as a page size | Yes |

The full guidance for designing requests and responses, including how to name a field
so that it does not need renaming later, is in
[API design guidelines](../engineering/api-design.md).

### How it is built

`merchant-api` implements only the newest version in its core. Each breaking change is
written once, as a pair of transformations that sit at the edge of the service: one
that turns an older request into the newer shape, and one that turns a newer response
back into the older shape. A request at an old version passes through the chain of
transformations from its version up to the newest, and its response passes back down.

Each change is registered in one file, with its version and its transformations, so
that the documentation and the changelog are generated from the same source:

```yaml
# merchant-api/versions.yaml (illustrative)
- version: 2026-04-01
  changes: []                    # the baseline, frozen
- version: next
  changes:
    - id: balance-per-currency
      summary: The balance holds one amount per currency.
      response_downgrade: keep the settlement currency's amount only
    - id: payment-status-awaiting-approval
      summary: A payment can show a refund awaiting approval.
      response_downgrade: report the status as before the refund was requested
```

### An example: trying a version before moving to it

A marketplace pinned to `2026-04-01` reads its balance and gets the shape it has always
had, one amount in its settlement currency:

```json
{
  "object": "balance",
  "available": { "amount": 1843250, "currency": "GBP" },
  "pending": { "amount": 92000, "currency": "GBP" }
}
```

Once a later version with per-currency balances is released, the marketplace's
engineers can try it on one request, without touching the pin and without affecting
any other request from their account:

```bash
curl https://api.quillmoor.example/v1/balance \
  -H "Authorization: Bearer $QM_SECRET_KEY" \
  -H "Quillmoor-Version: <the newer version>"
```

The answer comes back in the new shape, and its `Quillmoor-Version` response header
confirms which version produced it:

```json
{
  "object": "balance",
  "available": [
    { "amount": 1843250, "currency": "GBP" },
    { "amount": 415700, "currency": "EUR" }
  ],
  "pending": [
    { "amount": 92000, "currency": "GBP" }
  ]
}
```

When their code handles both, they move the pin in Merchant Hub, watch their
integration for a day, and either keep the new version or move the pin back within the
72 hours. Requests that name a version in the header are unaffected by the pin either
way, which is why we recommend that merchants send the header explicitly once they
have finished moving.

### Webhooks

Webhooks sent by `notify` are rendered at the merchant's pinned version at the moment
they are sent, and carry an `api_version` field in their body. A webhook replayed later
is rendered at the version pinned at the time of the replay; see
[How to replay a merchant webhook](../payments/replay-webhook.md).

### Idempotency

The version is part of the request fingerprint used for idempotency keys
([ADR-008](adr-008-idempotency-keys.md)). A retry that reuses a key with a different
`Quillmoor-Version` is a different request, and is rejected as a reused key.

### Telling merchants

- The changelog on `developers.quillmoor.example` lists every version and every change
  in it, with what to do.
- A version approaching the end of its support period is announced by email to the
  account's technical contacts six months, three months and one month before it ends,
  and by a banner in Merchant Hub.
- Responses served at such a version carry the standard `Deprecation` and `Sunset`
  headers, so that a merchant's own monitoring can notice.
- When a version reaches the end of its support, accounts still pinned to it are moved
  to the oldest supported version, after the last notice.

## Consequences

### For merchants

- They take breaking changes when they choose, one version at a time, and can try a
  version on a single request first.
- They know how long they have: 24 months from the release of the version they are on.
- An integration that never sends the header keeps working exactly as it did, until
  its version's support ends.

### For us

- Breaking changes become possible again, which unblocks the refunds and multi-currency
  work above.
- Every live version is code we maintain. At four versions a year and 24 months of
  support, up to eight versions can be live at once. Each transformation must be
  tested at every version it touches, so contract tests run against every supported
  version in continuous integration.
- Merchant Support needs to see an account's pinned version, and the version of each
  request in the logs, to answer questions. Both are part of ENG-30.
- Merchant Hub calls `merchant-api` with the newest version, explicitly, on every
  request. It never relies on a pin.
- The internal composite endpoints for Merchant Hub, from
  [ADR-016](adr-016-no-graphql.md), are not versioned this way. They change with the
  front end that uses them.

### Delivery

The work is epic ENG-30, Date-based API versioning, planned for ENG Sprint 34 to ENG
Sprint 40. It covers the `Quillmoor-Version` header and its validation, pinning and
the Merchant Hub settings page, the transformation framework, the generated changelog,
and the first version after `2026-04-01`. Until the header ships, every request is
served as `2026-04-01`.

## Alternatives considered

### A new path version, `/v2`

Simple to explain and common in our industry. It forces every change on a merchant at
once and doubles our surface for years. The forces above are exactly the ones it
handles worst.

### A version in the media type

Clients would ask for `application/vnd.quillmoor.v2+json` in the `Accept` header.
It is as expressive as a custom header, harder to type in a terminal, and confusing in
error responses whose media type differs from the one requested.

### A version as a query parameter

Easy to try in a browser, easy to lose: query parameters are stripped by some proxies
and logged in places where we would rather not log full URLs.

### Semantic version numbers in the header

`Quillmoor-Version: 1.4` says nothing about how old an integration is. A date does,
and dates sort by themselves.

### Keep adding, and never break

The status quo. It blocks the two pieces of work above, and the accidents show that
"never break" is a promise we cannot keep without a mechanism behind it.

### GraphQL schema evolution

Considered and rejected for the Merchant API in ADR-016, for reasons that still hold.

## Related ADRs

- [ADR-008](adr-008-idempotency-keys.md): the version is part of the idempotency
  fingerprint.
- [ADR-016](adr-016-no-graphql.md): the Merchant API stays resource-oriented.
- [ADR-017](adr-017-money-minor-units.md): amounts in every version are integer minor
  units.
- [ADR-024](adr-024-react-merchant-hub.md): Merchant Hub, which always sends the newest
  version.
