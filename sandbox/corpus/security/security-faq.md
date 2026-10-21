---
title: "Security FAQ"
---

# Security FAQ

Short answers to the questions `#team-security` hears most often, with a link to the
page that holds the full answer. Maintained by the Security team; last reviewed on
2026-10-14. If your question is not here, ask in `#team-security`, or email
security@quillmoor.example if it is sensitive.

## Reporting

### How do I report a security problem?

Email security@quillmoor.example. Out of hours, or if it cannot wait, page the
`security-oncall` rota in Klaxon. Do not describe the problem in a public channel. The
[security incident response plan](incident-response-plan.md) explains what happens next.

### Is a security incident the same thing as a SEV?

No. Security incidents are graded S1 to S4 by the SIRT, on the scale in the
[security incident response plan](incident-response-plan.md). Production incidents use
SEV1 to SEV4, defined in [production incident management](../incidents/incident-management.md).
The two scales measure different things and are never converted into each other. An
idea on the [product discovery board](../product/discovery-process.md) proposes a single
scale; until something is decided, keep them apart.

### I think I have received a phishing email.

Use the "Report phish" button in your email client, or forward the message as an
attachment to phish@quillmoor.example. Do not forward it to colleagues to ask their
opinion. See the [phishing playbook](phishing.md).

### I clicked a link and typed my password.

Report it straight away and say that you entered your password. Reset your password
from a device you trust. Security will revoke your sessions, so expect to be signed out
everywhere. Nobody will blame you; the faster you tell us, the smaller the problem.

### A researcher has emailed me about a vulnerability in our product.

Forward it to security@quillmoor.example and do not reply. Security answers every
report, but we do not run a paid reward scheme, and only Security should say so.

## Secrets and access

### I committed a password or pasted a token in chat.

Tell Security now. Production secrets must be rotated and the old value revoked within
1 hour, so minutes matter. Do not just delete the message or force-push: follow the
[leaked secret playbook](leaked-secret.md).

### Where should I keep a password my team shares for a supplier's website?

In Strongroom, under a `team/` path. [Using Strongroom](strongroom-how-to.md) shows how.
Never in a document, a spreadsheet, a ticket or a chat message.

### How do I get production access?

Ask your manager, then request it through the identity provider's access request form.
The system owner approves it after your manager. Production access is never part of a
new joiner's starting profile; [quarterly access reviews](access-reviews.md) describes
how access is granted and taken away.

### Why am I being asked to certify my team's access?

Because every manager does so four times a year, within 10 business days of the review
opening. It takes most managers twenty minutes. The
[quarterly access reviews](access-reviews.md) page has the details and some advice on
the decisions.

### I am an administrator. Why do I need a hardware security key?

Because a key will not sign in to a look-alike website, which makes administrators'
accounts far harder to phish. Administrators sign in with keys only; see the
[password and MFA standard](password-and-mfa.md).

## Devices and software

### I have lost my laptop, my phone or my security key.

Email security@quillmoor.example at once, whatever the hour, then tell your manager.
The [laptop security baseline](laptop-baseline.md) explains why a lost laptop is
usually not a disaster, and the [password and MFA standard](password-and-mfa.md) what
happens with a lost key.

### Can I work on my personal laptop?

No. Your own phone can hold work email and chat with the company's device management
profile, but nothing else.

### Why can I not install the tool I need?

Laptops have no administrator rights by default, and software comes from the company
catalogue. If the tool is not there, ask for it; if it is new to Quillmoor, it needs a
[vendor security review](vendor-security-review.md) first.

### I am travelling abroad for work.

Within the UK and the EU, nothing changes. Elsewhere, tell Security 10 business days
ahead. [Travelling with company devices](travel-with-devices.md) has the rest.

## Data

### Can I send this document to a merchant or a supplier?

It depends on its level. Public and Internal information can be shared with a business
reason; Confidential information only under a contract or an NDA and never as an email
attachment; Restricted information never, without written approval from Legal or the
DPO. See [data classification](data-classification.md).

### A merchant sent us a full card number in a support ticket.

Do not copy it, quote it or forward it. Tell Security, who will have it redacted.
Cardholder data is Restricted wherever it turns up.

## Engineering

### How quickly must we fix a vulnerability?

It depends on its severity, from 7 days for a critical one. The
[vulnerability management SLAs](vulnerability-slas.md) give every deadline and explain
how to ask for an exception.

### What should I check when reviewing a change that touches money or personal data?

Use the [secure code review checklist](secure-code-review.md) alongside the usual code
review guidelines, and add the `security-review` label when the checklist says so.

### Can I run a security scanner against our services?

Only against your own service in staging, and only with tools from the company
catalogue. Scanning production, or another team's service, needs Security's written
approval beforehand, so that the SIRT does not mistake you for an attacker.

### When was the last penetration test?

In March 2026, with a retest in June. The [2026 summary](pen-test-2026.md) lists the
findings and what we changed.
