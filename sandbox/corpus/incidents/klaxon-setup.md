---
title: "Setting up Klaxon on your phone"
---

# Setting up Klaxon on your phone

Before your first shift on any rota, set up Klaxon on your phone and prove that a page
can wake you. It takes about ten minutes. Most missed pages we review turn out to be a
phone setting, not a person, so please do all of it, including the test.

Written by Site Reliability (`#team-sre`). Last reviewed 2026-06-30.

## 1. Install and sign in

1. Install the Klaxon app from the company app catalogue on your phone. Personal
   phones are fine; a company phone is available if you prefer to keep work off your
   own, so ask your team lead.
2. Sign in with your company account through single sign-on. Klaxon will not accept a
   separate password.
3. Allow notifications when asked. Then allow the app to override silent mode and
   do-not-disturb. On some phones this is called "critical alerts", on others
   "override do not disturb" or "priority notifications". Without it, a page at 03:00
   arrives silently.

## 2. Set your notification rules

In the app, open **Profile, Notification rules**. The defaults we recommend for every
rota:

| Step | When | How |
|---|---|---|
| 1 | Immediately | Push notification, with the loud "klaxon" sound |
| 2 | After 1 minute unacknowledged | Text message |
| 3 | After 3 minutes unacknowledged | Phone call, repeated once |

Klaxon escalates to your secondary after 5 minutes for a SEV1 and 15 for a SEV2, as
set out in the [on-call policy](on-call.md). The rules above make sure your own phone
has tried three ways before that happens.

Add the phone number Klaxon calls from to your contacts, named "Klaxon", and mark it
as a favourite or an emergency contact. Many phones let favourites through
do-not-disturb even when apps are blocked.

## 3. Phone settings that cause missed pages

- **Battery saving.** Exclude Klaxon from battery optimisation or "deep sleep"
  lists. Phones that put unused apps to sleep will hold a page until you unlock them.
- **Focus or sleep modes.** If you use a scheduled sleep mode, add Klaxon to its
  allowed apps, and the Klaxon contact to its allowed callers.
- **Notification summaries.** Exclude Klaxon from any feature that bundles
  notifications into a summary later.
- **Volume.** The klaxon sound follows the alarm volume on some phones and the ringer
  volume on others. Check both.
- **Two devices.** If Klaxon is on a tablet too, the tablet must not acknowledge for
  you by accident. Turn its notifications off.

## 4. Send yourself a test page

In the app, open **Profile, Send test page**. Put the phone face down, lock it, set it
to silent, and wait. You should get the push within seconds, the text message at 1
minute and the call at 3 minutes. Acknowledge the call to stop it.

Repeat the test at the start of every shift; it is on the
[on-call handover checklist](handover-checklist.md). After any major update to your
phone's operating system, test again: updates reset notification permissions more
often than you would expect.

## 5. Useful things in the app

- **Who is on call** for every rota, with contact cards.
- **Overrides**: cover for an hour or two while you are unavailable. Whole-shift swaps
  are also made here, at least 24 hours ahead.
- **Acknowledge from the lock screen**: long-press the notification. Acknowledge only
  if you are starting work on it.
- **Declare from the phone**: the "Declare incident" button does the same as
  `/klaxon declare` in chat, if you are away from your laptop.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Test page arrives only when you unlock the phone | Battery optimisation | Exclude Klaxon, as in step 3 |
| Push arrives but makes no sound | Silent mode override not granted | Grant it in the phone's notification settings for Klaxon |
| No text message or call | Wrong number in your profile | Klaxon takes your number from Haven; correct it there, then wait an hour |
| "Not on any rota" in the app | Rota membership not set | Ask your team lead to add you in Klaxon |

Still stuck? Ask in `#team-sre`; someone will test with you.
