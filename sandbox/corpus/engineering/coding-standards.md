---
title: "Coding standards"
---

# Coding standards

Kept by the backend guild, with the TypeScript section kept by the frontend guild. Page owner: Kwabena Stroud, Ledger team lead. Last reviewed: 2026-09-16, after the [September backend guild](guild-backend-2026-09.md) adopted `log/slog` for Go.

These standards exist so that an engineer moving from `ledger` to `card-auth` can read the code on their first day, and so that reviewers spend their attention on behaviour rather than on taste. Most of the rules below are encoded in the shared linter configuration that every repository pulls from `platform-config`. Where this page and that configuration disagree, the configuration is what CI enforces, and the disagreement is a bug to raise in `#team-platform`.

To change a rule, bring a proposal to the backend or frontend guild with two or three real examples from our code. Once the guild agrees, the proposer edits this page and the shared configuration in the same week.

## Which language

We write back-office services in Python ([ADR-002](../architecture/adr-002-python-back-office.md)) and latency-critical services in Go ([ADR-003](../architecture/adr-003-go-latency-critical.md)). Merchant Hub is TypeScript and React ([ADR-024](../architecture/adr-024-react-merchant-hub.md)). Starting a service in any other language needs an ADR of its own.

| Language | Baseline version | Formatter | Linter | Type checking |
|---|---|---|---|---|
| Python | 3.13 | Ruff | Ruff | mypy, strict on new modules |
| Go | 1.26 | gofmt and goimports | golangci-lint | the compiler |
| TypeScript | 5.x | Prettier | ESLint | tsc with `strict: true` |

The development containers described in [local development](local-development.md) carry exactly these versions, so what passes on your laptop passes in CI.

## Rules for every language

**G1. Money is an integer in minor units, with its currency.** Never a float, and never a decimal string inside a domain object. [ADR-017](../architecture/adr-017-money-minor-units.md) has the reasoning; the shared `Money` types in Python and Go are how we follow it.

**G2. Time is UTC inside the system.** Store and compare timezone-aware UTC timestamps. Convert to UK time or CET only at the edges, where a rule is stated in local time; the settlement cut-offs themselves live in [settlement windows and cut-off times](../payments/settlement-cutoffs.md), not in code comments.

**G3. Every write path is idempotent.** An API handler or event consumer that changes state takes an idempotency key and returns the earlier result when it sees that key again, as [ADR-008](../architecture/adr-008-idempotency-keys.md) requires. An event consumer applies an event and records its identifier in one transaction, and commits its offset only once that transaction is durable; the [June 2026 backend guild](guild-backend-2026-06.md) has the reasoning.

**G4. Errors carry a stable code.** Errors that reach a log line, an alert or a merchant use the form `PREFIX-NNNN NAME`, for example `LDG-4091 UNBALANCED_JOURNAL`. Each service owns its prefix and keeps its codes in `errors.yaml` at the repository root, with a one-line description and the runbook that explains it. Numbers are never reused, even after a code is retired, because runbooks, dashboards and alerts refer to them.

**G5. Secrets come from Strongroom and nowhere else** ([ADR-020](../architecture/adr-020-strongroom.md)). Not from a committed file, not from a default value in code, and never into a log line or an error message.

**G6. Configuration is read once, at start-up, and validated.** A service that starts with a missing or malformed setting exits at once with a clear message; it does not fail on the first request at three in the morning.

**G7. Feature flags go through the Switchboard client.** Name them and retire them as [feature flags and kill switches](../release/feature-flags.md) describes. A flag read any other way is invisible to the audit log.

**G8. Logs are structured, and traces propagate.** See [logging and tracing](logging-and-tracing.md).

**G9. Comments say why.** The code says what. A comment that repeats the code is deleted at review.

**G10. No dead code.** Delete it; Git remembers. Commented-out blocks are rejected at review, as the [code review guidelines](code-review.md) say.

## Python

- Type hints on every public function and every dataclass field. New modules run under `mypy --strict`; older modules join the strict list as they are touched, never in a change of their own.
- Values are frozen dataclasses. Mutable state at module level is not allowed.
- Catch the narrowest exception you can handle. A bare `except:` or `except Exception:` is allowed only at the top of a worker loop, where it logs the error and moves the message to the dead-letter topic.
- Raise domain errors from the service's `errors` module, so that G4 holds.
- Imports are absolute. No wildcard imports, and no imports inside functions except to break a genuine cycle.
- `asyncio` only in services that are asynchronous end to end. Never call a blocking database driver from an event loop.
- Database access goes through the repository's data-access module. SQL strings anywhere else fail review.
- Functions stay short enough to read without scrolling; Ruff's complexity limit is 10, and we do not raise it per file.

```python
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ledger.errors import UnbalancedJournal
from ledger.money import Money


@dataclass(frozen=True)
class JournalLine:
    account: str
    side: Literal["debit", "credit"]
    amount: Money


def check_balanced(lines: Sequence[JournalLine]) -> None:
    """Raise UnbalancedJournal unless debits equal credits in each currency."""
    net: Counter[str] = Counter()
    for line in lines:
        sign = 1 if line.side == "debit" else -1
        net[line.amount.currency] += sign * line.amount.minor
    unbalanced = {currency: diff for currency, diff in net.items() if diff}
    if unbalanced:
        raise UnbalancedJournal(unbalanced)
```

The function takes plain values, decides, and raises; posting the journal is a separate step. Keeping decisions apart from effects like this is what makes the test in the [testing strategy](testing-strategy.md) a five-line unit test rather than an integration test.

## Go

- `gofmt` and `goimports` on save. CI rejects unformatted code.
- `context.Context` is the first parameter of anything that does I/O, and it is honoured: pass it down, and stop work when it is done. Latency-critical services live inside budgets that one forgotten context can blow.
- Wrap errors with `%w` and a short phrase saying what was being attempted. Compare with `errors.Is` and `errors.As`, never by string.
- No `panic` on a request path. A panic in a handler is a bug, and the recovery middleware logs it with its stack as an error.
- Every goroutine has an owner that waits for it. Use `errgroup.Group` for fan-out, with a context that cancels the siblings when one fails.
- Log with `log/slog` and the shared handler in `qm-go/logging`. This was adopted at the September 2026 guild; existing services move over as they are touched.
- Interfaces belong to the package that uses them, and stay small.
- Package names are short lower-case nouns: `issuer`, `hsm`, `quote`. No `util`, `common` or `helpers`.

```go
func (c *Client) Authorise(ctx context.Context, req AuthRequest) (AuthResult, error) {
	ctx, cancel := context.WithTimeout(ctx, c.issuerTimeout)
	defer cancel()

	res, err := c.issuer.Send(ctx, req)
	if errors.Is(err, context.DeadlineExceeded) {
		return AuthResult{}, ErrIssuerTimeout // CAU-1207 in errors.yaml
	}
	if err != nil {
		return AuthResult{}, fmt.Errorf("send to issuer %s: %w", req.IssuerID, err)
	}
	return res, nil
}
```

The timeout comes from configuration, not a literal, and the error the caller sees is the catalogued one rather than whatever the transport returned.

## TypeScript and React

This section is kept by the frontend guild.

- `strict: true` everywhere. No `any` without a comment that says why; at a boundary, take `unknown` and parse it.
- Function components and hooks only. No new class components.
- Use components from `@quillmoor/inkwell` rather than building new ones. If something is missing, follow [contributing to Inkwell](../design/contributing.md); styling follows [theming and dark mode](../design/theming.md).
- Responses from `merchant-api` are parsed against a schema where they enter the application; components never see raw responses.
- Tests find elements by role and label, the way a user would, not by class name or test identifier.
- Interface text follows the [content style guide](../design/content-style.md).

## Shell scripts

Shell is for glue: a few lines that call `qm`, `shipwright` or `conveyor` in order. Anything with branching logic, parsing or more than about 50 lines is rewritten in Python. The scripts that remain follow these rules, which ShellCheck enforces in CI:

- Start with `#!/usr/bin/env bash` and `set -euo pipefail`.
- Quote every expansion: `"$file"`, never `$file`.
- Take arguments as named flags, and print usage when they are wrong.
- Never echo a secret, and never put one on a command line, where it lands in the process list and the shell history.

```bash
#!/usr/bin/env bash
set -euo pipefail

usage() { echo "usage: $0 --service NAME --release VERSION" >&2; exit 64; }

service="" release=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) service="$2"; shift 2 ;;
    --release) release="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$service" && -n "$release" ]] || usage

shipwright deploy "$service" --release "$release"
```

## Retries and timeouts

Every call across the network has a timeout, taken from configuration. Retries are bounded, use exponential backoff with jitter, and happen in one layer only: if the client library retries, the caller does not. A retry is safe only when the operation is idempotent (G3), so a retry of a write always reuses the original idempotency key. Errors that cannot succeed on a second attempt, such as a validation failure or a declined card, are never retried.

## Dependencies

Add a third-party dependency only when it saves real work, and prefer the standard library when it is close enough. Check the licence against the [open-source licence policy](../legal/open-source-licences.md) before the change goes up for review, and keep versions current as the [dependency update policy](../release/dependency-updates.md) describes. Pin exact versions in lock files; ranges belong only in shared libraries.

## Naming

| Thing | Convention | Example |
|---|---|---|
| Service | kebab-case noun | `settlement-batcher` |
| Python module | snake_case | `payout_batches.py` |
| Go package | short lower-case noun | `quote` |
| Environment variable | `QM_` and upper snake case | `QM_LEDGER_DB_URL` |
| Metric | service, subsystem, unit | `card_auth_issuer_latency_seconds` |
| Error code | `PREFIX-NNNN NAME` | `FXQ-2002 STALE_RATE` |
| Database table | plural snake_case | `payout_batches` |
| Boolean | reads as a question | `is_held`, `hasExpired` |

## SQL in services

Queries are parameterised, always; string formatting into SQL fails review. Select explicit columns, never `*`, so that adding a column cannot change a result. Schema changes are migrations run with `shipwright migrate`, following [database migrations](../release/database-migrations.md). Each service owns its database ([ADR-012](../architecture/adr-012-database-per-service.md)) and never reads another service's tables; ask the owning team for an API or an event instead. Warehouse SQL follows its own [SQL style guide](../data/sql-style-guide.md).

## Service documentation

Every service has a `README.md` at the top of its directory, short enough to read in five minutes, with the same headings in the same order so that on-call can find things without thinking:

1. **What it does**, in two sentences, and who owns it.
2. **How to run it locally**, which is usually one `qm` command.
3. **Dependencies**: the databases, topics and services it calls, and those that call it.
4. **Operations**: its Lantern dashboards, its alerts, and links to its runbooks.
5. **Error codes**: a pointer to its `errors.yaml`.

Public functions and packages have docstrings or doc comments that say what the caller can rely on, including the errors they raise. Longer design reasoning belongs in an ADR, not in a comment that nobody updates.

## Suppressions

A suppression carries its reason on the same line:

```python
def build_iso_message(mti, pan_token, amount, currency, merchant, terminal, stan):  # noqa: PLR0913 - mirrors the scheme message fields one for one
    ...
```

```go
//nolint:gosec // G404: jitter for retry delays, not a secret
delay := base + time.Duration(rand.Int64N(int64(base)))
```

A suppression without a reason fails CI. If a team finds itself suppressing the same rule again and again, the rule is wrong for us or the code is: bring it to the guild rather than suppressing it one line at a time. Debt that a suppression hides goes on the register described in [managing technical debt](tech-debt.md).
