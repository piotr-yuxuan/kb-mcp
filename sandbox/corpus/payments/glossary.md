---
title: "Payments glossary"
---

Plain-language definitions of the words payments engineers use every day, for colleagues in Support, Finance, Product and Legal who meet them in tickets and incident channels. Maintained by Payments Core; suggestions in `#team-payments-core`. Last reviewed 2026-06-30.

For how the services fit together, see [Payments platform architecture](platform-architecture.md), which also defines the two card-data acronyms used across these pages.

## The life of a card payment

**Authorisation.** The first step of a card payment. Quillmoor asks the issuer, through the acquiring bank and the card schemes, whether the buyer's card can pay this amount. If the issuer approves, the funds are reserved on the buyer's card but have not moved. An authorisation expires if it is not captured, usually after seven days, depending on the card scheme.

**Capture.** The merchant's instruction to take the money that an authorisation reserved. Most marketplaces capture when the order ships. A capture can be for less than the authorised amount (a partial capture), never for more. Only captured payments are settled.

**Settlement.** The actual movement of money between banks. For card payments, the card schemes settle captured amounts to the acquiring bank, which settles them to us, usually one or two business days after capture. For payouts, settlement is the moment our settlement bank pays the seller's bank. The word means "money moved", not "payment approved". Payout settlement times depend on currency cut-offs: see [Settlement windows and cut-off times](settlement-cutoffs.md).

**Payout.** A payment from Quillmoor to a marketplace seller of the money they have earned, less fees, in GBP or EUR. Payouts are grouped into batches that `payout-gateway` sends to our settlement bank every 15 minutes. A new seller's first payouts may be held; see [Payout holds and releases](payout-holds.md).

## Fees and disputes

**Interchange.** The fee the acquiring side pays the issuer on each card payment, set by the card schemes and varying with the card type, the region and how the payment was taken. It is the largest part of the cost of accepting a card. Merchants rarely see it directly; it is folded into our pricing.

**Chargeback.** A payment reversed by the issuer at the cardholder's request, after settlement, for example because the buyer says they did not authorise it or never received the goods. The merchant can contest a chargeback with evidence, which starts a dispute. Support's handling of chargebacks, including deadlines and fees, is in [Chargebacks and disputes](../support/chargebacks.md).

## Other words you will hear

| Term | Meaning |
|---|---|
| Acquiring bank | The bank that connects Quillmoor to the card schemes and settles card payments to us |
| Issuer | The buyer's bank, which issued the card and approves or declines each authorisation |
| Card schemes | The networks that carry card payments between acquiring banks and issuers and set their rules |
| Settlement bank | The bank that holds our client funds and pays sellers |
| Decline | An authorisation the issuer, or our risk checks, refused |
| Step-up | An extra authentication challenge to the buyer during checkout |
| Refund | Money returned to the buyer at the merchant's request; not a chargeback. See [Handling merchant refund requests](../support/refunds.md) |
| Batch | A group of payouts sent to the bank together |
| Journal | A ledger record of one movement of money, whose debits equal its credits |
| Break | A difference found by the nightly ledger reconciliation; see [Runbook: ledger reconciliation breaks](ledger-reconciliation.md) |
| Suspense account | Where the ledger parks an amount nobody can yet explain |
| Token | The stand-in for a card number that services outside the card data environment use |

## Words we avoid

- **"Transaction"** on its own: say whether you mean an authorisation, a capture, a refund or a payout. Incident channels lose a lot of time to this one.
- **"Settled"** to mean "approved": an approved authorisation has not settled.
- **"Paid"** for a payout that has only been batched: it is paid when our settlement bank confirms it.
