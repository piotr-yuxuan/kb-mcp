---
title: "ADR-014: Build Switchboard for feature flags"
---

- **Status:** Accepted, 2021-09-20
- **Author:** Bram Oyelaran
- **Deciders:** Ottilie Marsh, Nadia Ferreira, Yusuf Achterberg, Lukas Brennand,
  Ama Rowntree

## Context

Our feature flags are environment variables and configuration files. Turning a feature
on or off means changing a file and deploying the service. Three things have made that
untenable this year:

- **Switching off takes a deploy.** In June a new payout-status email misfired for a
  subset of sellers. The fix was to turn it off, but turning it off took a full deploy
  of `notify`: forty minutes from decision to effect, while emails kept going out.
- **No gradual rollouts.** Product wants to release features to a few merchants, then
  a percentage, then everyone. Our files hold one value per environment.
- **No record.** We cannot say who changed a flag, when, or why, except by reading
  commit history across several repositories.

We compared three ways forward: a hosted flag vendor, an open-source flag server, and
building our own. The hard constraints were these:

- `card-auth` must evaluate flags with no network call on the authorisation path
  ([ADR-003](adr-003-go-latency-critical.md)), and it lives in the card data
  environment, which may not call arbitrary services outside it.
- Merchant identifiers used for targeting should not leave our infrastructure.
- Clients in Go and Python, of equal quality.

## Decision

We build Switchboard, a small internal flag service owned by Platform.

- **Flags as reviewed code.** Flag definitions, their defaults and their targeting
  rules live in a Git repository owned by Platform. A change is a reviewed commit, so
  every change has an author, a reviewer and a reason.
- **Local evaluation.** Clients hold the full set of flags for their service in memory
  and evaluate them in-process. Switchboard streams changes to clients, which apply
  them within seconds. No flag check ever waits on the network.
- **Safe defaults.** Every flag has a default compiled into the client. If Switchboard
  is unreachable when a service starts, the service runs with defaults and says so in
  its health endpoint.
- **Targeting.** By environment, by merchant, and by a stable percentage of merchants.
- **Clients.** One Go and one Python library, maintained by Platform.

```go
if sb.Enabled(ctx, "sb.notify.payout-status-email", merchantID) {
	sendPayoutStatusEmail(ctx, payout)
}
```

Naming, ownership, how long a flag may live and how to clean one up are kept in
[Feature flags and kill switches](../release/feature-flags.md), so that the rules can
change without a new ADR.

## Consequences

- Turning a feature off no longer needs a deploy.
- We own and run one more service. Its availability matters, though less than it
  seems: clients keep their last known flags if the stream drops.
- Flags accumulate. Without a clean-up habit, code fills with branches nobody
  remembers. The rules on the feature flags page exist for that reason.
- Product managers can see rollout state without asking an engineer, through a
  read-only page in Switchboard.
- Kill switches, which turn off part of a running service in an emergency, were not
  part of this decision. They were added to Switchboard later, under ENG-8.

## Alternatives considered

- **A hosted flag vendor.** Mature and quick to adopt, but its clients fetch rules
  from the vendor's servers, which `card-auth` may not call, and targeting would send
  merchant identifiers to a third party. The price per seat also grows with every
  engineer we hire.
- **An open-source flag server.** We trialled two. One had no Go client we were
  willing to run inside the card data environment; the other evaluated flags on the
  server, adding a network call to every check.
- **Keep configuration files, deploy faster.** Faster deploys help, but a deploy is
  still the wrong tool for switching something off in an incident.

## Related ADRs

- [ADR-003](adr-003-go-latency-critical.md): why evaluation must be local.
- [ADR-010](adr-010-kubernetes.md): where Switchboard and its clients run.
