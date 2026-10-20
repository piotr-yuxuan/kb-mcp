---
title: "Password and MFA standard"
---

# Password and MFA standard

**Status:** in force. **Owner:** Callum Ibe, head of security. **Last reviewed:**
2026-08-17, when hardware security keys became mandatory for every administrator.

This standard applies to every employee and contractor, on every system that holds
Internal data or above.

## Passwords

Your identity provider password is the only password most people at Quillmoor need.

- At least 14 characters. A passphrase of four or more unrelated words is easier to
  remember and harder to guess than a short, complicated password.
- The identity provider checks every new password against a list of passwords known
  from public breaches and refuses a match.
- There is no forced periodic change. Change your password when there is any sign it
  may be known to someone else, or when Security asks you to.
- Never reuse it anywhere else, at work or at home.
- Never share it, not with a colleague and not with Security. Nobody at Quillmoor will
  ask you for it.

Secrets that systems use, and credentials a team shares for a supplier's website, go
in Strongroom, as set out in
[ADR-020: Strongroom as the only secrets store](../architecture/adr-020-strongroom.md).
They never go in a document, a spreadsheet or a chat message.

## MFA

MFA is required on every application behind the identity provider. An application
that cannot sit behind the identity provider needs Security's approval and its own MFA
before anyone uses it for work.

| Factor | Allowed for | Notes |
|---|---|---|
| Hardware security key | Everyone; required for administrators | Resists phishing: it will not answer a look-alike domain |
| Authenticator app, push with number matching | Everyone except administrators | Type the number shown on the sign-in screen |
| Authenticator app, one-time code | Everyone except administrators, as a fallback | Use only when push is unavailable |
| Text message, voice call, email code | Nobody | Disabled in the identity provider |

Never approve a prompt you did not start, even if it keeps coming. Report it with the
"Report phish" button or to security@quillmoor.example; the
[phishing playbook](phishing.md) explains what happens next.

## Hardware security keys for administrators

Administrators sign in with hardware security keys only. Push and one-time codes are
disabled on their accounts. For this standard, an administrator is anyone with
production access to Kubernetes, Shipwright or the databases, write access to
production paths in Strongroom, administrator rights in the identity provider, email,
chat or Harbour, or the `merchant-api-admin` role.

Every production administrator was enrolled under ENG-16, which finished in August
2026. New administrators are enrolled before the privileged entitlement is granted; the
[quarterly access review](access-reviews.md) flags anyone who slips through.

- **Two keys each.** Security issues a primary key and a backup. Keep the primary with
  you and the backup somewhere safe and separate, such as a locked drawer at home.
- **Only keys issued by Security.** Personal keys are not accepted, so that we know the
  model and can revoke it.
- **A lost or damaged key** is reported to security@quillmoor.example the same day.
  Security revokes it, you sign in with the backup, and a replacement is issued within
  2 business days.
- **Both keys lost** means no administrator access until Security has verified your
  identity, as below.

## Recovery when you have lost every factor

Security verifies your identity on a video call, with your camera on and your manager
confirming in the same call or in writing from their own account. Recovery is never
done over email or chat alone, and never at the request of someone calling on your
behalf. Expect it to take up to one business day; out of hours, only administrators
needed for an active incident are recovered.

## Exceptions

Exceptions are approved by the head of security, recorded with an end date, and last
90 days at most. A system that cannot meet this standard gets a plan to replace it, not
a permanent exception.
