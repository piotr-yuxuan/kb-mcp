---
title: "Playbook: leaked secret or API key"
---

# Playbook: leaked secret or API key

Owner: Security (`#team-security`). Maintainer: the security on-call of the week.
Last reviewed: 2026-10-07, after the SCN-7731 follow-ups were closed.

Use this playbook when a password, token, private key, connection string or API key
has been seen somewhere it should not be: a commit, a chat message, a ticket, a log
line, a screenshot, a public website. It covers our own secrets, which live in
Strongroom, and merchants' API keys, which live in `merchant-api`.

> [!IMPORTANT]
> Rotate in Strongroom first, then revoke the old value. A production secret must be
> rotated, and its old value revoked, within 1 hour of the finding.

## The short version

1. Tell Security: email security@quillmoor.example, or page `security-oncall` in Klaxon
   out of hours. Quote the scanner finding if there is one, such as `SCN-7731`.
2. Find out what the secret opens and who uses it today.
3. Rotate it in Strongroom, so that a new value exists and consumers pick it up.
4. Check that every consumer runs on the new value.
5. Revoke the old value.
6. Look for any use of the old value during the time it was exposed.
7. Only then clean up where it leaked.

The clock starts when anyone at Quillmoor first knows of the leak: the scanner's
timestamp, the time of the chat message, or the time a merchant told us.

## Why rotate before revoking

Revoking first feels safer and is usually worse. If you revoke the only valid value of
`card-auth`'s database password, `card-auth` stops authorising payments until someone
creates and distributes a new one, and you have caused the outage an attacker would
have wanted. Strongroom keeps two versions valid side by side during a rotation, so
the right order costs a few minutes and no downtime:

```text
time ->      t0 leak found     t1 rotate          t2 consumers moved     t3 revoke
version 41   valid ----------- valid ------------ valid ---------------- revoked
version 42                     valid ------------ valid ---------------- valid
```

There is one exception. If the old value is being used by someone else right now, the
incident lead may order an immediate revocation and accept the outage. That decision
is recorded in the incident with the lead's name; if merchants feel it, Site Reliability
opens a production incident alongside ours.

## Deadlines

| Where the secret works | Rotate and revoke within | Who does it |
|---|---|---|
| Production, including the card data environment | 1 hour of the finding | The owning team, with the security on-call |
| Staging (`staging-eu`) and other shared non-production | 1 business day | The owning team |
| A developer's local environment only | Before the branch is merged | The author |
| A supplier's system (our settlement bank, our email provider) | As fast as the supplier allows; the incident lead decides on interim controls | Security, with the team that owns the integration |

If you cannot meet the 1-hour deadline for a production secret, say so in the incident
channel before the hour is up, with the reason and the time you expect to finish. The
incident lead decides what to do meanwhile: tighter network rules, a kill switch on the
feature that uses the secret, or a controlled revocation.

## Step by step

### 1. Report and open the incident

The security on-call acknowledges, opens a private channel `#inc-sec-` plus a codename,
and grades the leak on the scale in the [security incident response plan](incident-response-plan.md).
Most leaks found quickly by the scanner, with no sign of use, are S3. A leak with any
sign of use by an unknown party is at least S2; one through which data was read is S1.

### 2. Understand the secret

Answer four questions in the channel before touching anything:

- **What does it open?** The Strongroom path tells you the service and environment.
- **Who reads it today?** Strongroom lists every consumer.
- **Where was it exposed, and to whom?** An internal repository, a public one, a chat
  channel of fifty people and a direct message are four different risks.
- **For how long?** From the first exposure to now. This is the window you will search
  for misuse in step 6.

```bash
# Every read of the secret over the last three days, with the caller's identity
strongroom audit prod/ledger/replica-readonly --since 72h

# The workloads that currently hold a lease on it
strongroom consumers prod/ledger/replica-readonly
```

### 3. Rotate in Strongroom

For secrets Strongroom manages itself, which covers our PostgreSQL credentials and
service-to-service tokens, one command creates the new version and sets it on the
target:

```bash
strongroom rotate prod/ledger/replica-readonly --reason "SCN-7731"
```

For a credential issued by a supplier, create the new value in the supplier's console
first, then store it as a new version:

```bash
strongroom put prod/notify/email-provider-api-key --from-stdin --reason "leak in chat"
```

Production database credentials are already rotated every 30 days by the schedule
added under ENG-14, which limits how long a leaked one stays useful. Thirty days is
still far too long to wait: rotate now.

### 4. Move the consumers

Workloads that use the Strongroom sidecar pick up the new version within 90 seconds.
Workloads that read secrets only at start need a redeploy of their current release:

```bash
shipwright deploy settlement-batcher --release current
```

Confirm with `strongroom consumers` that no workload still holds the old version. Ask
the owning team to check Lantern for authentication errors before you move on.

### 5. Revoke the old value

```bash
strongroom revoke prod/ledger/replica-readonly --version 41 --reason "SCN-7731"
```

For a supplier's credential, revoke it in the supplier's console as well, and keep a
screenshot of the confirmation in the incident record, not in chat.

### 6. Look for misuse

Search the exposure window for any use of the old value that is not one of the known
consumers:

- Strongroom's audit log, for reads by unexpected identities;
- the target's own logs: PostgreSQL connection logs, the supplier's access log, the
  identity provider for personal tokens;
- network logs, for connections from addresses outside our ranges.

If you find any, regrade the incident and follow the
[security incident response plan](incident-response-plan.md) from containment onwards.

### 7. Clean up the exposure

Remove the secret from the file, the ticket or the message, and note what you removed.
Do not rewrite shared git history unless Security asks: a force-push does not reach the
clones and caches that already hold the commit, and it makes the investigation harder.
A rotated and revoked secret left in history is harmless; an unrotated one removed from
history is still a live secret.

## Merchant API keys

Merchants' API keys are the merchants' credentials, not ours, so they are not rotated
in Strongroom. They are revoked through the `merchant-api` admin console, which needs
the `merchant-api-admin` role.

The principle is the same: new key first, then revoke the old one.

1. Merchant Support contacts the merchant and asks them to create a new key in
   Merchant Hub and deploy it. Both keys work in the meantime.
2. In the `merchant-api` admin console, open the merchant, then **API keys**. Check the
   old key's last use and source addresses.
3. When the old key has not been used by the merchant's own systems for 15 minutes,
   select it and choose **Revoke**. Give the Harbour ticket or the `SCN-` finding as the
   reason.
4. Record the revocation in the Harbour ticket so that support can answer follow-up
   questions.

If the leaked key is being used by someone other than the merchant, revoke it at once
in the admin console and call the merchant straight after: their integration stops
until they deploy a new key, and they need to hear that from us first. Merchant Support
handles the call using [the support escalation playbook](../support/escalation.md).

A merchant's key pasted into a Harbour ticket or an email to us also counts as leaked.
Ask the merchant to replace it, and redact the ticket.

## The secret scanner

The secret scanner checks every push to every repository, every CI log and, each night,
the full history of every repository. Each finding gets an `SCN-` number, is posted to
`#team-security` and is emailed to the commit's author:

```text
SCN-7731  severity=high  rule=postgres-connection-string
repo=data-pipelines  branch=feature/ledger-extract
file=dags/ledger_extract/config.yaml  line=14
status=open  notified=author,#team-security
```

The security on-call triages each finding as a real secret, a test fixture or a false
positive. Only Security can close a finding as a false positive or add an allowlist
entry, and every allowlist entry names the file and the reason. The author of the
commit never closes their own finding.

Run the scanner's pre-commit hook locally to catch mistakes before they reach the
remote; [using Strongroom](strongroom-how-to.md) explains how to read secrets at run
time so that they never need to be in a file.

## Worked example: SCN-7731

On 2026-08-26, an engineer working on a ledger extract for the warehouse pasted the
production read-only replica credential for `ledger` into a Conveyor DAG's
configuration and pushed the branch.

| Time (UTC) | What happened |
|---|---|
| 10:42 | The scanner raised `SCN-7731` on push and notified the author and `#team-security` |
| 10:44 | The security on-call acknowledged and opened `#inc-sec-wren`; graded S3, pending checks |
| 10:51 | `strongroom audit` showed reads only by Conveyor workers; PostgreSQL logs showed no connections from unknown addresses |
| 10:58 | `strongroom rotate`; version 42 created |
| 11:09 | Data Platform confirmed Conveyor workers on version 42 |
| 11:21 | Version 41 revoked |
| 11:30 | The branch was fixed to read the credential from Strongroom; history left as it was |

Revocation came 39 minutes after the finding, inside the 1-hour deadline. Follow-ups:
the Conveyor DAG template now reads credentials from Strongroom only, and the scanner's
pre-commit hook is part of the data repositories' default configuration.

## Edge cases

- **A public leak.** A secret on a public website or public repository is harvested
  within minutes. Assume it is in use until the logs prove otherwise.
- **A secret in logs.** Ask Platform to purge the lines from the log store, and fix the
  code that logged it; see the [secure code review checklist](secure-code-review.md).
- **A leaver's personal tokens.** Leavers' accounts are disabled by the access process,
  but tokens they created for services must be rotated by the owning team.
- **Weekend or night.** The 1-hour deadline still applies to production. Page the
  owning team's on-call through Klaxon; the security on-call does not wait for
  business hours.
- **You leaked it.** Say so at once. Nobody is disciplined for reporting their own
  mistake promptly; hiding one is a different matter.

## Related pages

- [Security incident response plan](incident-response-plan.md)
- [Using Strongroom](strongroom-how-to.md)
- [ADR-020: Strongroom as the only secrets store](../architecture/adr-020-strongroom.md)
