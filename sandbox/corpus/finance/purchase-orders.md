---
title: "Raising a purchase order in Tally"
---

# Raising a purchase order in Tally

> [!NOTE]
> Owner: Dominic Ferrabee, accounts payable lead. Last reviewed 2026-09-03.

A purchase order tells a supplier that Quillmoor has agreed to buy something, and tells
Finance that money is committed. Raise one before you accept a quote, sign anything or
let work start. This page is the how-to; who approves at which value is on the
[spend approval matrix](spend-approval.md).

## Before you start

Have these to hand:

- **A quote or proposal** from the supplier, in writing.
- **The supplier's name.** Search for it in Tally first; if it is new, Tally asks for the
  supplier's contact and opens a set-up request for accounts payable.
- **The cost centre** that will pay, from the [cost centre list](cost-centres.md).
- **The total value excluding VAT, over the whole committed term.** A two-year
  subscription is two years' fees.
- **Whether it is software or an online service**, and whether the supplier will handle
  personal data.

## Step by step

1. In Tally, open **Purchasing > New purchase order**.
2. Choose the supplier and the cost centre.
3. Choose a category, such as software, contractors, professional fees, events or
   office. The category sets the account code.
4. Enter one line per item, with the net amount, the currency and, for services, the
   start and end dates.
5. Tick **Software or online service** if it applies. Tally adds Security's review.
6. Answer the question **Will the supplier process personal data for us?** A yes adds
   Legal's review.
7. Attach the quote and write a description someone outside your team would understand:
   what, why, and for how long.
8. Submit. Tally shows the approval route before you confirm.

Approvers see your request in Tally and by email. You can follow its progress under
**My requests**, and you can remind an approver from there after two business days.

## When it is approved

Tally gives the purchase order a number in the form `PO-` followed by six digits, such
as `PO-104382`, and emails the purchase order to the supplier's contact, with a copy to
you. Ask the supplier to quote that number on every invoice; invoices without it are held
(see [paying suppliers](paying-suppliers.md)).

Only now may you confirm the order with the supplier. If a contract has to be signed,
that follows its own rules on
[contract signature authority](../legal/contract-signature-authority.md).

## Receiving

When the goods arrive or the service is delivered, mark the purchase order as received
in Tally under **My purchase orders > Receive**. For a service that runs over several
months, receive each month's share at the end of that month. Receipts are what let
accounts payable pay the invoice, and what tell Finance to accrue the cost if the invoice
is late.

## Changing or closing a purchase order

- **More money or a longer term:** use **Request change**. The change is approved at the
  level of the new total.
- **Less money:** use **Request change** as well; reductions need only the budget
  holder.
- **Done:** close the purchase order once the last invoice is paid. Tally closes purchase
  orders automatically 90 days after their end date if nothing is outstanding.

## Common reasons for a rejection

| Reason | How to avoid it |
|---|---|
| Value for one year on a multi-year contract | Enter the whole committed term |
| Software box not ticked | Tick it for any tool, plugin or online service, free ones included |
| No quote attached | Attach the supplier's written quote or proposal |
| Wrong cost centre | Use the cost centre that benefits, with its budget holder's agreement |
| Purchase order raised after the invoice | Raise it before you commit; retrospective ones are reported monthly |

## Help

Ask in `#ask-finance`. For a question about a particular purchase order, include its
`PO-` number.
