---
title: "Vendor security review"
---

# Vendor security review

Owner: Security, with Beatrix Sallow, DPO, for anything that processes personal data.
Last reviewed: 2026-09-23.

Before Quillmoor starts using a new supplier's software or service, Security checks
that it is safe to trust with our data. This page explains when a review is needed, how
long it takes and what we look at. The [spend approval matrix](../finance/spend-approval.md)
says who approves the money; this review is the security part of the same decision.

## When you need one

You need a review before any of the following, whether the product is paid for or free:

- a new software product or online service that will hold Internal data or above;
- anything that connects to our systems, our identity provider, or our code
  repositories, including browser extensions and chat integrations;
- a renewal that widens what a supplier does with our data, such as a new product
  module or a new kind of data;
- a supplier that will process merchants' or staff members' personal data on our
  behalf.

You do not need one for tools that hold only Public information and connect to nothing,
such as a stock photo library. If in doubt, ask in `#team-security`.

## How to ask

1. Raise the purchase order in Tally as usual, following
   [raising a purchase order in Tally](../finance/purchase-orders.md), and tick
   "software or online service". For a free product, email security@quillmoor.example
   with the product's name and what you want to use it for.
2. Answer the four intake questions: what data the product will hold, its
   [classification](data-classification.md), how many people will use it, and what it
   connects to.
3. Security sets the tier and sends the supplier a questionnaire if one is needed.

Start early. The clock runs from the day the supplier returns its answers, not from
the day you ask, and suppliers are often slow.

## Tiers

| Tier | When | What we ask for | Target time |
|---|---|---|---|
| 1 | Restricted data, Confidential data in bulk, or any access to production | Full questionnaire, an independent audit report, a PCI DSS attestation if it touches cardholder data, a call with the supplier's security team | 15 business days |
| 2 | Confidential data in limited amounts | Short questionnaire and the supplier's published security documentation | 5 business days |
| 3 | Internal data only, no connection to our systems | Our checklist, completed by Security from public information | 2 business days |

## What we look at

- **Sign-in:** single sign-on through our identity provider, with MFA. A product that
  only offers its own passwords needs a strong reason and an exception under the
  [password and MFA standard](password-and-mfa.md).
- **Encryption** in transit and at rest, and who holds the keys.
- **Where data lives**, and the supplier's own sub-processors.
- **Breach notification:** how quickly and how the supplier will tell us.
- **Access:** who at the supplier can see our data, and how that is controlled and
  logged.
- **Exit:** how we get our data back, and how the supplier disposes of it when the
  contract ends.
- **Testing:** recent independent penetration tests, and how findings were handled.

## Personal data

If the supplier will process personal data on our behalf, the DPO reviews it as well,
the contract needs a DPA, and a supplier that processes merchants' data joins our
sub-processor list. The [DPA playbook](../legal/dpa-playbook.md) covers the contract
side; Legal handles it through Clausebook once Security has approved.

## Outcomes

- **Approved.** The supplier is added to the supplier register with its tier.
- **Approved with conditions.** For example: single sign-on must be switched on before
  anyone else is invited, or no personal data may be uploaded. The requester owns the
  conditions.
- **Not approved.** Security explains why and, where it can, suggests an alternative
  that has already passed review.

Tier 1 suppliers are reviewed again every 2 years, and any supplier is reviewed again
after a breach or a significant change in what it does for us.
