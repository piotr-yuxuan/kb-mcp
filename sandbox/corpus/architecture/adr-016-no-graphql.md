---
title: "ADR-016: Do not adopt GraphQL for the Merchant API"
---

- **Status:** Rejected, 2022-05-11. Proposed on 2022-04-25.
- **Author:** Priya Castellane, for Merchant Experience
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Yusuf Achterberg, Bram Oyelaran,
  Ama Rowntree

This record keeps a proposal that the architecture review turned down. The proposal
was to adopt GraphQL for the Merchant API; the title states the outcome. It is kept so
that the next person with the same idea can start from the reasons rather than from
scratch.

## Context

The newer pages of Merchant Hub are built in React and fetch their data from
`merchant-api`, the same public API that merchants integrate with. The API is
resource-oriented: one endpoint per kind of thing, over HTTP with JSON. For a
dashboard, that means many requests per screen. The payments overview makes nine
calls on first load: the merchant, the balance, recent payments, recent payouts, open
disputes and four lookups for related records. Most of the data fetched is never
shown.

The proposal, from the Merchant Experience team:

- add a GraphQL endpoint to `merchant-api`, covering the same resources;
- move Merchant Hub's pages to it, one query per screen;
- offer it to merchants as well, as an alternative to the resource endpoints.

Its benefits were real: fewer round trips, smaller responses, a typed schema that the
front end could generate code from, and one place to describe the API's shape.

## Decision

Rejected. The Merchant API stays resource-oriented, over HTTP with JSON. Merchant
Hub's needs are met another way.

The review gave six reasons.

1. **Writes and idempotency.** Every write to the API honours idempotency keys
   ([ADR-008](adr-008-idempotency-keys.md)), keyed on a request. A GraphQL request can
   hold several mutations, and we would need a second, parallel scheme for retries
   that merchants and our own engineers would have to learn.
2. **Cost and rate limits.** Rate limits today count requests. A GraphQL query's cost
   depends on its shape, so we would need query cost analysis, depth limits and a new
   kind of limit for merchants to understand.
3. **Authorisation per field.** In a payments API, who may see what is the part we
   review most carefully. A graph that lets any client traverse from a payment to a
   payout to a seller multiplies the paths that review must cover.
4. **Who our users are.** We asked our forty largest merchants. Most integrate from
   back-end jobs that create payments and read payouts, and are well served by
   resources. Three said they would use GraphQL.
5. **Two public surfaces.** Offering both would double the documentation, the client
   examples and the support questions, for every change, for years.
6. **Caching and errors.** Our edge caching and our error codes follow HTTP semantics.
   GraphQL returns most errors inside a successful response, which our monitoring and
   our merchants' would have to relearn.

What we do instead:

- `merchant-api` gains composite endpoints for Merchant Hub on its internal surface,
  one per screen where it helps, such as `GET /internal/hub/payments-overview`. They
  are not part of the public API and carry no compatibility promise to merchants.
- Public endpoints gain an `expand` parameter for the most common related records,
  so that a merchant can fetch a payout and its seller in one call.

## Consequences

- Merchant Experience owns a small set of internal composite endpoints, shaped by the
  screens they serve, and changes them with the front end.
- The public API keeps one shape, documented once, with rules for request and
  response design in [API design guidelines](../engineering/api-design.md).
- Merchant Hub does not get a generated, typed client from a schema. The team will
  publish types for the composite endpoints by hand.
- We will look at this again if a large share of merchants ask for it, or if the
  number of composite endpoints grows past what one team can keep tidy.

## Alternatives considered

- **GraphQL for Merchant Hub only, not for merchants.** The closest call. It removes
  reasons 4 and 5 but keeps 1, 2 and 3 for our own front end, and would have meant
  running a gateway that a team of six would own alone.
- **gRPC between Merchant Hub's server side and `merchant-api`.** Does nothing for
  round trips from the browser, which is where the time goes.
- **Do nothing.** Nine calls per screen is slow on a poor connection and will get
  worse as screens grow.

## Related ADRs

- [ADR-008](adr-008-idempotency-keys.md): idempotency keys on every write.
- [ADR-023](adr-023-api-versioning.md): how the resource API changes over time.
- [ADR-024](adr-024-react-merchant-hub.md): React for Merchant Hub.
