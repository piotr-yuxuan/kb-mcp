---
title: "Dependency update policy"
---

# Dependency update policy

| | |
|---|---|
| Owner | Platform (release engineering), with Security for vulnerability fixes |
| Applies to | Every service and library that Shipwright builds |
| Last reviewed | 2026-07-14 |

Dependencies rot quietly. A library two major versions behind is not a problem until the day a security fix lands only in the newest one, and then it is an emergency. This policy exists so that updates are small, regular and boring.

## The rules

1. **Lockfiles are committed.** Every repository commits its lockfiles: `go.sum` for Go, the lockfile of the Python project manager in use, `package-lock.json` for TypeScript. Shipwright refuses to build a service whose lockfile is missing or out of date with its manifest.

2. **Automatic update pull requests arrive every Monday.** The dependency bot opens them at 06:00 UK time. Patch and minor updates are grouped into one pull request per ecosystem per repository; each major update gets its own.

3. **Patch and minor updates are merged within one sprint.** If the tests pass, merge. If they fail, the failure is a ticket in the current sprint, not a reason to close the pull request.

4. **Major updates are planned.** Each one becomes an ENG ticket with an estimate. No service may be more than one major version behind on its language runtime, its PostgreSQL driver or its web framework.

5. **Security fixes follow the vulnerability timelines,** not this page. The deadlines by severity are on [Vulnerability management SLAs](../security/vulnerability-slas.md). The bot labels such pull requests `security` and Security follows them up.

6. **New dependencies are a decision.** Before adding one, check its licence against the [Open-source licence policy](../legal/open-source-licences.md), check that it is maintained, and say in the pull request why the standard library or an existing dependency will not do. A dependency added for one function is rarely worth it.

7. **Base images are rebuilt weekly** by Platform and pinned by digest. Services pick up the new base image through the Monday pull request like any other update.

8. **Updates ship like any other change.** They ride the release train or are deployed by hand, through every stage, canary included. A dependency update is never "too small to need a canary"; some of our worst regressions were one-line lockfile changes.

## Front ends and Inkwell

Merchant Hub and other front ends stay within one minor version of the latest `@quillmoor/inkwell`. Inkwell's release notes say what changed and what to check; the most recent are the [Inkwell 3.2 release notes](../design/release-notes-inkwell-3-2.md). Major Inkwell versions come with a migration guide and a few sprints' notice.

## Platform-wide upgrades

Some upgrades cannot be done service by service: the Kubernetes version, the base image's operating system, the shared Go and Python libraries. Platform runs those as projects, with a change ticket for each step. The Kubernetes 1.31 upgrade, epic ENG-9, is the recent example: node pools were drained and upgraded one region at a time over ENG Sprints 16 to 20, between November 2025 and January 2026.

## Exceptions

Sometimes an update cannot be merged: a breaking change upstream, a bug in the new version, a licence change. In that case:

- close the pull request with a comment saying why;
- add the package and version to `dependency-exceptions.yaml` in the repository, with an expiry date no more than 90 days away and a ticket key;
- the bot will not propose that version again until the exception expires.

```yaml
exceptions:
  - package: example.com/retry
    skip: ">=3.0.0"
    reason: "3.x changes backoff semantics; migration tracked in ENG ticket"
    expires: 2026-10-09
```

Exceptions that expire without action reappear in the Monday pull request, which is the point.

## Who to ask

| Question | Where |
|---|---|
| The bot, base images, Shipwright refusing a lockfile | `#team-platform` |
| Whether a vulnerability applies to us | `#team-security` |
| A licence you have not seen before | Legal, through the policy page above |
| Inkwell upgrades | `#team-inkwell` |
