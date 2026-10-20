---
title: "ADR-003: Go for latency-critical services"
---

- **Status:** Accepted, 2017-04-03
- **Author:** Nadia Ferreira
- **Deciders:** Ottilie Marsh, Yusuf Achterberg, Kwabena Stroud

## Context

When a shopper pays on a marketplace, the marketplace's checkout waits while we decide
whether to send the payment to the issuer, ask for 3DS, and relay the issuer's answer.
Every millisecond we spend is added to the shopper's wait, and the card schemes expect
answers within fixed limits. A slow answer is a lost sale for our merchant and, past
the limits, a declined payment.

Our first prototype of the authorisation path was a Python service. Under a load test
at ten times our expected launch volume, its tail latency was dominated by work we did
not control: interpreter overhead on JSON handling, the global interpreter lock under
concurrent requests, and garbage collection pauses at awkward moments. We could have
tuned it, but we would have been tuning it for years.

[ADR-002](adr-002-python-back-office.md) already settled Python for the back office.
This record covers the other side of that line.

## Decision

Services on the synchronous payment path are written in Go. The first is `card-auth`.

A service is latency-critical when a cardholder or a merchant's checkout waits on it
while it runs. Anything that can be queued, batched or retried later is not, and
follows ADR-002.

House rules for these services:

- **Standard library first.** The HTTP server, JSON handling and context propagation
  come from Go's standard library. Frameworks need a reason.
- **A deadline on every outbound call.** No call to another service, a database or
  the issuer is made without a deadline taken from configuration. A missing deadline
  fails review.
- **Benchmarks in continuous integration** for the hot path, with the previous run as
  the baseline.
- **Profiling stays on in production**, behind the internal network, so that a slow
  hour can be explained from data rather than guessed.

```go
// Every outbound call carries a deadline from configuration.
func (c *IssuerClient) Authorise(ctx context.Context, req AuthRequest) (AuthResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, c.cfg.IssuerTimeout)
	defer cancel()
	return c.send(ctx, req)
}
```

## Consequences

- We hire for and maintain two languages. On-call engineers on the payments rota must
  read Go well enough to follow a stack trace at night.
- Some helpers exist twice, once per language. We keep that list short and prefer
  shared schemas to shared code.
- The line between "latency-critical" and "back-office" will be argued over. A service
  that changes category gets a new ADR rather than a quiet rewrite.
- The latency budgets themselves belong to the services and their owners: see
  [Payments platform architecture](../payments/platform-architecture.md) for the
  budgets, and [Runbook: card authorisation latency](../payments/card-auth-latency.md)
  for what to do when `card-auth` misses its own.

## Alternatives considered

- **Python with an asynchronous framework.** Helps with waiting on the network, does
  nothing for interpreter overhead or pauses, and makes the code harder for the back
  office to share.
- **A language on the Java platform.** Fast once warm, with good tooling, but
  start-up time, memory per instance and garbage collector tuning were all things we
  would have had to learn from scratch.
- **Rust.** Predictable latency and no garbage collector, but in 2017 one engineer in
  eleven had used it, and hiring would have been slow.

## Related ADRs

- [ADR-002](adr-002-python-back-office.md): Python for back-office services.
- [ADR-011](adr-011-opentelemetry.md): tracing across Go and Python services.
