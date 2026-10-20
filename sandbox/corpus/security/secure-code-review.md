---
title: "Secure code review checklist"
---

# Secure code review checklist

Owner: Security. Last reviewed: 2026-09-16.

Use this list alongside the [code review guidelines](../engineering/code-review.md)
whenever a change touches authentication, authorisation, money, personal or cardholder
data, secrets, or input from outside the service. You do not need to tick every box on
every pull request: skip the sections that do not apply, and say in your review which
ones you checked.

## Ask Security to review as well

Add the `security-review` label to the pull request and mention it in
`#team-security` when the change:

- adds or changes a public endpoint on `merchant-api`;
- touches anything inside the card data environment;
- changes how users or services sign in, or how sessions and tokens are issued;
- uses cryptography beyond calling the standard TLS client;
- adds a dependency that parses untrusted input (images, documents, archives).

Security picks up labelled pull requests in the order they arrive. Say in the channel
if the change is blocking a release or an incident fix, and the on-call will look first.

## Checklist

### Input

- [ ] Every value from outside the service is parsed and validated at the boundary:
      type, length, range, allowed characters. Unknown fields are rejected on
      `merchant-api`.
- [ ] Database queries use parameters, never string formatting.
- [ ] File uploads are checked by content, not by name, and have a size limit.
- [ ] Redirect targets come from an allow-list.

```python
# Do: the driver sends the values separately from the query text
cur.execute(
    "SELECT id, status FROM payouts WHERE merchant_id = %s AND id = %s",
    (merchant_id, payout_id),
)

# Do not: the values become part of the query text
cur.execute(f"SELECT id, status FROM payouts WHERE id = '{payout_id}'")
```

### Authorisation

- [ ] Every endpoint checks that the caller may act on *this* merchant's object, not
      only that the caller is signed in.
- [ ] There is a test showing that merchant A cannot read or change merchant B's
      payment, payout or refund.
- [ ] Administrative actions check the role on the server and write an audit entry.

### Money

- [ ] Amounts are integers in minor units, as
      [ADR-017](../architecture/adr-017-money-minor-units.md) requires.
- [ ] Write endpoints accept an idempotency key, as
      [ADR-008](../architecture/adr-008-idempotency-keys.md) requires.
- [ ] Limits and second approvals are enforced on the server, not only in Merchant Hub.

### Secrets

- [ ] No secret in code, configuration, tests or fixtures. Services read them from
      Strongroom at run time; see [using Strongroom](strongroom-how-to.md).
- [ ] No secret, token or full authorisation header is written to logs, traces or
      error messages.
- [ ] The secret scanner passed. If it raised an `SCN-` finding, follow the
      [leaked secret playbook](leaked-secret.md) before merging; deleting the line is
      not enough.

### Data

- [ ] No PAN leaves the card data environment, in any form, including logs and test
      data. The boundary is described in
      [payments platform architecture](../payments/platform-architecture.md).
- [ ] New warehouse columns that hold personal data are tagged, following
      [tagging personal data columns](../data/personal-data-columns.md).
- [ ] Logs carry identifiers, not names, email addresses or bank details.

### Dependencies and cryptography

- [ ] Each new dependency is maintained, needed, and under a licence the
      [open-source licence policy](../legal/open-source-licences.md) allows.
- [ ] Cryptography comes from the standard library or the platform's shared library.
      No home-made algorithms, no custom random number generation for secrets.
- [ ] TLS certificate verification is never turned off, not even "for staging".

### Failure

- [ ] Errors returned to merchants carry a code and a request identifier, never a stack
      trace or a query.
- [ ] Sign-in and token endpoints are rate-limited.
- [ ] A failed authorisation check fails closed: the request is refused, not let
      through with a warning.

## When you find something

Comment on the pull request as usual if the change is not merged yet. If the problem is
already in production, do not describe it in a public channel: email
security@quillmoor.example, and Security will file it with a deadline under the
[vulnerability management SLAs](vulnerability-slas.md).
