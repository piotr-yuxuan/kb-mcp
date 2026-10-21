---
title: "SQL style guide"
---

# SQL style guide

Owner: Rafael Quist, for Data Platform. Last reviewed 2026-05-14.

We write a lot of SQL, mostly for Trino, and read even more of it. This guide keeps it
readable by someone who did not write it. It applies to every model in
`data-pipelines` and is a strong suggestion for dashboards and ad hoc queries. Where it
is silent, match the file you are editing.

## The rules

1. **Lower-case keywords and functions.** `select`, `from`, `coalesce`. Upper case
   shouts and adds nothing that syntax highlighting does not.
2. **Four spaces of indentation, no tabs.**
3. **One column per line in a `select` list, trailing commas.**
4. **Always alias with `as`**, for columns and tables alike. Table aliases are short but
   meaningful: `o` for orders, `c` for captures; never `a`, `b`, `c` in sequence.
5. **Qualify every column** once a query joins more than one table.
6. **Explicit joins.** Write `inner join` or `left join` with an `on` clause; never join
   with commas in the `from` clause.
7. **Common table expressions over nested subqueries.** Name each step after what it
   holds: `captures_by_order`, not `cte2`.
8. **No `select *`** in models. List the columns, so that a new upstream column does not
   change your output silently, and so that Trino reads only what you need.
9. **Typed literals.** `date '2026-05-01'`, `timestamp '2026-05-01 00:00:00 UTC'`,
   never a bare string compared with a date.
10. **Grouping:** name the columns in `group by`. Positional `group by 1, 2, 3` is
    allowed only when the grouped columns come first in the `select` list and there are
    no more than five of them.
11. **Comments explain why**, not what. `-- refunds count on processing date, see the
    pipeline page` earns its place; `-- sum the amounts` does not.

## Before and after

```sql
-- Before
SELECT m.*, SUM(o.CAPTURED_AMOUNT_MINOR) tot
FROM marts.merchant_orders_daily o, staging.stg_merchant_api__merchants m
WHERE o.merchant_id = m.merchant_id AND o.order_date >= '2026-04-01'
GROUP BY 1,2,3,4,5,6,7,8,9
```

```sql
-- After
with april_captures as (
    select
        o.merchant_id,
        o.currency,
        sum(o.captured_amount_minor) as captured_amount_minor
    from marts.merchant_orders_daily as o
    where o.order_date >= date '2026-04-01'
      and o.order_date < date '2026-05-01'
    group by o.merchant_id, o.currency
)

select
    m.merchant_id,
    m.trading_name,
    c.currency,
    c.captured_amount_minor
from april_captures as c
inner join staging.stg_merchant_api__merchants as m
    on m.merchant_id = c.merchant_id
order by c.captured_amount_minor desc
```

## Money and time

- Amounts are integers in minor units. Divide by 100 only in the presentation layer,
  and only for currencies with two decimal places.
- Never add amounts across currencies; group by `currency` or use a `_gbp_minor`
  column.
- All timestamps are UTC. If you need a local day for a French merchant, convert
  explicitly with `at time zone 'Europe/Paris'` and say so in a comment.
- Ranges on dates are half-open: `>=` the first day and `<` the day after the last, so
  that month boundaries are never counted twice.

## Trino specifics

- Prefer `approx_distinct` to `count(distinct ...)` on large tables when an estimate
  will do; say so in the column name or a comment.
- `count_if(condition)` is clearer than `sum(case when ... then 1 else 0 end)`.
- Integer division truncates: cast to `double` or `decimal` before dividing.
- Use `try_cast` only where bad input is expected, and count what it turned into
  `null`.

For making queries cheaper as well as readable, see
[Keeping warehouse queries cheap](query-costs.md). Table and column names are covered
by [Warehouse naming conventions](naming-conventions.md).

## Formatting automatically

`data-pipelines` runs the formatter on every pull request; run it locally before you
push:

```bash
make sql-format        # rewrites models/ in place
make sql-lint          # fails on rules the formatter cannot fix, such as select *
```
