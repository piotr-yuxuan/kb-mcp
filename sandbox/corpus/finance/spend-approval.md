---
title: "Spend approval matrix"
---

# Spend approval matrix

> [!NOTE]
> Owner: Arjun Pelletier, finance director. Approved by Idris Kallenberg, CFO.
> Last reviewed on 2026-08-14. Next review due with next year's budget.

This matrix says who must approve a commitment to spend Quillmoor's money with a
supplier before the commitment is made. In practice that commitment is a purchase order
raised in Tally, and the matrix is built into Tally's approval routing, so most people
never need to read this page twice. Read it once, though: Tally can only route what you
tell it, and the most common reason for a payment being held is a purchase order raised
with the wrong value, the wrong cost centre or after the invoice arrived.

## 1. Scope

The matrix covers every purchase of goods or services from a supplier, whatever the
amount and however it will be paid, including:

- software subscriptions, licences and renewals, free tiers and trials included;
- contractors, consultants and agencies;
- cloud commitments and marketplace purchases;
- events, sponsorships and venues;
- furniture, equipment and office services;
- professional fees such as audit, tax and legal advice.

It does not cover:

- **Signing the contract.** Approving the spend and signing the agreement are two
  different decisions, made by people who may not be the same. Who may sign, and at
  what value, is set out in
  [contract signature authority](../legal/contract-signature-authority.md). A purchase
  order approved under this matrix does not give anyone the right to sign.
- **Personal expenses** claimed back by employees, which follow the
  [expenses policy](expenses.md).
- **Salaries and new roles**, which follow [headcount planning](headcount-planning.md).
- **Refunds to merchants**, which are not spend and have their own approvals in
  Customer Support.

## 2. The matrix

The value that decides the approver is the **total value of the purchase order,
excluding VAT, over its whole committed term**.

| Total purchase order value, excluding VAT | Approver | Typical time in Tally |
|---|---|---|
| Under £10,000 | The budget holder of the cost centre charged | Same day |
| £10,000 to £100,000 | The finance director, after the budget holder | 2 business days |
| Over £100,000 | The CFO, after the budget holder and the finance director | 3 to 5 business days |

Approvals are cumulative: a purchase order of £40,000 is approved first by the budget
holder and then by the finance director; one of £150,000 by the budget holder, the
finance director and then the CFO. Exactly £10,000 and exactly £100,000 both go to the
finance director.

Today the finance director is Arjun Pelletier and the CFO is Idris Kallenberg. Budget
holders are listed against their cost centres in the [cost centre list](cost-centres.md).

## 3. Reviews that do not depend on value

Some purchases need a specialist review before Tally lets them reach the approvers
above. These reviews add to the matrix; they never replace it.

| Purchase | Review | Why |
|---|---|---|
| **Any software**, at any value, including free tools, trials, browser extensions and plugins | **Security** | Software reaches our laptops, our data or our production systems |
| A supplier that will process personal data on our behalf | Legal | We need a DPA in place before any data moves (see the [DPA playbook](../legal/dpa-playbook.md)) |
| Cloud commitments and reserved capacity | Platform and the FinOps working group | Commitments are bought centrally (see [cloud cost allocation](cloud-cost-allocation.md)) |
| Recruitment agencies | People | Agency terms are agreed centrally |
| Furniture, fit-out and office services | Workplace | The building, its leases and its insurance |

### Software needs Security's review

Every purchase of software goes through Security's review, whatever its value, and
that includes a tool that costs nothing. Tick **Software or online service** when you
raise the purchase order and Tally adds the review step automatically. Security's
reviewers follow the process on [vendor security review](../security/vendor-security-review.md)
and return one of three answers: approved, approved with conditions (for example single
sign-on only, or no production data), or rejected.

Allow about five business days for a new supplier. A renewal of software that Security
has already reviewed is usually faster, but it is still reviewed, because suppliers
change how they handle data between renewals.

> [!WARNING]
> Do not start a trial, connect a tool to your work account or install an extension
> while the review is pending. A free trial that holds company data is a purchase for
> the purposes of this page.

## 4. How to measure the value

- **Whole term.** A three-year subscription at £40,000 a year is a £120,000 purchase
  order, approved by the CFO, even if it is invoiced annually.
- **Excluding VAT.** Enter net amounts. Tally adds VAT when the invoice arrives.
- **Other currencies.** Tally converts at its daily rate on the day the purchase order is
  raised. If the converted amount sits within 5% of a threshold, use the higher route.
- **Usage-based pricing.** Estimate the committed or expected spend for the term and
  explain the estimate in the description. If actual usage later takes the total over a
  threshold, raise a change to the purchase order before the excess is incurred.
- **Changes.** A change that raises the value of a purchase order is approved at the
  level of the new total, not of the increase. Taking a £9,000 purchase order to £12,000
  sends the whole £12,000 to the finance director.
- **Renewals.** Each renewal is a new purchase order and is routed again.

### No splitting

Splitting one purchase into several purchase orders to keep each below a threshold is a
breach of this policy, even when every part is approved. Tally flags purchase orders to
the same supplier from the same cost centre within 30 days, and the finance controller
reviews every flag. If the work really is separate, say so in the description.

## 5. Before, not after

Approval must be in place before you commit, which means before you sign, before you
accept a quote by email and before work starts. Suppliers are asked to quote a purchase
order number on every invoice; an invoice without one is held by accounts payable until
a purchase order exists (see [paying suppliers](paying-suppliers.md)).

A purchase order raised after the invoice is a retrospective purchase order. It goes
through exactly the same matrix, and the finance controller lists every retrospective
purchase order, by cost centre, in the monthly management report. Two in a quarter from
the same cost centre will lead to a conversation with the finance director.

## 6. Absence and delegation

- A budget holder may delegate approval in Tally to another budget holder or to a named
  deputy in their team, for up to four weeks at a time. The delegate approves at the
  budget holder's level and no higher.
- When the finance director is away, purchase orders at that level are approved by the
  CFO. They are not delegated downwards.
- When the CFO is away for more than three business days, purchase orders over £100,000
  wait, unless the chief executive approves them in the CFO's place.
- No one may approve a purchase order they raised themselves, or one from which they
  benefit personally. Tally moves such a request to the next approver up.

## 7. Worked examples

**A design tool for the Design System team, £2,400 a year, one year.**
Under £10,000, so Priya Castellane approves as budget holder of `CC-3900`. It is
software, so Security reviews it first.

**A contractor for Data Platform for three months, at £600 a day for 60 days.**
The total is £36,000, so the budget holder of `CC-3700` approves and then the finance
director. Not software, so no Security review; no personal data, so no Legal review.

**A three-year observability commitment at £48,000 a year.**
The total is £144,000, over £100,000: the budget holder, the finance director and the
CFO, in that order. It is software and holds production telemetry, so Security reviews
it; logs may contain personal data, so Legal checks the DPA. Once the purchase order is
approved, the contract is signed under
[contract signature authority](../legal/contract-signature-authority.md), which is a
separate step with its own rules.

**Desks for the floor 5 refurbishment, £18,500.**
Between £10,000 and £100,000, so the budget holder and the finance director, with
Workplace's review because it is furniture.

**A free browser extension to help with screenshots.**
Zero pounds, so no purchase order approver beyond the budget holder, but it is software:
Security's review is still required, and until it is complete the extension stays
uninstalled.

**A £9,000 conference sponsorship that grows to £14,000.**
The original purchase order went to the budget holder alone. The change takes the total
to £14,000, so the finance director approves the change before the extra is committed.

## 8. What Tally does for you

When you submit a purchase order, Tally:

1. checks the cost centre and the budget holder;
2. adds the specialist reviews from section 3, based on the category you chose and the
   **Software or online service** box;
3. routes the request to the approvers in section 2, in order;
4. emails the purchase order number to you when the last approval lands.

The step-by-step guide is on [raising a purchase order in Tally](purchase-orders.md).

If the supplier is new to Quillmoor, Tally also opens a supplier set-up request for
accounts payable, who check the company's details and confirm its bank account by
telephone before the first payment. That check runs in parallel with the approvals and
rarely delays them.

## 9. Records and audit

Tally keeps every request, every approval and every comment, with the time and the
approver's name, for as long as the [data retention schedule](../data/retention-schedule.md)
requires for financial records. Nobody can edit an approval after the fact: a mistake is
corrected by cancelling the purchase order and raising a new one.

Each quarter the finance controller samples 25 purchase orders across all approval
levels and checks that:

- the value matched the quote and covered the whole term;
- the right approvers approved, in the right order, before the commitment date;
- every software purchase carried Security's review;
- the invoice, when it came, matched the purchase order.

The findings go to the finance director and, once a year, to the audit committee. Most
findings so far have been about the first check: subscriptions entered at one year's
value when the contract committed us to two or three.

## 10. Frequently asked questions

**Is this matrix the same as the contract signature limits?**
No. The two are set separately and the thresholds are not the same. Check both pages
before you commit.

**My spend is in the budget. Do I still need approval?**
Yes. The budget says the money is expected; the purchase order says this supplier, this
amount, now. See the [annual budget cycle](budget-cycle.md).

**Can I pay a supplier on my corporate card instead?**
Small, one-off purchases, yes, within the limits on [corporate cards](corporate-cards.md).
Software is the exception: it needs Security's review whatever the payment method, so
raise a purchase order or ask Security first.

**What if the supplier will not accept a purchase order?**
Raise one anyway, for our own control, and tell accounts payable in the description.

**Who can change this page?**
Only the finance director, with the CFO's approval. Changes are announced by email to
all budget holders.

## Related pages

- [Raising a purchase order in Tally](purchase-orders.md)
- [Paying suppliers](paying-suppliers.md)
- [Contract signature authority](../legal/contract-signature-authority.md)
- [Vendor security review](../security/vendor-security-review.md)
