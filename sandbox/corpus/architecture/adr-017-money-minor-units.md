---
title: "ADR-017: Represent money in integer minor units"
---

- **Status:** Accepted, 2022-11-07
- **Author:** Kwabena Stroud
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Yusuf Achterberg, Arjun Pelletier

## Context

The public API has always sent amounts as whole numbers of pence or cents. Inside our
systems, nobody wrote that down, and practice has drifted:

- some Python back-office jobs use `Decimal` with two places;
- one Go service holds converted amounts in `float64`;
- a finance report computed totals in floating point and printed them rounded;
- two database tables store amounts as `numeric(12,2)`, one as `bigint`.

In September a reconciliation break of a single penny took two engineers a day to
trace. A converted amount had been computed in floating point, rounded in one service
and truncated in another. Finance tolerated it once; it would not scale to the volumes
we expect, nor to every new currency we add.

## Decision

Every monetary amount at Quillmoor is an integer number of the currency's minor unit,
always paired with the currency's ISO 4217 alphabetic code.

- **Everywhere.** In APIs, events, database columns, files we produce, logs and
  metrics. There is no internal exception.
- **The exponent comes from ISO 4217.** GBP and EUR have two decimal places, so
  £12.50 is `1250`. Some currencies have none, and a few have three. Code never
  assumes two; it reads the exponent from the shared currency table.
- **No floating point** for money, ever, including in intermediate steps.
- **Databases** store an amount as `bigint` and its currency as `char(3)`, in two
  columns next to each other.
- **JSON** carries an integer `amount` and a string `currency`.
- **Converting** between currencies produces an integer amount in the target currency.
  The rounding rule for conversions belongs to `fx-quote` and is applied there once;
  see [fx-quote service](../payments/fx-quote-service.md).
- **Splitting** an amount, for example a fee across several sellers, uses
  largest-remainder allocation, so that the parts always add up to the whole.
- **Formatting** for people, with symbols and separators, happens only at the edge:
  in Merchant Hub, in emails and in reports.

```go
type Money struct {
	Amount   int64  // minor units
	Currency string // ISO 4217 alphabetic code, such as "GBP"
}
```

```python
def allocate(total: int, weights: list[int]) -> list[int]:
    """Split total minor units by weights; the parts always sum to total."""
    base = [total * w // sum(weights) for w in weights]
    remainders = sorted(
        range(len(weights)),
        key=lambda i: total * weights[i] % sum(weights),
        reverse=True,
    )
    for i in remainders[: total - sum(base)]:
        base[i] += 1
    return base
```

## Consequences

- One representation, so a penny can no longer appear or vanish between services.
- Existing `numeric` columns and the `float64` service are migrated, each by its
  owning team, before the end of the fiscal year.
- Files from outside, such as bank statements, use decimal strings. They are parsed
  into minor units at the boundary and never travel further as strings.
- Engineers must remember that `1250` means £12.50 and not £1,250. Field names in new
  code say so where it helps (`amount_minor`), and the shared types make it hard to
  get wrong.
- The terms used for amounts in payments, such as capture, settlement and payout, are
  defined in the [Payments glossary](../payments/glossary.md).

## Alternatives considered

- **Decimal types everywhere.** Exact, but Go has no standard decimal type, JSON has
  no decimal type at all, and every language would round differently at the edges.
- **Amounts as decimal strings.** Exact and readable, but every consumer must parse
  them, and sorting or summing in a database becomes a trap.
- **Leave it to each team.** That is how we got the penny.

## Related ADRs

- [ADR-004](adr-004-postgresql.md): the databases that hold these columns.
- [ADR-008](adr-008-idempotency-keys.md): its example request already used minor
  units.
- [ADR-012](adr-012-database-per-service.md): each owning team migrates its own
  columns.
