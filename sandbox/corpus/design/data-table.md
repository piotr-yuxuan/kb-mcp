---
title: "Data table component"
---

# Data table component

| Owner | Last reviewed | Status | Channel |
|---|---|---|---|
| Teodor Ashby, with Merchant Experience | 2026-09-03 | Stable; column pinning added in 3.1 | `#team-inkwell` |

`DataTable` shows records that people scan, compare, sort and act on: payments, payouts, refunds, disputes, API request logs. It is the heaviest component in Inkwell and the one Merchant Hub leans on most; about two thirds of Merchant Hub pages are, at heart, a table with filters.

Use a plain `Table` instead when the data is small and static (a fee schedule, a list of three bank accounts) and needs no sorting, selection or pagination.

## Minimal example

```typescript
import { DataTable, type Column, Money, StatusBadge } from "@quillmoor/inkwell";

const columns: Column<Payout>[] = [
  { id: "created", header: "Date", cell: (p) => formatDate(p.createdAt), sortable: true },
  { id: "reference", header: "Reference", cell: (p) => p.reference },
  { id: "status", header: "Status", cell: (p) => <StatusBadge status={p.status} /> },
  {
    id: "amount",
    header: "Amount",
    align: "end",
    cell: (p) => <Money minor={p.amountMinor} currency={p.currency} />,
    sortable: true,
  },
];

export function PayoutsTable({ payouts, sort, onSortChange }: PayoutsTableProps) {
  return (
    <DataTable
      caption="Payouts"
      columns={columns}
      rows={payouts}
      getRowId={(p) => p.id}
      sort={sort}
      onSortChange={onSortChange}
      emptyState={{ title: "No payouts yet", body: "Payouts appear here once your first sale settles." }}
    />
  );
}
```

## Props worth knowing

| Prop | Default | Notes |
|---|---|---|
| `caption` | required | Visible by default; `captionHidden` keeps it for screen readers only |
| `columns` | required | Order, header text, alignment, sortability, width |
| `rows`, `getRowId` | required | Stable IDs matter: selection and focus follow the ID, not the index |
| `sort`, `onSortChange` | | Controlled. Sorting is done by your API, not in the browser, for anything paginated |
| `selection` | none | `single` or `multiple`; multiple adds a header checkbox and a bulk action bar |
| `density` | `comfortable` | `compact` uses `space.2` cell padding and 32 px rows; comfortable uses `space.3` and 48 px rows |
| `pageSize` | 25 | Options offered: 25, 50, 100 |
| `stickyHeader` | `true` | The header stays visible as the page scrolls |
| `pinnedColumns` | | Pin the identifying column on narrow screens |
| `loading` | `false` | Shows skeleton rows at the current height so the page does not jump |

## Money, dates and numbers

- Amounts arrive from our APIs in integer minor units, per [ADR-017](../architecture/adr-017-money-minor-units.md). Pass them straight to `Money` with the currency; never divide by 100 in product code, because not every currency has two decimal places.
- Amount columns are right-aligned (`align: "end"`) and use tabular figures, so pence line up.
- Negative amounts, such as refunds and chargebacks, show a minus sign, not brackets and not red alone.
- Dates follow the [content style guide](content-style.md): "14 Oct 2026" in tables, with the full timestamp in a tooltip.

## Row actions

- One obvious action per row: make the row's identifying cell a link to the detail page.
- Other actions go in a tertiary icon button at the end of the row, opening a menu. Label it with the row: "Actions for payout PO-2041".
- Destructive row actions confirm, as every destructive action does; see the [button page](button.md).
- Bulk actions appear in a bar above the table when rows are selected and say how many rows they affect: "Export 12 payouts".

## a11y notes

The component renders a real `table` with `th` headers and `scope`, and announces sort changes ("Sorted by amount, descending"). Sort buttons live inside the header cells and are reachable by Tab. Arrow-key cell navigation is available with `gridNavigation` for spreadsheet-like screens, but off by default because it changes how Tab behaves. Column reordering works by drag and through the column menu, so nobody has to drag. Tables may scroll sideways inside their own container at narrow widths, which the reflow rule allows for data tables. See the [a11y checklist](accessibility.md).

## Edge cases

- **Empty after filtering** is not the same as empty. Say "No payouts match these filters" and offer "Clear filters".
- **Errors** replace the body with a message and a "Try again" button; the header stays so the user keeps their bearings.
- **Very long references** truncate in the middle ("PO-20...4417"), because the end of a reference is usually the distinctive part.
- **Live updates** should not reorder rows under the pointer. New rows arrive in a "3 new payouts" bar that the user clicks to load.
- **Exports** should match what the table shows, including filters, and say so in the button: "Export filtered results".
