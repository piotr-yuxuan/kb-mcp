---
title: "Payout delays: what to tell merchants"
---

Owner: Femi Haldane. Last reviewed 2026-09-22. Questions about this page: `#team-support`.

"Where is my payout?" is the question marketplaces ask most, and the one where a vague answer does most harm: their sellers are waiting too. This page lists what to check, in order, and what to say for each cause. Payouts tickets are P2 when a payout has not been sent at all; see [Ticket priorities and SLAs](priorities-and-slas.md).

## First, three checks

1. **Is there an incident?** Look at Beacon, `status.quillmoor.example`, and at `#team-support` for a pinned incident message. If an incident covers payouts, answer with `incident-known-issue` and stop here.
2. **What does the payout's status say?** Open the payout in the back office, or ask the merchant for its reference from Merchant Hub.
3. **When was it expected?** Merchant Hub shows an expected arrival date for every payout. Many "late" payouts are not late yet.

## By status

**Scheduled.** The payout has not left yet. Usually it was created after the day's cut-off, or a weekend or bank holiday lies between now and the next payout run. The cut-off times by currency are on [Settlement windows and cut-off times](../payments/settlement-cutoffs.md); use them to work out the expected date before you reply. Macro: `payout-delay-cutoff`.

**In transit.** We have sent the payout to our settlement bank, and it is travelling to the seller's bank. Most arrive on the expected date. If it is more than 2 business days past the expected date, escalate to T2 with the payout reference: T2 can obtain a trace from the settlement bank.

**Paid.** Our settlement bank has confirmed the payment. If the seller still cannot see it, the seller's own bank is holding or crediting it; give the merchant the payout reference so that the seller can ask their bank. We cannot see inside another bank.

**Failed.** The seller's bank returned the payout, most often because the account details are wrong or the account is closed. The money returns to the balance and is paid out again once the details are corrected in Merchant Hub. Macro: `payout-bank-rejected`.

**On hold.** Someone has held the payout on purpose. There are two common reasons:

- the seller is new to the marketplace, and their first payouts are held for an initial period, released by Risk; see [Payout holds and releases](../payments/payout-holds.md). Macro: `payout-hold-new-seller`.
- a verification review is open on the merchant or the seller; see [Answering KYC queries](kyc-queries.md).

Support cannot release a hold. Do not say when Risk will release it unless the back office shows a release date.

## "The payout is lower than I expected"

That is a different question from a delay, and usually has a simple answer. The payout report in Merchant Hub lists everything deducted from the balance before the payout: refunds made in the period, disputed amounts and dispute fees, and our processing fees. Walk the merchant through the report line by line before escalating. If the report itself looks wrong, escalate to T2.

## What not to say

- Do not quote internal error codes, such as `PGW-5021`, or name internal services. Merchants cannot act on them.
- Do not promise a time that the status does not support. "It should arrive today" is a promise.
- Do not tell a merchant that another merchant is affected.
- Do not blame the seller's bank until the status is **Paid**.

## When several merchants write in

If three or more merchants report missing payouts within 30 minutes, it is no longer a series of tickets but a possible incident: follow the paging rule in [Support escalation playbook](escalation.md). Do not wait for Beacon to confirm it.

## Templates

`payout-delay-cutoff`:

> Your payout {{payout.reference}} was created after today's cut-off time for {{payout.currency}} payouts, so it will be sent with the next payout run and should arrive on {{payout.expected_date}}. You can follow its status in Merchant Hub under **Payouts**.

`payout-bank-rejected`:

> Payout {{payout.reference}} was returned by the receiving bank, which usually means the account details are incorrect or the account is closed. The funds are back in your balance. Once the bank details are updated in Merchant Hub, the payout will be sent again with the next payout run.

`payout-hold-new-seller`:

> Payouts to sellers who have just joined your marketplace are held for an initial period, as part of our standard checks. You can see the expected release date, where one is set, on the seller's page in Merchant Hub. No action is needed from you or the seller.
