---
title: "Data classification"
---

# Data classification

*Owner: Callum Ibe, head of security, with Beatrix Sallow, DPO. Last reviewed:
2026-05-14.*

All information at Quillmoor belongs to one of four levels: **Public**, **Internal**,
**Confidential** or **Restricted**. The level decides where the information may be
stored, who may see it and how it may be shared. If you do not know the level, treat it
as the higher of the two you are hesitating between, and ask in `#team-security`.

## The four levels

| Level | Meaning | Examples |
|---|---|---|
| Public | Approved for anyone to see | The Merchant API reference, Beacon updates, published job adverts, the company website |
| Internal | For staff and contractors; little harm if it leaked | This wiki, most ENG tickets, team calendars, most chat channels, the organisation chart |
| Confidential | Real harm to merchants, people or Quillmoor if it leaked | Personal data (staff records, merchants' contacts, sellers' bank details), merchant contracts, source code, unpublished financial results, security findings |
| Restricted | Severe harm, or a breach of PCI DSS or of the law, if it leaked | Cardholder data, secrets and keys, authentication data, health information in HR records, incident evidence |

Cardholder data is always Restricted, in every form: in a database, a log line, a
screenshot, a support ticket or a spreadsheet. A ticket that holds a PAN is
Restricted, however the PAN got there. Where cardholder data may live is set by the
card data environment, described in
[payments platform architecture](../payments/platform-architecture.md).

## Handling rules

| | Internal | Confidential | Restricted |
|---|---|---|---|
| Where it may be stored | Company services | Company services with access limited to those who need it | Only the systems approved for it: the card data environment for cardholder data, Strongroom for secrets, the SIRT evidence store for evidence |
| Sharing outside Quillmoor | With a business reason | Under a contract or an NDA, through company services, never as an email attachment | Never, except where Legal or the DPO has approved it in writing |
| On a laptop | Yes | Only while you work on it | Never |
| In chat | Yes | In private channels, with care | Never |
| Printing | Yes | Collect at once; shred after use | Never |

Public information has no handling rules, but only the owner of a document can make it
Public.

## Rules that catch people out

- **Aggregation raises the stakes.** One merchant's address is Confidential; an export of
  every merchant's address is still Confidential, but losing it is a far bigger event.
  Ask before you build any bulk export of personal data.
- **Copies keep the level of the original.** A screenshot of a Restricted screen is
  Restricted.
- **Test data is not exempt.** Real personal data copied into staging keeps its level.
  Use seed data instead.
- **Pseudonymised is not anonymised.** Replacing a name with a stable identifier
  leaves personal data, which is still Confidential.

## In the warehouse

Every warehouse column holding personal data is tagged, so that access and erasure can
follow it; see [tagging personal data columns](../data/personal-data-columns.md). Tags
map to these levels: a column tagged as personal data is Confidential, and no column in
the warehouse may hold Restricted data.

## When something is in the wrong place

If you find Restricted data where it should not be, such as a PAN in a ticket or a
password in a document, do not forward it or copy it to show someone. Email
security@quillmoor.example with where you found it. For secrets, follow the
[leaked secret playbook](leaked-secret.md).
