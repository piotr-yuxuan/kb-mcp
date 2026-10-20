---
title: "Open-source licence policy"
---

- **Owner:** Saoirse Lindqvist, general counsel, with Bram Oyelaran, head of platform
  engineering
- **Applies to:** every repository at Quillmoor, including internal tools and scripts
- **Last reviewed:** 2026-03-18

We build on open source every day and want to keep doing so without surprises. This
policy says which licences engineers may use without asking, which need Legal's review,
and how the check is automated. In short: **MIT, Apache 2.0 and BSD are allowed; GPL needs
Legal's review.**

## Licence categories

| Category | Licences | What you may do |
|---|---|---|
| Allowed | MIT, Apache 2.0, BSD (2-clause and 3-clause) | Use, modify and ship, keeping the copyright and licence notices |
| Allowed with care | MPL 2.0 and other file-level copyleft licences | Use freely; changes to the licensed files themselves must be published, so do not patch them in place |
| Legal's review | GPL (any version), including LGPL and AGPL, and any other copyleft licence not listed above | Raise a request before adding the dependency |
| Not allowed | No licence at all, "non-commercial" licences, licences restricting fields of use | Do not use; find an alternative |

The GPL family needs review because its obligations depend on how the code is combined
and distributed, and Merchant Hub and our SDKs are distributed to merchants. A GPL tool
used only on an engineer's laptop or in CI, and never shipped, is usually approved within a
day; a GPL library linked into a service rarely is. AGPL code reached over a network can
create obligations even when nothing is distributed, so do not run AGPL software in
production without approval.

Code with no licence is not open source: all rights remain with its author. Copying a
snippet from a forum answer or a public repository without a licence is not allowed.

## How the check works

The CI pipeline reads each repository's dependency manifests and checks every licence
against the categories above, using SPDX identifiers.

- An **allowed** licence passes silently.
- A **Legal's review** licence fails the check unless the dependency is on the approved
  exceptions list, which Legal maintains in the `legal-oss-exceptions` repository.
- An unknown or missing licence fails the check.

Do not suppress the check or vendor the code to get round it. If it fails, raise a
request. Updating existing dependencies is covered by the
[dependency update policy](../release/dependency-updates.md); a licence change in a new
version is treated like a new dependency.

## Asking for a review

Raise a "Partnership or other" request in Clausebook (see
[Requesting a contract review](contract-requests.md)) with:

1. the package name, version and link to its source;
2. the licence, and the SPDX identifier if you know it;
3. which service or tool will use it, and whether it is shipped to merchants;
4. how it is used: linked as a library, called as a separate process, or used only at
   build time;
5. the alternatives you looked at.

Most reviews are answered within 2 business days. An approval names the package, the
version range and the use, and is added to the exceptions list.

## Contributing to open source

Engineers are welcome to contribute fixes upstream to projects we use. You do not need to
ask for small fixes to projects under allowed licences, provided the contribution contains
no Quillmoor code beyond the fix and nothing confidential. Ask Legal before:

- signing a contributor licence agreement on Quillmoor's behalf;
- publishing a new project under Quillmoor's name;
- contributing anything related to payments security or fraud detection.

Publishing a new project also needs the approval of the head of platform engineering and
the head of security.
