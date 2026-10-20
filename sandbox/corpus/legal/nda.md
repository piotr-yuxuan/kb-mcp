---
title: "Mutual NDA: template and guidance"
---

- **Page owner:** Delphine Marchetti, senior commercial counsel
- **Approver:** Saoirse Lindqvist, general counsel
- **Template:** `TPL-NDA-MUTUAL`, version 4, in Clausebook
- **Last reviewed:** 2026-09-03

Our mutual NDA is the contract that colleagues reach for most often, and the one most
often signed in a hurry. This page tells you when you need one, how to send ours without
waiting for Legal, and how to judge the changes a counterparty asks for. It is internal
guidance written by the Legal team for Quillmoor colleagues, not legal advice; when in
doubt, ask us at `legal@quillmoor.example`.

## When you need an NDA

You need an NDA before you share Confidential information with anyone outside Quillmoor
who is not already bound to us by a contract with a confidentiality clause. The usual
cases are:

- early conversations with a prospective partner, such as a marketplace platform weighing
  an integration with Quillmoor Pay or Quillmoor Payouts;
- evaluating a supplier before a purchase, when they need to see our architecture,
  transaction volumes or roadmap;
- a senior candidate who will be shown strategy material during the final interview
  (speak to People first, as the interview pack may be the better place for it);
- a research partner, such as a university group helping Risk ML with a study.

You do **not** need a separate NDA when:

- the counterparty is a merchant that has signed our MSA, which has its own
  confidentiality clause (see the [MSA clause guide](msa-clause-guide.md));
- the supplier has signed one of our supplier agreements, all of which include
  confidentiality terms;
- you only share Public information, such as anything already on `quillmoor.example` or
  in the published Merchant API reference.

If you are not sure how the material is classified, check
[Data classification](../security/data-classification.md) before deciding.

Investors, advisers on a financing and anyone discussing an acquisition never go through
the self-serve route. Send those straight to the general counsel.

## Mutual or one-way

Our default is mutual: in most conversations both sides end up sharing something, and a
mutual NDA is quicker to agree because it is plainly balanced.

| Situation | Template | Can you self-serve? |
|---|---|---|
| Both sides will share information | `TPL-NDA-MUTUAL` | Yes, if the text is unchanged |
| Only Quillmoor will share | `TPL-NDA-ONEWAY` | Yes, if the text is unchanged |
| Only the counterparty will share | Their paper, reviewed by Legal | No |
| French-speaking counterparty | `TPL-NDA-MUTUAL-FR`, bilingual | Yes, if the text is unchanged |
| Investor, financing or acquisition | Bespoke | No, general counsel only |

We are wary of one-way NDAs in the counterparty's favour. Someone pitching an idea to us
under a one-way NDA can later claim that a feature we built was theirs. If a start-up
wants to show you a product and insists on its own one-way NDA, raise a request and we
will usually propose our mutual template instead.

## The self-serve route

You may send and sign our template without a Legal review when **all** of these hold:

1. You generate it from Clausebook, not from a copy saved on your laptop or a shared
   drive. Old copies circulate and some still carry a residuals clause we removed in 2024.
2. You fill in only the open fields: the counterparty's full legal name, registered
   number, registered address, the purpose and the date.
3. The counterparty accepts the text unchanged. A single edited word takes the NDA out of
   the self-serve route.
4. No personal data and no cardholder data will be exchanged.
5. The person signing for us has authority under
   [Contract signature authority](contract-signature-authority.md). An NDA carries no
   contract value, so a head of department may sign it.

### Steps in Clausebook

1. Choose **New request**, then **NDA (self-serve)**.
2. Enter the counterparty's details. Clausebook warns you if an NDA with the same company
   is already in force; if it covers your purpose, use that one instead of signing another.
3. Write the purpose in one or two specific sentences (see the example below).
4. Pick the signatory. Clausebook sends the document for electronic signature, to the
   counterparty first and to our signatory second, so that we never sign a version they
   have not seen.
5. When both sides have signed, Clausebook files the NDA against the counterparty and sets
   a reminder 60 days before it expires.

A good purpose is narrow enough to stop the counterparty using our information for
something else, and wide enough to cover the conversation you will actually have:

> The parties wish to evaluate a possible integration between the Counterparty's
> marketplace platform and Quillmoor Pay, including the exchange of technical
> documentation, anticipated transaction volumes and indicative pricing (the "Purpose").

Avoid purposes such as "general business discussions": they protect neither side.

## Clause guide

For each clause below you will find what our template says, why, what counterparties
tend to ask for, and how far we can move. Anything beyond the fallback goes to Legal
through a Clausebook request.

### Definition of confidential information

Our definition is deliberately broad and does not depend on marking:

> "Confidential Information" means all information, in any form, disclosed by or on behalf
> of a party (the "Discloser") to the other party (the "Recipient") in connection with the
> Purpose, which is marked as confidential or which a reasonable person would understand to
> be confidential given its nature and the circumstances of its disclosure.

**What you will hear:** "Only information marked confidential should count."

**Fallback:** we may accept a marking requirement for written information, provided that
information disclosed orally or by demonstration counts if it is identified as
confidential at the time and summarised in writing within 30 days. Never accept
marking-only wording if the counterparty will attend a demo or visit Quill House, where
much of what they see cannot be marked.

### Exclusions

The template has the four usual exclusions: information that is or becomes public through
no fault of the Recipient, that the Recipient already lawfully held, that it develops
independently without using ours, or that it receives from a third party free to disclose
it. The Recipient carries the burden of showing that an exclusion applies.

Equivalent wording in the counterparty's own style is fine. Reject any exclusion that turns
on the Recipient's belief, such as "information the Recipient reasonably believes to be
public", because it is impossible to disprove.

### Use and standard of care

The Recipient may use our information only for the Purpose and must protect it with at
least the care it uses for its own information of a similar kind, and never less than
reasonable care. Requests to soften this to "commercially reasonable efforts" alone should
be declined; "reasonable care" is the floor.

### Who may see it

Disclosure is allowed to the Recipient's employees, officers, professional advisers and
contractors who need to know for the Purpose and are bound by duties at least as strict.
The Recipient stays responsible for them.

Counterparties often ask to add their affiliates. That is acceptable, provided the
Recipient remains liable for any affiliate's breach. Do not accept wording that lets the
Recipient share with "potential investors" or "financing sources" without our consent.

### Disclosure required by law

> If the Recipient is required by law, regulation or a competent authority to disclose any
> Confidential Information, it may do so to the extent required, provided that, where
> lawfully permitted, it gives the Discloser prompt notice and reasonable assistance to
> seek a protective order.

Keep this clause two-way. As a regulated payments business we must be able to answer our
regulators, the card schemes and the supervisory authority without first notifying the
counterparty, and the words "where lawfully permitted" preserve that.

### Term and survival

The agreement lasts **2 years** from the date of the last signature. Confidentiality
obligations survive for **3 years** after it expires or ends, and for trade secrets for as
long as the information remains a trade secret.

**What you will hear:** "One year in total is our standard."

**Fallback:** survival may come down to 2 years. Below that, ask Legal: technical material
about our payment flows stays sensitive for much longer than a year.

### Return and destruction

On request, or when the agreement ends, the Recipient must return or destroy our
information. Copies held in automatic backups may be kept until they are overwritten in the
normal course, and stay confidential meanwhile. We give the same commitment in return. We
will confirm destruction in writing on request, but we will not sign a certificate on a
deadline shorter than 30 days, because some of our own backups take that long to cycle
(see the [data retention schedule](../data/retention-schedule.md) for how long different
records live).

### No licence and no commitment

The NDA grants no licence over either side's intellectual property and does not oblige
anyone to sign a further agreement. Keep both statements: they stop an NDA being read as a
letter of intent.

### Residuals

A residuals clause lets the Recipient use anything its people remember unaided. It
undoes the whole agreement, and we **always reject it**. There is no fallback. If a
counterparty refuses to drop it, escalate to the general counsel.

### Non-solicitation

Our template has none. If a counterparty adds one, our first answer is to delete it. If it
matters to them, the fallback is a 6-month restriction limited to people directly
involved in the Purpose, with an exception for general job advertisements and for anyone
who approaches us first. Any non-solicitation clause needs Legal's approval, and People
must know about it.

### Remedies

Both sides accept that damages may not be an adequate remedy and that the Discloser may
seek an injunction. The NDA has no liability cap. Reject any proposal to add one; there is
no fallback below the general counsel.

### Governing law and jurisdiction

English law and the courts of England and Wales. For French counterparties the bilingual
template offers French law and the courts of Paris instead, and either option is fine. Any
other law goes to Legal.

## Reviewing a counterparty's NDA

When the counterparty sends its own paper, raise a **Third-party NDA review** in Clausebook
and attach the document in an editable format. While you wait, you can check it against
this list; it is what we look for first.

| Issue | Why it matters | What we do |
|---|---|---|
| One-way in their favour while we will also share | Our information is unprotected | Make it mutual or switch to our template |
| Marking-only definition | Demos and conversations fall outside it | Apply the fallback above |
| Residuals clause | Undoes the agreement | Delete, no fallback |
| Non-solicitation or non-compete | Restricts hiring or our business | Delete, or the 6-month fallback for non-solicitation |
| Exclusivity or standstill | A commercial commitment hidden in an NDA | General counsel only |
| Indemnity or liability cap | Out of place in an NDA | Delete |
| Perpetual term with no exit | We cannot end it | Our 2-year term and 3-year survival |
| Clauses on personal data | An NDA is the wrong instrument | Remove, and use a DPA instead |

## What never goes under an NDA

Some information should not leave Quillmoor at all, NDA or not:

- cardholder data of any kind, PANs included, and anything else classified Restricted;
- personal data of merchants, sellers or their customers: if a partner genuinely needs it,
  the right contract is a DPA, prepared with the DPO (see the [DPA playbook](dpa-playbook.md));
- passwords, API keys, tokens or other secrets: if one has been shared, follow the
  [leaked secret playbook](../security/leaked-secret.md) straight away;
- unannounced financial results or details of a fundraising, which only the CFO or the
  chief executive may disclose.

## After signature

Clausebook is the record. Do not keep signed NDAs only in your inbox. When you are told
that an NDA is about to expire, either let it lapse (the survival period still protects
what was shared) or raise a new self-serve request if the conversation continues.

If you suspect a counterparty has misused our information, write to
`legal@quillmoor.example` the same day with what you know. Do not contact the
counterparty about it first.

## FAQ

**The counterparty insists on its own NDA and it looks fine to me. Can I sign it?**
Not without a Legal review. Raise a Third-party NDA review in Clausebook; see
[Requesting a contract review](contract-requests.md) for how long that takes.

**Can I sign on paper?**
Yes, if the counterparty cannot sign electronically. Upload the scan of the fully signed
copy to the Clausebook request so that it is filed.

**Do office visitors need to sign an NDA?**
Ordinary visitors do not. If a visitor will see confidential material during a workshop,
treat it as any other disclosure and put an NDA in place beforehand. Registering visitors
is covered in [Visitors and deliveries](../workplace/visitors-and-deliveries.md).

**We already have an NDA with this company for a different project. Is it enough?**
Only if its purpose covers the new conversation. Most do not, so raise a new self-serve
request with the new purpose.

**The counterparty wants New York law. Is that a problem?**
It goes to Legal. We rarely refuse outright, but we need to look at the rest of the text
with that law in mind.
