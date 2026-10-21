---
title: "DPA playbook"
---

> [!NOTE]
> Owned by Beatrix Sallow, data protection officer. Questions to `privacy@quillmoor.example`.
> Last reviewed 2026-10-06, after the annual refresh of the sub-processor list.

This playbook is for anyone who negotiates, signs or operates contracts that involve
personal data: sales and account managers, procurement, Merchant Support leads and the
engineers who answer the technical questions in a merchant's privacy questionnaire. It
explains our positions on data protection terms, how we handle access requests and
breaches under those terms, and how the sub-processor list is kept.

## Terms used on this page

| Term | Meaning at Quillmoor |
|---|---|
| Data processing agreement (DPA) | The contract, or contract schedule, that sets out how a processor handles personal data on behalf of a controller, as GDPR Article 28 requires. Ours is template `TPL-DPA-MERCHANT`, and it forms part of every merchant's MSA. |
| Data subject access request (DSAR) | A request by an individual to see the personal data we hold about them, and to learn how and why we use it. |
| Standard contractual clauses (SCCs) | The model clauses approved for transfers of personal data to countries without an adequacy decision, used with the UK addendum for transfers from the UK. |
| Data protection officer (DPO) | The person who advises Quillmoor on data protection, monitors compliance and is our contact for the supervisory authority. At Quillmoor this is Beatrix Sallow. |

Other pages use these acronyms without spelling them out and link here.

## Who we are in each relationship

Whether we are a controller or a processor decides which terms we can accept. Most
disputes in a negotiation come from a merchant assuming we are its processor for
everything. We are not.

| Activity | Our role | Why |
|---|---|---|
| Processing payments and payouts on the merchant's instructions | Processor | We act for the merchant and only as it instructs |
| Merchant Hub accounts for the merchant's staff | Controller | We decide how logins and permissions work |
| KYC checks on merchants and their sellers | Controller | The law requires us to do them for our own purposes |
| Fraud scoring by `risk-scorer` | Independent controller | We use the results to protect our own network as well as the merchant |
| Reporting to the card schemes, our settlement bank and regulators | Independent controller | Our own legal and scheme obligations |
| Service emails and webhooks sent by `notify` | Processor | Sent on the merchant's behalf, with the merchant's content |

Our DPA covers the processor activities only. If a merchant's paper tries to bring
fraud scoring or KYC under its instructions, decline: we cannot let one merchant
instruct us on data we need to keep the whole network safe.

## Which DPA to use

- **Merchants:** `TPL-DPA-MERCHANT`, attached to the MSA. Merchants should accept it as it
  stands; the positions below say where we can move.
- **Merchants' own DPAs:** large merchants sometimes send their own. We review them only for
  merchants on the strategic list. Everyone else gets ours.
- **Suppliers that process personal data for us:** `TPL-DPA-SUPPLIER`, where we are the
  controller. It is stricter than the merchant template, by design. The supplier must
  also pass the [vendor security review](../security/vendor-security-review.md) before we
  sign.

Raise all DPA work in Clausebook as a **Data protection** request. The DPO is added as a
reviewer automatically.

## Clause positions

### Instructions

We process personal data only on the merchant's documented instructions, which are the
MSA, the DPA and the merchant's use of the services. Merchants may not add instructions by
email. If a merchant needs something unusual, it is a change to the services, not to the
DPA.

### Security measures

Annex 2 describes our technical and organisational measures at a level we can keep true
as our systems change. Do not paste internal security standards into it, and do not agree
to "comply with the merchant's security policy". The fallback is to answer the merchant's
security questionnaire, with Security's help, and attach our answers as information, not
as obligations.

### Sub-processors

The merchant gives a general authorisation for the sub-processors on our list. We give
**30 days' notice** of a new sub-processor, and during that period the merchant may
object on reasonable data protection grounds. If we cannot address the objection, the
merchant's remedy is to end the affected service without penalty.

Never agree to obtain the merchant's specific prior consent for each new sub-processor. We
have thousands of merchants; one objection could freeze a change for all of them.

### Personal data breaches

By contract, we tell affected merchants of a personal data breach **within 48 hours** of
becoming aware of it.

> Quillmoor shall notify the Merchant without undue delay, and in any event within 48 hours
> of becoming aware, of any Personal Data Breach affecting Merchant Personal Data, and
> shall provide the information reasonably available to it to allow the Merchant to meet
> its own obligations.

Merchants regularly ask for 24 hours. The answer is no: 48 hours is the shortest period
we can meet reliably while the facts are still being established. We may add "without
undue delay", as above, and we may commit to send updates as we learn more. Never commit
to a number of hours shorter than 48, and never let a merchant's paper override this
clause.

How a breach is triaged and who decides whether to notify the supervisory authority are
set out in the [security incident response plan](../security/incident-response-plan.md).
That plan is the authority on timings towards the supervisory authority; this playbook
covers our contractual duty to merchants.

### Assistance with requests from individuals

As a processor we help the merchant answer requests from its own customers. If such a
request reaches us, we pass it to the merchant within 5 business days and do not answer
it ourselves. Merchants may ask for 2 business days; we can agree to 3.

### Audits

We meet audit rights with our certificates, reports and questionnaire answers first. The
fallback is one remote audit a year, on 30 days' notice, at the merchant's cost, which
matches the [MSA clause guide](msa-clause-guide.md).

### Return and deletion at the end of the contract

At the end of the contract we delete merchant personal data, except where the law requires
us to keep it. Payment records are kept for legal and scheme reasons; the periods are in
the [data retention schedule](../data/retention-schedule.md). Do not put retention periods
in the DPA itself: they change, and the schedule is the source.

### International transfers

Merchant personal data is hosted in the UK and the European Economic Area. Where a
sub-processor sits outside both and the destination has no adequacy decision, we rely on
the SCCs, with the UK addendum for UK data, and we keep a transfer risk assessment on
file. Merchants may ask to see the assessment; the DPO decides what can be shared.

### Liability

Data protection claims are subject to the separate cap in the MSA. Do not accept a
different cap in the DPA: two caps in one contract invite an argument over which applies.

## Positions at a glance

| Topic | Standard | Fallback | Never |
|---|---|---|---|
| Sub-processor changes | 30 days' notice and objection | Email notice to a named contact | Specific prior consent |
| Breach notice to merchants | Within 48 hours | Add "without undue delay" and updates | Fewer than 48 hours |
| Passing on individuals' requests | 5 business days | 3 business days | Answering for the merchant |
| Audits | Reports and certificates | One remote audit a year | Unlimited on-site audits |
| Security measures | Our Annex 2 | Questionnaire answers as information | The merchant's own policy |

## Answering a DSAR

When we are the controller, for example for Merchant Hub users or for KYC data, we answer
a DSAR **within one month** of receiving it. The month may be extended by two further
months when a request is complex or one of many from the same person, but the requester
must be told of the extension, with reasons, within the first month.

1. **Intake.** Requests reach us through Merchant Support, email or post. Support forwards
   them as described in [Forwarding data subject requests](../support/data-subject-requests.md);
   anything sent elsewhere should be forwarded to `privacy@quillmoor.example` the same day.
2. **Log and clock.** The privacy team logs the request in its request register, with the
   date of receipt. The month runs from the day we received it, not from the day it
   reached the privacy team.
3. **Verify identity.** Ask only for what is needed to be sure of the person. Do not ask
   for a copy of an identity document when a confirmation from the merchant's registered
   email address will do.
4. **Decide our role.** If we are the merchant's processor for that data, pass the request
   to the merchant and tell the individual we have done so.
5. **Gather.** Data Platform finds the data through the tags described in
   [Tagging personal data columns](../data/personal-data-columns.md). Merchant Support
   exports the Harbour history; the privacy team collects anything else.
6. **Review.** Remove other people's personal data and anything legally privileged. The DPO
   signs off any refusal or partial answer.
7. **Respond** through a secure link, never as a plain email attachment.

If the person also asks us to erase their data, the warehouse side is handled as an
erasure request; follow [Erasure requests in the warehouse](../data/erasure-requests.md)
and do not improvise a deletion from a notebook.

## Notifying merchants of a breach

When the SIRT confirms that personal data held for merchants is involved, the DPO, the
general counsel and the head of customer support agree the list of affected merchants.
The 48-hour clock started when we became aware, so this is done in parallel with the
investigation, not after it.

The first notice is short and factual:

> We are writing to tell you about a personal data breach affecting data we process on your
> behalf. On [date] we became aware that [what happened, in one sentence]. The data
> involved is [categories]. We have [containment steps]. We will update you by [time] and
> as soon as we learn more. Your contact for this matter is
> `privacy@quillmoor.example`.

Do not speculate about cause or attribution in the first notice, and do not tell merchants
whether we have notified the supervisory authority until the DPO has confirmed it.

## The sub-processor list

The public list is at `https://quillmoor.example/legal/sub-processors`. It is the only list
we give merchants; do not send a copy as a spreadsheet, because copies go stale.

| Sub-processor category | Purpose | Location | Transfer safeguard |
|---|---|---|---|
| Cloud hosting provider | Hosting all production services and the data warehouse | UK and EEA | Not needed |
| Email delivery provider | Sending merchant emails from `notify` | EEA | Not needed |
| Identity verification provider | Document and liveness checks for KYC | UK | Not needed |
| Support telephony provider | Call handling for Merchant Support | EEA, with support staff in the US | SCCs and the UK addendum |
| Translation service | Translating support tickets for French-speaking merchants | EEA | Not needed |
| Backup storage provider | Encrypted off-site backups | UK | Not needed |

The list names each provider; the categories above are what this page needs. Each entry
records the provider, purpose, location, the transfer safeguard and the date it was added.

### Adding a sub-processor

1. The team that wants the supplier raises a **Data protection** request in Clausebook,
   with the vendor security review attached.
2. The DPO assesses the transfer and approves or refuses.
3. Legal signs `TPL-DPA-SUPPLIER` with the supplier, together with the main contract.
4. The privacy team updates the public list and emails the privacy contact of every
   merchant. The 30-day notice period starts on that day.
5. The supplier may not receive merchant personal data until the notice period ends with no
   objection left open.

Allow six to eight weeks from the first request to the first transfer of data. Start
early.

## Frequently asked questions

**A merchant wants our DPA signed separately from the MSA. Is that possible?**
Yes. It is the same text; Clausebook can issue it as a standalone document.

**A merchant asks us to name a data protection contact in the contract.**
Name the role and address, not a person: the DPO at `privacy@quillmoor.example`.

**Can we use merchant data to improve our fraud models?**
Yes, as an independent controller for fraud prevention, which the MSA explains. It is
not a processor activity, so it is not in the DPA.

**A supplier will only see personal data occasionally, during support calls. Do we need a
DPA?**
Yes. Occasional access is still processing. Use `TPL-DPA-SUPPLIER`.
