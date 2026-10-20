---
summary: "Let payout operators roll back a payout-gateway release themselves"
---

## Problem

When a payout-gateway release misbehaves, payout operators have to page the Payouts
on-call engineer, who then follows the [rollback runbook](../../corpus/payments/payout-gateway-rollback.md)
by hand: pause the batch scheduler, drain the queue, roll back, resume. In the three
payout incidents of the last year, the page itself cost between 12 and 25 minutes
before anyone touched the release.

## Idea

A guarded button in the operations console that runs the runbook's steps in order,
with the same checks, and stops for a human at the drain step if in-flight batches do
not clear. It would never cross a ledger schema migration; those still go through the
Ledger team.

## Open questions

- Does this replace the generic path in [Reverting a bad release](../../corpus/release/reverting-a-release.md)
  for payout-gateway, or sit beside it?
- Who may press the button outside business hours?

Raised by Oskar Ngata after the June 2025 payouts incident.
