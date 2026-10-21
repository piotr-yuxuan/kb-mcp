---
title: "Feature flags and kill switches"
---

# Feature flags and kill switches

Owner: Platform team, who also run Switchboard. Questions in `#team-platform`.
Last reviewed: 2026-10-06

Switchboard is Quillmoor's own flag service; [ADR-014](../architecture/adr-014-build-switchboard.md) explains why we built it rather than adopting one. It stores two kinds of thing that look alike in the console and behave very differently in practice: **feature flags**, which let you release new behaviour gradually, and **kill switches**, which let you turn an existing feature off in an emergency.

| | Feature flag | Kill switch |
|---|---|---|
| Name | `sb.<service>.<flag>` | `ks.<service>.<feature>` |
| Purpose | Release new behaviour gradually, or to chosen merchants | Turn an existing feature off, fast |
| Values | on or off, a percentage, a list of merchants | engaged or released |
| Default in code | off: the old behaviour | released: the feature runs |
| Lifetime | Temporary: removed within 90 days of full rollout | Permanent, for as long as the feature exists |
| Who changes it | The owning team | The owning team, the service's on-call, Site Reliability, the IC |
| Logged | Yes | Yes, with a mandatory reason |

## Naming

The name is the contract between the code and the console, so we are strict about it.

- Flags start with `sb.`, kill switches with `ks.`. Nothing else is accepted.
- The middle part is the Shipwright service name, exactly: `merchant-api`, not `merchantapi` or `api`.
- The last part is lower-case words joined by hyphens that describe the behaviour, not the project: `partial-refunds`, not `eng-6-phase-2` or `q3-launch`.
- No dates, team names or people's names. Flags tend to outlive all three.
- One flag controls one decision. If you need two decisions, make two flags.

| Name | Verdict |
|---|---|
| `sb.merchant-hub.dark-mode` | Good |
| `sb.merchant-api.refund-reasons` | Good |
| `ks.notify.webhook-retries` | Good |
| `ks.payout-gateway.batch-scheduler` | Good |
| `sb.mh.newExport` | Rejected: not a service name, and not lower-case words |
| `sb.merchant-api.eng-30` | Rejected: a ticket, not a behaviour |
| `ks.card-auth` | Rejected: a kill switch must name the feature it stops |
| `sb.payments.refunds` | Rejected: `payments` is a team, not a service |

Switchboard checks names when it reads `switchboard.yaml` and refuses the deploy if any name breaks these rules.

## Kinds of flag

**Release flags** are the common case. They hide new code until it is ready, then let you open it up gradually. They are temporary by definition.

**Allow-list flags** give early access to named merchants, for example `sb.merchant-api.date-versioning` while epic ENG-30 is in progress. They are release flags with a different targeting rule, and just as temporary.

**Operational flags** tune behaviour in production without a deploy. The best-known one is `sb.card-auth.stepup-sampling`, used in [Runbook: card authorisation latency](../payments/card-auth-latency.md). Operational flags are declared `permanent: true` with a written reason, and release engineering reviews the list every year. If you cannot write the reason in one sentence, it is probably a release flag in disguise.

## Declaring a flag

Flags and kill switches are declared in `switchboard.yaml` at the root of the service's repository and reviewed in the pull request that first uses them. Switchboard reads the file whenever Shipwright deploys a release. A flag that is not declared does not exist: the client library returns the code default and logs a warning.

```yaml
flags:
  - name: sb.merchant-api.refund-reasons
    kind: release
    owner: merchant-experience
    description: Accept and store a reason on partial refunds (ENG-6).
    default: false
  - name: sb.merchant-api.date-versioning
    kind: allow-list
    owner: merchant-experience
    description: Honour the Quillmoor-Version header for allow-listed merchants (ENG-30).
    default: false
kill_switches:
  - name: ks.notify.webhook-retries
    owner: merchant-experience
    description: Stop retrying failed webhook deliveries; deliver once and record failures.
```

Values are not in the file. They live in Switchboard, per environment, and are changed in the console at `switchboard.quillmoor.example`.

## Using flags in code

Go, in `merchant-api`:

```go
import "quillmoor.example/go/switchboard"

func (h *RefundHandler) Create(ctx context.Context, req RefundRequest) error {
	withReason := switchboard.Bool(ctx, "sb.merchant-api.refund-reasons", false,
		switchboard.ForMerchant(req.MerchantID))
	if withReason {
		return h.createWithReason(ctx, req)
	}
	return h.createLegacy(ctx, req)
}
```

Python, in `notify`:

```python
from quillmoor import switchboard


def deliver(event):
    if switchboard.engaged("ks.notify.webhook-retries"):
        log.info("webhook retries stopped by kill switch", event_id=event.id)
        return deliver_once(event)
    return deliver_with_retries(event)
```

TypeScript, in Merchant Hub:

```typescript
import { flags } from "@quillmoor/switchboard";

export async function themeChoices(merchantId: string): Promise<string[]> {
  const darkMode = await flags.bool("sb.merchant-hub.dark-mode", false, { merchantId });
  return darkMode ? ["light", "dark"] : ["light"];
}
```

Rules that make flags safe:

- **Always pass a default, and make it the old, safe behaviour.** The client library keeps the last values it received from Switchboard, which streams changes and resynchronises every 10 seconds. If Switchboard is unreachable, the code keeps those values; the code default is used only by a process that never managed to load any. The default is what you get on the worst day, so choose it accordingly.
- **Evaluate once per request** and pass the result down. A flag evaluated in five places can change value between the first and the fifth.
- **Do not evaluate flags in shared libraries.** The calling service decides and passes the decision in.
- **Test both branches** until the flag is removed. A fake client (`switchboard.Fake` in Go, `switchboard.testing.override` in Python) makes that easy.

## Rolling a flag out

A typical release flag goes through: the test merchants in `staging-eu`, then 1%, 10%, 50% and 100% of merchants in production, with at least a working day between steps for anything that touches money. Percentages are bucketed by merchant ID, so a given merchant sees a stable experience rather than flickering between old and new.

Turning a flag **up**, so that more merchants get new behaviour, is a production change. It follows the same deploy windows as a release ([How code reaches production](deployment-pipeline.md)) and is not allowed during a change freeze without an exception ([Change freeze calendar 2026](change-freeze-2026.md)). Turning a flag **down** or off is always allowed, at any hour.

"Full rollout" means: on for 100% of traffic in production, with no allow-list and no exclusions. Switchboard records the date a flag reaches that state; it is the date the removal clock starts from.

## Removing flags: the 90-day rule

A release flag must be **removed within 90 days of full rollout**. Removed means the off branch of the code is deleted, the flag is gone from `switchboard.yaml`, and the release that does both is running in production. Switching the flag off in the console is not removal, and neither is leaving it on forever.

What happens automatically:

| Days after full rollout | What Switchboard does |
|---|---|
| 60 | Posts a reminder in the owning team's channel |
| 90 | Marks the flag overdue in the console and raises an ENG ticket for the owning team, labelled `flag-cleanup` |
| Every week after 90 | Lists the team's overdue flags in its channel on Monday morning |

Each quarter, release engineering publishes a clean-up report with the numbers per team; the latest is the [Flag clean-up report Q3 2026](flag-cleanup-2026-q3.md).

Why so strict? Each live flag doubles the paths through a piece of code, and nobody tests the old path once the new one has been on for a month. Old flags also get flipped by mistake. The worst flag incident we have had came from a release flag that had been at 100% for eleven months: someone turning off what they thought was an unrelated flag sent a few hundred merchants back to code that no longer matched the database.

Exceptions: operational flags declared permanent, and allow-list flags waiting on a contractual date with a named merchant, which may have one extension of 30 days, agreed in `#team-platform` and recorded on the flag.

## Kill switches

A kill switch turns an existing feature off without a deploy. Engaging one is a production change in every sense except that it bypasses the pipeline, so it comes with rules of its own.

- **No deploy needed.** A flip reaches every pod in both regions within about 15 seconds. It is allowed at any hour, inside or outside the deploy windows, and during change freezes.
- **Every flip is logged.** Switchboard records who flipped it, when, the old and new state, the reason, and the incident channel if there is one. The reason field is mandatory. The log is append-only, shown in the console, posted to `#deploys` and to the owning team's channel, and copied to the warehouse each night as `raw.switchboard_audit`.
- **Who may flip.** The owning team, whoever is on call for the service, Site Reliability, and the IC of an open incident.
- **Every switch is exercised.** Each kill switch is engaged and released in `staging-eu` once a quarter. A switch that has never been flipped is a switch that may not work.

The audit log came with epic ENG-8 (ENG Sprints 8 to 15, July to November 2025). Before it, the console kept only the current state, and twice during incidents we could not tell who had engaged a switch, or why.

Runbooks that rely on a kill switch name it explicitly; for example, `ks.payout-gateway.batch-scheduler` in [Runbook: rolling back payout-gateway](../payments/payout-gateway-rollback.md).

To flip from the console, open the switch, press **Engage**, fill in the reason and the incident channel, and confirm. Automation and scripts use the API, with a token read from Strongroom:

```bash
curl -sS -X POST \
  "https://switchboard.quillmoor.example/api/v1/kill-switches/ks.notify.webhook-retries/engage" \
  -H "Authorization: Bearer ${SWITCHBOARD_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason": "retry storm against one merchant endpoint", "incident": "inc-notify-retries"}'
```

When should a feature have a kill switch? When it calls an outside party, moves money, sends messages to merchants, runs on a schedule, or could flood a downstream service. If you are not sure, add one: it costs a line of YAML and an `if`.

## Flags in other environments

Values in `staging-eu` are set separately from production; see [Staging environments](staging-environments.md). In local development, `qm dev up` reads `switchboard.local.yaml` if present, so you can force values without touching anyone else's environment; see [Local development environment](../engineering/local-development.md).

## Things not to do

- **Flags as configuration.** Timeouts, endpoints and batch sizes belong in the release, where they are reviewed and travel with the code.
- **Nested flags.** A flag checked only when another flag is on creates combinations nobody tests.
- **Flagging a migration.** A schema change cannot be switched off. Flag the code that uses the new schema; see [Database migrations](database-migrations.md).
- **Reusing a name.** Once a flag is removed its name is retired, so that an old release still in staging cannot pick up a new meaning.
- **Turning a kill switch into a feature flag.** If you find yourself engaging a kill switch for a percentage of merchants, you wanted a flag.
