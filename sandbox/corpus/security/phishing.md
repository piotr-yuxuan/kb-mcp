---
title: "Playbook: reported phishing"
---

# Playbook: reported phishing

*Maintained by the Security team. Last reviewed on 2026-10-06 by Callum Ibe.*

This page has two halves. The first is for everyone at Quillmoor: how to recognise
phishing, how to report it, and what to do if you have already clicked. The second is
the playbook the security on-call follows once a report arrives.

## Part 1: for everyone

### What phishing looks like here

Attackers know we move money, so they aim at people who can approve, release or
redirect it, and at people who hold administrator rights. Messages we have seen this
year, with the details changed:

- "Your payslip is ready in Haven", linking to a copy of our sign-in page on a
  look-alike domain.
- An invoice from "our settlement bank" asking Finance to update the account details
  for the next payment run.
- A message to a payouts operator, signed with the name of the Payouts team lead,
  asking for an urgent manual payout "before the cut-off".
- A burst of MFA approval prompts at 23:00 that the person had not triggered, followed
  by a call from "IT support" asking them to approve the next one.
- A chat message from an external account that had joined a shared channel, with a
  link to "the updated incident runbook".

Things worth a second look:

1. Urgency or secrecy: "before 15:00", "do not tell anyone yet".
2. A sign-in page reached from a link rather than from your bookmark.
3. A request to change bank details, approve a payment or share a code.
4. A sender address that is close to ours but not quite, such as
   `quillmoor-payouts.example.com` or `qui11moor.example.com`.
5. An MFA prompt you did not start. Never approve it, not even to make it stop.

### How to report

- **In your email client:** select the message and press the "Report phish" button in
  the toolbar, on desktop and on the web. It sends the message with its full headers to
  Security and takes it out of your inbox.
- **On a phone, or if the button is missing:** forward the email *as an attachment* to
  phish@quillmoor.example. Forwarding it inline strips the headers we need.
- **A chat message, a text or a call:** take a screenshot or write down what was said,
  and email it to phish@quillmoor.example.

Please do not forward a suspicious message to colleagues to ask whether it is real, do
not reply to it, and do not press "unsubscribe".

The "Report phish" button asks one question: *did you click a link, open an attachment,
enter your password or approve a prompt?* Answer honestly. A "yes" pages the security
on-call; a "no" goes to the normal queue, and you will receive a verdict within one
business day. Many reports turn out to be genuine emails from suppliers. Report them
anyway; we would rather check.

### If you clicked, or entered your password

Act straight away, in this order:

1. **Tell us.** Report the message with the button and answer "yes", or email
   security@quillmoor.example with "I entered my password" in the subject. Out of
   hours, page `security-oncall` in Klaxon.
2. **Reset your password** from a device you trust, through the identity provider's
   self-service page. If you used the same password anywhere else, change it there too.
3. **Expect to be signed out everywhere.** Security revokes all your sessions; this is
   deliberate, not a fault.
4. **Say whether you approved a prompt or typed a code.** It changes what we look for.
5. **If you opened an attachment,** disconnect the laptop from the network (turn off
   Wi-Fi), leave it switched on, and do not try to clean it yourself.

Nobody is blamed for being phished. The people who report within ten minutes are the
reason most of our phishing incidents stay small.

### Simulations

Security sends simulated phishing emails four times a year. If you click one, you see a
short page explaining what gave it away. Results are reported to leadership by
department and never by name, and they are never used in performance reviews.

## Part 2: playbook for the security on-call

### Where reports arrive

Both the "Report phish" button and phish@quillmoor.example feed the phishing queue.
Reports answered "yes" also page the security on-call.

| Report | First look |
|---|---|
| Answered "yes" to the button's question, or "I entered my password" | Immediately, at all hours |
| Answered "no", during business hours | Within 1 business hour |
| Answered "no", out of hours | The next business morning |

### Step 1: give a verdict

| Verdict | Meaning | What happens |
|---|---|---|
| Legitimate | A genuine email | Release it to the reporter and thank them |
| Spam | Unwanted but harmless | Block the sender; close |
| Phishing, no interaction | Nobody clicked, entered anything or approved anything | Contain the campaign (step 2); log it; no incident is opened, unless the campaign targets administrators specifically, in which case open an S4 |
| Phishing, with interaction | At least one person clicked through to a form, entered credentials, approved a prompt or opened an attachment | Contain the campaign, open a security incident and grade it (step 3) |

Tell the reporter the verdict, even when it is "legitimate". People keep reporting when
reports get answers.

### Step 2: contain the campaign

One report usually means many recipients.

1. Search every mailbox, through our email provider's administration search, for the
   same sender, subject, links or attachment hash.
2. Move every copy to quarantine. Do not purge them: they are evidence, and the
   quarantine keeps them out of reach of staff.
3. Block the sender's address or domain at the email gateway, and the links at the web
   filter.
4. Pull the gateway's click log for those links. Everyone who clicked is now a person to
   contact, whether or not they reported anything.
5. If the email impersonated a supplier, tell the supplier's contact owner at
   Quillmoor, who warns the supplier through a known channel.

### Step 3: open and grade the incident

Phishing incidents are graded S3 by default. They are graded S2 when the person who
interacted is an administrator, which for this purpose means anyone with:

- production access to Kubernetes, Shipwright or the databases;
- administrator rights in the identity provider, email or chat;
- write access to production paths in Strongroom;
- the `merchant-api-admin` role or administrator rights in Harbour.

Administrators carry hardware security keys, as required by the
[password and MFA standard](password-and-mfa.md), and a key will not sign in to a
look-alike domain. We still grade them S2: an administrator's password may open systems
that sit outside the identity provider, and an attacker who reaches an administrator
rarely stops at one attempt.

From there, the [security incident response plan](incident-response-plan.md) applies.
If you find that the attacker signed in, the incident is an active compromise and at
least S2. If they read cardholder or personal data, it is S1, and the DPO must be told
at once.

### Step 4: credentials entered, so reset the password and revoke sessions

When credentials were entered, do both of these, every time:

- **Reset the password.** Force a reset in the identity provider. If the person cannot
  be reached within 15 minutes, set a random password and disable sign-in until they can
  be.
- **Revoke every session.** In the identity provider, revoke sessions and refresh tokens
  for the person, which signs them out of email, chat, Lantern, Harbour, Shipwright and
  every other application behind single sign-on. The Strongroom command-line tool keeps
  its own long-lived token, so revoke that one separately:

```bash
# Strongroom CLI tokens are not covered by the identity provider's revocation
strongroom sessions revoke --user "a.person@quillmoor.example"
```

Why both: a new password does nothing against an attacker who already holds a session
cookie, and revoked sessions do nothing against an attacker who knows the password.

Then check the account for anything the attacker may have left behind:

| Check | Where | Look for |
|---|---|---|
| MFA factors | Identity provider | A factor registered since the click; remove any the person does not recognise |
| Mailbox rules | Email administration | Forwarding to outside addresses, rules that delete or hide replies |
| Delegations | Email administration | Mailbox or calendar access granted to someone new |
| Application consents | Identity provider | Third-party applications granted access to mail or files since the click |
| Sign-in log | Identity provider | Sign-ins from new devices, countries or networks since the click |
| Chat | Chat administration | Messages sent by the person that they do not recognise |

If the person approved a prompt or typed a one-time code, assume the attacker
completed a sign-in, and look hard at the sign-in log.

### Step 5: an attachment was opened

Isolate the laptop through device management, which cuts it off from everything except
the security tooling. Ask the person to leave it switched on. Security collects it, or
for remote staff sends a courier with a replacement. See the
[laptop security baseline](laptop-baseline.md) for what the endpoint agent records.

### Step 6: money was asked for

If the message asked someone to change bank details, release a payout or pay an
invoice, tell the finance director straight away, and Payouts if a payout was involved.
Finance confirms any change of bank details by calling the supplier on a number taken
from our own records, never from the email. If a payment has already gone, Legal and
Finance take over the recovery; the security incident continues alongside.

## Phishing aimed at merchants

Attackers also pretend to be Quillmoor: copies of the Merchant Hub sign-in page, or
emails asking merchants to "confirm payout details". Merchants report these to Merchant
Support, who follow [merchants reporting fraud](../support/merchant-fraud-reports.md)
and send us the details.

Security then:

1. collects the look-alike domain, the sending infrastructure and samples;
2. asks the general counsel to request a takedown from the domain's registrar and host;
3. checks `merchant-api` and Merchant Hub sign-in logs for accounts accessed from the
   phishing infrastructure, and has Merchant Support contact those merchants;
4. agrees with the head of customer support whether a warning goes to all merchants.

A merchant account taken over this way is an incident in its own right, graded on the
same scale.

## Closing the report

For every report, record in the queue:

- the verdict;
- the number of recipients and of people who interacted;
- what was blocked and quarantined;
- the incident reference and grade, if one was opened.

The weekly security report summarises the queue: how many reports, how many were real
phishing, how fast we answered, and how many incidents were opened at each grade.

## Recent figures

| Calendar quarter | Reports | Real phishing | Incidents at S3 | Incidents at S2 | Median time from report to sessions revoked |
|---|---|---|---|---|---|
| Q1 2026 | 412 | 96 | 4 | 1 | 21 minutes |
| Q2 2026 | 388 | 81 | 3 | 0 | 17 minutes |
| Q3 2026 | 455 | 102 | 5 | 1 | 14 minutes |

The S2 in Q3 2026 was a production administrator who entered a password on a
look-alike Lantern page. The hardware security key blocked the sign-in; the password
was reset and sessions revoked 11 minutes after the report.

## Related pages

- [Security incident response plan](incident-response-plan.md)
- [Password and MFA standard](password-and-mfa.md)
- [Security FAQ](security-faq.md)
