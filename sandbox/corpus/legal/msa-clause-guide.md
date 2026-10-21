---
title: "MSA clause guide"
---

| Item | Detail |
|---|---|
| Owner | Saoirse Lindqvist, general counsel |
| Day-to-day contact | Delphine Marchetti, senior commercial counsel |
| Templates | `TPL-MSA-MERCHANT` version 7; `TPL-MSA-MERCHANT-FR` version 3 |
| Audience | Sales, account management, Merchant Support leads, product managers |
| Last reviewed | 2026-07-14 |

Every merchant that uses Quillmoor signs our master services agreement (MSA). It is the
framework contract for Quillmoor Pay, Quillmoor Payouts, Merchant Hub and the Merchant
API, and it is where most negotiation with a merchant happens. This guide walks through
the clauses merchants push back on, gives our standard position and the fallbacks you
may offer without coming back to Legal, and says who must approve anything further.

It is written for colleagues who negotiate with merchants, not as legal advice. If the
merchant's lawyers are involved, bring Legal in early rather than late.

## How the contract fits together

The MSA is never signed alone. A merchant's contract is a bundle, and when two documents
disagree, the one higher in this list wins:

1. the DPA, for anything about personal data (see the [DPA playbook](dpa-playbook.md));
2. the order form, which holds the merchant's pricing, products and any agreed deviations;
3. the product schedules (Pay, Payouts, Merchant Hub and API);
4. the MSA general terms;
5. our published documentation, as updated from time to time.

Agreed deviations belong in the order form under "Special terms", never in a side letter
or an email. A deviation that is not in the order form does not exist when someone reads
the contract in two years' time.

## Positions at a glance

| Clause | Our position | Fallback you may offer | Beyond that |
|---|---|---|---|
| 4. Fees and set-off | Fees deducted from settlement; full set-off | Itemised monthly statement on request | Legal |
| 5. Reserves and holds | Discretion to hold or reserve | Notice and reasons within 2 business days | Legal and Risk |
| 7. Service levels | Service level schedule; credits are the sole remedy | Credits up to 10% of the month's fees | General counsel |
| 8. Confidentiality | Mutual, survives 3 years | Replace an existing NDA expressly | Legal |
| 12. Indemnities | Limited, mutual pair | None | General counsel |
| 13. Liability | Capped at 12 months' fees | Fixed floor of £150,000 for new merchants | General counsel; strategic merchants only |
| 14. Term | One-year initial term, then rolling | Merchant may leave on one month's notice after year one | Legal |
| 16. Governing law | England and Wales | French law and Paris courts for French merchants | Legal |
| 19. Audit | Our reports and certificates | One remote audit a year | Legal and Security |

The rest of this page goes clause by clause.

## 2. Services and onboarding

The services start only after the merchant passes our KYC checks. Merchants sometimes ask
for a go-live date in the contract; we can give a target date in the order form, but it
must say that it depends on KYC being complete. Questions about the checks themselves go
to Merchant Support (see [Answering KYC queries](../support/kyc-queries.md)).

## 3. Merchant obligations

The merchant must follow the card schemes' rules, keep its own environment compliant with
PCI DSS where it touches card data, and not use the services for prohibited business
types. These obligations are not negotiable: they flow down from our own obligations to
the card schemes and the acquiring bank. If a merchant objects, explain that we cannot
accept less than the card schemes impose on us.

## 4. Fees, settlement and set-off

We deduct our fees from settlement before paying the balance out. Settlement timing is not
written into the MSA; the product schedule points to our published settlement windows, so
that we can change cut-off times without amending every contract. Do not quote cut-off
times in a merchant's order form. Point merchants to
[Settlement windows and cut-off times](../payments/settlement-cutoffs.md) instead.

Our set-off right is wide on purpose:

> Quillmoor may set off against any amount due to the Merchant any Fees, Refunds,
> Chargebacks, fines or assessments imposed by the Card Schemes, and any other amount the
> Merchant owes to Quillmoor under this Agreement.

Merchants ask to narrow this to fees only. We cannot agree: chargebacks and scheme fines
are exactly what set-off protects us against. The fallback is to offer an itemised
monthly statement showing every deduction.

## 5. Reserves and payout holds

We may hold payouts or require a reserve when we see elevated risk. Our standard holding
rules for new sellers are operational, not contractual, and are described in
[Payout holds and releases](../payments/payout-holds.md); never copy them into the MSA.

**Fallback:** we may promise to tell the merchant of a new reserve, with our reasons,
within 2 business days of imposing it, unless the law or the card schemes forbid it. We
never give up the right to impose a reserve, and we never agree a maximum reserve amount
without Risk's written agreement.

## 6. Chargebacks and refunds

The merchant bears chargebacks and refunds on its transactions. We will help it defend
disputes, as described in [Chargebacks and disputes](../support/chargebacks.md), but the
contract must not make the outcome our responsibility. Requests to share chargeback
losses are declined without a fallback.

## 7. Service levels

The service level schedule commits to availability figures that are deliberately looser
than our internal SLOs (see the [SLO catalogue](../incidents/slo-catalogue.md)). Never
write an internal SLO figure into a merchant contract: the internal number is a target we
manage to, and it must stay free to change.

Service credits are the merchant's sole remedy for missing a service level. The fallback
is to raise the credit ceiling to 10% of the month's fees. Removing "sole remedy" goes to
the general counsel.

## 8. Confidentiality

The MSA's confidentiality clause mirrors our [mutual NDA](nda.md) and survives for 3 years
after the agreement ends. If the merchant signed an NDA during the sales process, the MSA
should replace it expressly, so that only one regime applies:

> This Agreement supersedes any prior confidentiality or non-disclosure agreement between
> the parties relating to its subject matter, and information disclosed under such an
> agreement is treated as Confidential Information under this Agreement.

## 10. Intellectual property and the Quillmoor name

We keep all rights in the platform. The merchant may display our name and the "Powered by
Quillmoor" mark at checkout, following [Using the Quillmoor name and logo](brand-use.md).
Merchants sometimes ask for the right to announce the partnership; that is handled by a
separate approval, not by changing the MSA.

## 12. Indemnities

The template has two indemnities and no others: the merchant indemnifies us for fines and
assessments from the card schemes caused by its breach, and we indemnify the merchant
against claims that the platform infringes a third party's intellectual property. General
"any breach" indemnities are refused, and there is no fallback below the general counsel.

## 13. Limitation of liability

This is the clause merchants care most about and the one where we have least room.

### The standard cap

Each party's total liability is capped at **12 months' fees**:

> Subject to clauses 13.3 and 13.4, each party's total aggregate liability arising out of
> or in connection with this Agreement shall not exceed the total Fees paid or payable by
> the Merchant in the 12 months immediately preceding the event giving rise to the claim.

The cap is mutual. Make that point early: merchants often assume it protects only us.

### Strategic merchants

For a merchant on the strategic list (see [Strategic merchants](../support/strategic-merchants.md)),
the cap may rise to **24 months' fees**, with the general counsel's approval. Nobody
else can approve it, and the approval must be recorded on the Clausebook request before
the order form is issued. The clause then reads:

> ...shall not exceed the total Fees paid or payable by the Merchant in the 24 months
> immediately preceding the event giving rise to the claim.

A merchant that is not on the strategic list stays at 12 months' fees. Do not suggest to a
merchant that a higher cap might be available; it only creates an expectation we will
not meet.

### What sits outside the cap

- fraud, and death or personal injury caused by negligence, which cannot be limited;
- the merchant's obligation to pay fees, refunds, chargebacks and scheme fines;
- our intellectual property indemnity;
- our obligation to remit settlement funds, which is a debt we owe and not a liability
  for loss.

Data protection claims have their own separate cap: the greater of £1,000,000 and twice
the general cap. This is often the answer to a merchant asking for unlimited liability
for data breaches: offer the separate cap rather than moving the general one.

### Excluded losses

Neither party is liable for indirect or consequential loss, loss of profit, revenue or
goodwill. Merchants sometimes ask to carve "lost revenue during an outage" out of this
exclusion. Decline: service credits cover outages.

### Fallback ladder

| The merchant asks for | You may answer | Who approves |
|---|---|---|
| A higher cap | 12 months' fees is our standard; explain it is mutual | Nobody, this is the standard |
| A fixed floor because its fees will be small at first | The greater of 12 months' fees and £150,000 | Commercial counsel |
| Unlimited liability for data breaches | The separate data protection cap | Commercial counsel |
| 24 months' fees | Only for strategic merchants | General counsel |
| Anything above 24 months' fees, or uncapped liability | No | Not available |

## 14. Term and termination

The initial term is one year and then rolls on until either side gives notice. After the
first year the merchant may leave on one month's notice; we give three months' notice.
Either side may end the contract at once for a material breach not remedied within 30
days, or on insolvency.

**Fallback:** a merchant may be allowed to leave during the first year on three months'
notice if it pays the minimum monthly fees for the remainder of the year.

## 15. Suspension

We may suspend the services immediately when we suspect fraud, when a card scheme or
regulator tells us to, or when continuing would breach the law. Merchants ask for prior
notice. We give notice "where lawfully permitted and practicable", and we will not accept
a fixed notice period.

## 16. Governing law

English law and the courts of England and Wales. French merchants may sign
`TPL-MSA-MERCHANT-FR`, which is under French law with the courts of Paris; the commercial
terms are identical. Any other law needs Legal.

## 17. Assignment and subcontracting

The merchant may not assign without our consent. We may assign within the Quillmoor group
and use subcontractors, including the sub-processors listed under our DPA. Merchants
sometimes ask for consent over our subcontractors; the DPA's objection process is the
answer.

## 18. Force majeure

Standard, but force majeure never excuses a payment obligation, on either side.

## 19. Audit

We meet audit requests with our certificates and independent reports first. The fallback
is one remote audit a year, on 30 days' notice, at the merchant's cost, scoped with
Security. On-site audits at Quill House need Legal and the head of security.

## Asking for a deviation

1. Raise an **MSA deviation** request in Clausebook (see
   [Requesting a contract review](contract-requests.md)), naming the merchant, the
   clause and the wording the merchant proposes.
2. Say what the deal is worth and whether the merchant is on the strategic list.
3. Commercial counsel replies with an answer or a counter-proposal. Anything needing the
   general counsel is routed to her automatically.
4. Agreed deviations go into the order form under "Special terms".
5. The order form is signed according to
   [Contract signature authority](contract-signature-authority.md).

Legal keeps a register of every deviation agreed since 2023. If a merchant tells you
"you agreed this for our competitor", ask us before you answer; the register usually shows
that the competitor accepted something in return.
