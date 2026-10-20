---
title: "Laptop security baseline"
---

# Laptop security baseline

Owner: Security, with the Workplace team for hardware. Last reviewed: 2026-06-02.

Every Quillmoor laptop meets this baseline from the day it is handed over, and device
management checks it every hour. You should not need to change anything yourself; this
page is here so that you know what is set and why.

## The baseline

| Control | Setting | Enforced by |
|---|---|---|
| Disk encryption | Full-disk encryption on, recovery key held by device management | Device management; a laptop without it cannot reach the identity provider |
| Screen lock | Locks after 5 minutes without input, and needs your password or key to unlock | Device management profile |
| Operating system updates | Critical security updates within 7 days, all others within 14 | Device management; you get reminders, then a forced restart |
| Endpoint agent | Installed, running, reporting | Device management; checked hourly |
| Firewall | On, blocking incoming connections | Device management profile |
| Administrator rights | None by default | Temporary elevation on request, for 30 minutes at a time |
| Software | From the company catalogue | Anything else needs a [vendor security review](vendor-security-review.md) |
| Browser | The managed browser profile for work, with the company extensions | Device management |

Lock your screen yourself whenever you step away, even in the office. The 5-minute
lock is a safety net, not a habit to rely on.

## What may live on the laptop

Work belongs in company services, not on the disk. In particular:

- no Restricted data on the laptop, ever; that includes cardholder data and exports of
  personal data (see [data classification](data-classification.md));
- no secrets in files: read them from Strongroom when you need them;
- no copies of production databases, even "just for a test". Use seed data and the
  staging environments.

If your laptop is lost tomorrow, the only thing you should lose is what you had not
yet pushed.

## When a laptop falls out of compliance

Device management marks a laptop non-compliant when any control above fails. You get an
email and a notification on the laptop. After a 3-day grace period, the identity
provider refuses sign-ins from that laptop until it is fixed. Laptops with disk
encryption off are blocked at once, with no grace period.

If you cannot fix it yourself, ask in `#team-security` with your laptop's asset tag,
not its serial number.

## Lost, stolen or damaged

Report it to security@quillmoor.example as soon as you notice, at any hour, and then to
your manager. Security locks the laptop and, if it does not come back, wipes it
remotely. Because the disk is encrypted and the screen locks, a lost laptop usually
stays a low-severity incident; we still treat every report as urgent. Report a theft
to the police as well, and send Security the crime reference.

Travelling? Read [travelling with company devices](travel-with-devices.md) before you
go.

## Personal devices

Your own phone may hold work email and chat if you install the company's device
management app profile, which can wipe work data without touching the rest of the
phone. Personal laptops and tablets may not be used for work, and no personal device
may reach production, Strongroom or the warehouse.
