---
title: "Security incident response plan"
---

# Security incident response plan

- **Owner:** Callum Ibe, head of security
- **Approved by:** Ottilie Marsh, chief technology officer
- **Last reviewed:** 2026-09-30
- **Review cycle:** every six months, and after every S1 or S2
- **Questions:** `#team-security`, or security@quillmoor.example for anything sensitive

## Purpose and scope

This plan sets out how Quillmoor detects, contains and recovers from security
incidents, who takes which decision, and when we must tell people outside the company.
It applies to every employee and contractor, and to every system we run or rely on:
production and staging, the card data environment, the warehouse, the corporate estate
(laptops, phones, email, chat, the identity provider) and the suppliers that process
data for us.

If you think something is wrong, report it now. Do not investigate on your own first,
and do not wait until you are sure. A false alarm costs the security on-call ten
minutes; a late report can cost us the 72-hour notification window described below.

## Reporting a suspected incident

| What you have seen | Where to report it |
|---|---|
| Anything that might be a security incident | Email security@quillmoor.example, or page the `security-oncall` rota in Klaxon out of hours |
| A suspicious email | The "Report phish" button; see the [phishing playbook](phishing.md) |
| A password, token or API key somewhere it should not be | Follow the [leaked secret playbook](leaked-secret.md) and email security@quillmoor.example |
| A lost or stolen laptop, phone or security key | security@quillmoor.example straight away, then your manager |
| A merchant telling us their account was misused | Merchant Support handles it first, through [merchants reporting fraud](../support/merchant-fraud-reports.md), and pages us when needed |

Keep the details out of public channels. `#team-security` is readable by every member
of staff, so write only "I have emailed security about something urgent" there, and
put the substance in the email or the page.

## The security incident response team

The security incident response team (SIRT) runs every security incident from the first
report to closure. It is small by design: a few people who can take decisions quickly,
with specialists called in when the incident needs them.

| Role | Who | Responsibilities |
|---|---|---|
| Incident lead | The security on-call for S3 and S4; a senior security engineer or the head of security for S1 and S2 | Grades the incident, decides on containment, approves closure. The only person who can downgrade an incident |
| First responder | The security on-call | Acknowledges the report, opens the incident record, starts triage |
| Scribe | Any member of the Security team not responding | Keeps the timeline in UTC, records every decision and who took it |
| Technical responders | Engineers from the owning team, Site Reliability or Platform | Carry out containment and recovery under the incident lead's direction |
| Data protection | Beatrix Sallow, DPO | Decides whether personal data is involved; owns every notification to the regulator and to individuals |
| Legal | Saoirse Lindqvist, general counsel | Contracts, merchants, the card schemes, the acquiring bank, law enforcement |
| People | Rhiannon Dace, head of people | Joins when a member of staff may be involved; nobody else interviews colleagues |
| Customer liaison | Femi Haldane, head of customer support | Prepares merchant contact once Legal has approved the wording |

For an S1, the incident lead also informs the chief technology officer and the chief
executive within the first hour.

## Severity levels

Security incidents have their own scale, S1 to S4, defined here and nowhere else. It
is separate from the production scale SEV1 to SEV4, described in
[production incident management](../incidents/incident-management.md), and from the
support ticket priorities P1 to P4 in
[ticket priorities and SLAs](../support/priorities-and-slas.md). Do not translate one
into another: an S2 is not "a SEV2", and an S1 may have no effect on production at all.

| Level | Definition | Typical examples | SIRT assembled | Leadership updates |
|---|---|---|---|---|
| S1 | Confirmed exposure of cardholder or personal data | PANs found outside the card data environment; a merchant contact list copied out of the warehouse; personal data sent to the wrong recipient in bulk | Within 30 minutes, at all hours | Every 2 hours |
| S2 | An active compromise, with no data exposure confirmed | An attacker holding a session on an administrator account; malware on a laptop with production access; a production secret used from an unknown address | Within 1 hour, at all hours | Every 4 hours |
| S3 | A contained event of low impact | A phished employee whose password was reset before it was used; a staging secret pushed to a repository and rotated | Next business day | Daily summary |
| S4 | Suspicious and unconfirmed | An odd sign-in pattern; a scanner alert awaiting triage; a researcher's report not yet reproduced | Triage within 2 business days | Weekly security report |

Grading rules:

1. When in doubt, grade higher. Downgrading later is cheap.
2. Confirmed exposure of data makes the incident an S1, whatever it was before.
3. Every change of grade is written in the timeline with its reason and the incident
   lead's name.
4. An S4 is either closed or regraded to S1, S2 or S3 within 5 business days.
5. Some playbooks set a starting grade. Phishing, for example, starts at S3, or S2 when
   the target is an administrator; see the [phishing playbook](phishing.md).

## Response phases

### 1. Triage

The first responder:

1. Acknowledges the report or the page, and tells the reporter that someone is on it.
2. Opens a restricted incident record and a private chat channel named
   `#inc-sec-` followed by a codename, for example `#inc-sec-heron`. The codename must
   not reveal the system, the merchant or the person concerned.
3. Writes down what is known, what is assumed and what is unknown.
4. Proposes a grade and, for S1 or S2, pages the incident lead.
5. Asks whether merchants feel any effect. If they do, Site Reliability declares a
   production incident with `/klaxon declare`, and the two run side by side (see
   "Working alongside a production incident" below).

### 2. Containment

Containment stops the harm from growing. The usual levers:

- disable an account or revoke its sessions in the identity provider;
- rotate a credential in Strongroom, following the [leaked secret playbook](leaked-secret.md);
- cordon a Kubernetes node or scale a compromised workload to zero, after a snapshot;
- block an address range at the edge;
- flip a Switchboard kill switch to stop a feature being abused, as described in
  [feature flags and kill switches](../release/feature-flags.md).

Two rules apply to every containment step. First, preserve evidence before you destroy
anything: snapshot a volume before you terminate a node, and export the logs before you
rebuild a service. Second, if a production incident is open, agree any step that
affects merchants with its IC before you take it.

### 3. Evidence

The scribe keeps a list of what was collected, by whom, when and from where. Sources we
almost always need:

| Source | Owner | Notes |
|---|---|---|
| Identity provider sign-in and audit logs | Security | Export the full window, not only the suspicious account |
| Kubernetes audit logs | Platform | Ask Platform to extend retention for the affected clusters at once |
| Strongroom access log | Security | Every read of a secret, with the caller's identity |
| Switchboard audit log | Platform | Every kill switch flip, added under ENG-8 |
| Application logs and traces | The owning team | Through Lantern; export rather than screenshot |
| Email and chat | Security, with Legal's approval | Only within the scope Legal approves |

Hash every evidence file before it leaves the host where it was collected, and record
the hashes in the incident record:

```bash
# Run on the host where the evidence was gathered
cd /var/tmp/evidence
sha256sum ./*.tar.gz | tee SHA256SUMS
# Copy SHA256SUMS into the incident record before uploading anything
```

Evidence goes to the SIRT evidence store, which is write-once and readable only by the
SIRT. Never attach evidence to a ticket, a chat message or an email.

A compromised laptop stays switched on. Disconnect it from the network, leave it
running and hand it to the Security team; switching it off loses what is in memory.

### 4. Eradication and recovery

- Remove the cause, not only the symptom: the persistence mechanism, the vulnerable
  dependency, the over-broad permission.
- Rebuild from known-good images rather than cleaning a host in place.
- Bring services back step by step, and watch each step in Lantern before the next.
- Keep heightened monitoring on the affected systems for 14 days after recovery.

### 5. Notification

Notification decisions are taken by named people only. Engineers never contact anyone
outside Quillmoor about a security incident.

#### The regulator

When personal data is involved, the regulator is told within 72 hours of awareness,
through the DPO. No one else contacts the regulator, whatever the circumstances.

Awareness is the moment the SIRT has a reasonable degree of certainty that a breach
affecting personal data has happened. In practice it is the moment the incident is
graded S1 for personal data, and the incident lead records that time in the timeline.
The clock does not wait for the investigation to finish: the DPO may send a first
notification with what we know and complete it in stages.

Tell the DPO as soon as personal data might be involved, not once it is certain. The
DPO will ask for:

- the nature of the incident and how it was discovered;
- the categories of data and of people affected, and rough numbers of each;
- the likely consequences for those people;
- the measures taken and planned, and a contact for follow-up questions.

#### Merchants

What we owe merchants after a breach is set by contract, in the DPA each merchant
signs. Follow the [DPA playbook](../legal/dpa-playbook.md) for the timing and content;
the general counsel approves every merchant notification, and Merchant Support sends it.

#### The card schemes and the acquiring bank

If cardholder data is involved, the general counsel informs the acquiring bank and the
card schemes as PCI DSS and our agreements require. Do not contact them directly, even
if you know someone there.

#### People affected

The DPO decides whether individuals must be told directly, and approves the wording.

#### The status page

Beacon is updated only when merchants feel an effect, and then through the IC and the
communications lead, as set out in [status page communications](../incidents/status-page.md).
A security cause is never named on Beacon without the general counsel's approval.

### 6. Closure and review

The incident lead closes an incident when it is contained, its cause removed, every
notification sent and the monitoring period over.

- **S1 and S2:** a PIR on the standard [template](../incidents/post-incident-review.md),
  with a restricted circulation list. Its actions are tracked like any other PIR
  action, with ticket visibility limited to the SIRT.
- **S3:** a short write-up in the incident record: cause, fix, follow-ups.
- **S4:** a closing note saying what was checked and why the incident was closed.

## Working alongside a production incident

Some incidents are both: a credential stuffing attack that slows `merchant-api`, or a
compromised dependency that forces a rollback. Then:

| Question | Who decides |
|---|---|
| Is merchant traffic protected, and when is service restored? | The IC of the production incident |
| What is contained, what evidence is kept, who is told outside the company? | The SIRT incident lead |
| What goes on Beacon? | The IC and the communications lead, with the general counsel when a security cause is involved |
| Who is paged? | Each side pages its own rota; the SIRT lead joins the production channel, the IC is invited to the private one |

The production channel must not hold details of the security investigation. Keep them
in `#inc-sec-` channels.

## Communication discipline

- Share on a need-to-know basis. Being in the SIRT channel is not permission to tell
  your team.
- Do not discuss an incident on calls with suppliers or merchants unless the incident
  lead has asked you to.
- If the attacker might be able to read our email or chat, for example after an
  identity provider compromise, the incident lead moves the SIRT to the out-of-band
  bridge and the phone tree held by the head of security.
- Never forward evidence to a personal address or device.

## Exercises

The SIRT runs a tabletop exercise every six months, with the DPO, Legal and Site
Reliability present. The last one, on 2026-06-24, followed a production database
credential used from an unknown address on a Saturday night. It showed that:

1. the DPO was not paged automatically for S1 incidents, and is now on the Klaxon
   escalation path for the `security-oncall` rota;
2. responders hesitated over who could flip a kill switch, which is now written in the
   containment section above;
3. evidence collection was slowed by short Kubernetes audit log retention, which
   Platform has since extended for production clusters.

Earlier incidents shaped other controls that this plan relies on: hardware security
keys for every production administrator (ENG-16), rotation of production database
credentials in Strongroom (ENG-14) and automatic removal of leavers' access (ENG-15).

## Contacts

| Role | Name | How to reach |
|---|---|---|
| Head of security | Callum Ibe | Klaxon, `security-oncall` escalation |
| Security on-call | Weekly rota | Klaxon rota `security-oncall`; security@quillmoor.example |
| DPO | Beatrix Sallow | privacy@quillmoor.example; Klaxon for S1 |
| General counsel | Saoirse Lindqvist | legal@quillmoor.example; phone tree |
| Site reliability lead | Lukas Brennand | Klaxon |
| Head of people | Rhiannon Dace | people@quillmoor.example |

## Related pages

- [Playbook: leaked secret or API key](leaked-secret.md)
- [Playbook: reported phishing](phishing.md)
- [DPA playbook](../legal/dpa-playbook.md)
- [Production incident management](../incidents/incident-management.md)
- [Data classification](data-classification.md)
