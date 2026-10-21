---
title: "Quarterly access reviews"
---

# Quarterly access reviews

| Owner | Partner | Last reviewed | Questions |
|---|---|---|---|
| Callum Ibe, head of security | Rhiannon Dace, head of people | 2026-10-19 | `#team-security` |

Access drifts. People change teams, projects end, contractors finish, and the
permission someone needed for one incident two years ago is still there. We keep
access right with two controls that work together:

- the **JML process**, which changes access at the moment someone's situation changes;
- the **quarterly access review**, which catches whatever the JML process missed.

PCI DSS requires both for the card data environment. We apply them to every system that
holds Internal data or above, as defined in [data classification](data-classification.md).

## The JML process

JML stands for joiners, movers and leavers: the three moments when a person's access
must change. Haven is the source of truth for all three. When People record a start
date, a change of team or a leaving date in Haven, the identity provider acts on it.

### Joiners

- The identity provider account is created 5 business days before the start date,
  disabled until the first morning.
- Access is granted by **role profile**: a set of groups agreed by each team lead for
  each role, such as "Payouts engineer" or "Support agent, France". Profiles give
  chat channels, repositories, staging and the everyday tools.
- Profiles never include production access. A new engineer requests it once their
  manager agrees they are ready, through the identity provider's access request form,
  approved by the manager and then by the system owner.
- Access to the card data environment also requires the annual secure handling
  training to be completed and recorded in Haven.

What the first two weeks look like for the joiner is on
[new joiner onboarding](../people/onboarding.md).

### Movers

- A change of team in Haven applies the new role profile on the effective date.
- The old team's access is kept for a 30-day overlap, so that work can be handed over,
  and is then removed automatically unless the new manager asks to keep a specific
  entitlement, with a reason.
- A move into or out of a privileged role (any role listed under "Privileged access"
  below) triggers an immediate review of that person's access by Security, without
  waiting for the quarter.

### Leavers

Leavers lose access within 24 hours. The clock starts at the end of the person's last
working day as recorded in Haven.

Since ENG-15 was completed in March 2026, removal is automatic for every system behind
the identity provider. At the end of the last working day, the identity provider:

1. disables the account and revokes every session and refresh token;
2. removes the account from every group, which removes access to Kubernetes, Shipwright,
   Lantern, the warehouse, Harbour and chat;
3. calls Strongroom to revoke the person's tokens;
4. removes the `merchant-api-admin` role and Switchboard rights;
5. opens a ticket for each system outside the identity provider that the person had an
   account on, assigned to the system's owner, due within the same 24 hours.

Edge cases:

| Situation | What happens | Deadline |
|---|---|---|
| Immediate departure, at People's request | People call the security on-call, who disables the account by hand | Within 1 hour, at any time |
| Contractor | An end date is mandatory when the account is created; access expires on it automatically | End of the end date |
| Leaving date moved earlier | People update Haven; the automation follows the new date | 24 hours from the new date |
| Garden leave | Access removed at the start of garden leave, not at the end of employment | 24 hours from the start |
| Leaver who owned service accounts or tokens | The manager reassigns ownership before the last day; Security chases what is left | Before the last day |

What a leaver needs to do on their side is on [leaving Quillmoor](../people/leaving.md).

## The quarterly review

### Calendar

Reviews run four times a year, in January, April, July and October. Each opens on the
first working Monday of the month.

| Stage | Who | Deadline |
|---|---|---|
| Campaign prepared and sent | Security | The opening Monday |
| Managers certify their reports' access | Every people manager | Within 10 business days of opening |
| System owners certify privileged and service accounts | System owners | Within 10 business days of opening |
| Revocations carried out | System owners | Within 5 business days of the certification deadline |
| Sign-off | Head of security | Once revocations are confirmed |

### In scope

| System | What is reviewed | Second reviewer |
|---|---|---|
| Identity provider | Every group membership | None |
| Production Kubernetes clusters | Write access to each namespace | Platform (Bram Oyelaran) |
| Shipwright | Rights to deploy and roll back in production | Platform |
| Strongroom | Read and write access to production paths | Security |
| Card data environment | Every account, human or service | Payments Core (Nadia Ferreira) |
| Warehouse | Access to `marts` and to tables tagged as personal data | Data Platform (Tomasz Wilde) |
| Switchboard | The right to flip kill switches in production | Platform |
| `merchant-api` admin console | The `merchant-api-admin` role | Merchant Experience |
| Harbour | Administrator rights | Femi Haldane |
| Haven | Administrator rights and payroll document access | Rhiannon Dace |
| Tally | Approver rights | Arjun Pelletier |

### Privileged access

Privileged entitlements get stricter handling: they cannot be certified with "keep
all", the manager must give a reason for each one, and the second reviewer in the table
above must agree. An entitlement counts as privileged when it allows any of the
following in production: changing code or configuration, reading secrets, reading
cardholder data, reading personal data in bulk, or granting access to others.

Every holder of a privileged entitlement must also have hardware security keys
enrolled, as the [password and MFA standard](password-and-mfa.md) requires. The review
flags anyone who does not.

### How to certify, for managers

You receive an email from the access review tool, built under ENG-15, on the opening
Monday. For each person who reports to you, it lists every entitlement with its system,
the date it was granted and the date it was last used.

1. Open the review from the email or from the identity provider's portal.
2. For each entitlement, choose **Keep**, **Revoke** or **Not sure**.
3. Give a reason for every privileged entitlement you keep.
4. Submit before the deadline shown at the top of the page.

Some guidance:

- An entitlement unused for 90 days is pre-selected as **Revoke**. Change it only if
  you know why the person will need it soon.
- If you do not know what an entitlement is, choose **Not sure**. It goes to the
  system owner, who decides. Do not keep it to be safe.
- You cannot certify your own access. Your manager does that.
- Revoking something by mistake is cheap: the person requests it again. Keeping
  something by mistake is what auditors find.

### If certification is late

| Business day after opening | What happens |
|---|---|
| 5 | Reminder to managers who have not started |
| 8 | Reminder copied to the manager's head of department |
| 10 | Deadline. Security lists overdue managers to the head of security and the chief technology officer |
| 13 | Privileged entitlements still uncertified are suspended until they are certified |

Suspension is rare and deliberate. Three entitlements were suspended in July 2026; all
were certified within a day.

### Evidence

Security keeps, for each review: the campaign export, every decision with the name of
the person who took it and the time, and each revocation with its confirmation. This is
the evidence auditors ask for under PCI DSS. Do not keep your own copies.

## Service accounts

Service accounts are reviewed by their system owners, not by managers. Each one must
have:

- a named owner who is a current employee;
- a purpose recorded in the identity provider;
- credentials held in Strongroom only, never in a file or a repository;
- no interactive sign-in.

A service account with no owner is disabled at the end of the review in which it is
found. If something breaks, the team that notices becomes its owner.

## Break-glass accounts

Each critical system has two break-glass accounts for use when the identity provider is
unavailable. Their credentials are sealed in Strongroom, and reading them pages the
security on-call. Security reviews every use within 1 business day, and the credentials
are rotated after each use. Break-glass accounts are listed in every quarterly review
and certified by the head of security.

## Results

### July 2026

The review opened on Monday 6 July 2026 and closed for certification on Friday 17 July
2026.

| Measure | Value |
|---|---|
| Managers asked to certify | 58 |
| Entitlements reviewed | 6,912 |
| Entitlements revoked | 341 (4.9%) |
| Managers who certified on time | 53 (91%) |
| Privileged entitlements suspended on day 13 | 3 |
| Service accounts disabled for lack of an owner | 7 |

Findings: two leavers still held accounts on a supplier portal outside the identity
provider, because the portal had been added after their profiles were set up. Both
accounts were removed, and the portal now sits behind the identity provider, so
leavers' access to it is removed automatically.

### October 2026

The review opened on Monday 5 October 2026, and certification was due on Friday 16
October 2026. On 19 October, 96% of entitlements were certified; three managers were
overdue and had been escalated to their heads of department. System owners are working
through the revocations.

## Frequently asked questions

**Someone in my team is going on long leave. Do they keep their access?**
Yes for everyday access. Privileged entitlements are suspended after 3 months of
absence and restored on request when the person returns.

**A contractor's engagement has been extended.**
Ask People to update the end date in Haven before the old one passes, or the account
expires on schedule.

**I found someone with access they should not have, outside a review.**
Remove it, or ask the system owner to, and tell Security. If you think the access was
used to do something it should not have, report it as an incident under the
[security incident response plan](incident-response-plan.md).

**Why every quarter, and not once a year?**
Because the card data environment requires it, and because a quarterly review is small
enough to do properly. A yearly one becomes a click-through.
