---
title: "Code review guidelines"
---

# Code review guidelines

- **Owner:** Bram Oyelaran (head of platform engineering), with Nadia Ferreira (head of payments engineering) for the rules on payments services
- **Last reviewed:** 2026-09-30
- **Questions:** `#team-platform`

Every change to production code at Quillmoor is reviewed by someone other than its author before it merges. Review is how we share knowledge of the code, catch defects while they are cheap, and keep the payments services safe to change. It is not a gate to be got through: a good review leaves both people knowing more than they did before.

This page sets out the rules that the code host and CI enforce, and the habits that we expect but cannot enforce. The [coding standards](coding-standards.md) say what good code looks like; this page says how we agree that a change is good enough to merge.

## The rules at a glance

| Rule | Payments services | All other repositories |
|---|---|---|
| Approvals needed to merge | Two, at least one from the owning team | One |
| First review | Within one business day | Within one business day |
| Size of a change | Under 400 lines | Under 400 lines |
| Required checks | All green, see [continuous integration](continuous-integration.md) | All green |
| Who presses merge | The author | The author |

"Payments services" means the services owned by Payments Core, Payouts and Ledger: `card-auth`, `fx-quote`, `payout-gateway`, `settlement-batcher` and `ledger`, together with the shared payments libraries in the Payments Core repository. The owners file at the root of each repository marks these paths, and the code host will not enable the merge button until the approval count is met.

## Approvals

### Why two for payments

A defect in a payments service moves money: a payout sent twice, a journal that does not balance, a card declined that should have been approved. The second approval is not a second pair of eyes on the same thing, so we ask the two reviewers to split the work. One reviews the change as code: design, tests, readability. The other, who must belong to the owning team, reviews it as a change to a payments system: idempotency, retries, failure paths, what happens to work already in flight, and whether the ledger still balances afterwards.

When a change touches the ledger's schema, one of the two approvals must come from the Ledger team, whichever repository the change lives in.

### Who can approve

- Outside payments, anyone in engineering with write access to the repository may give the single approval.
- For payments services, at least one approver must be listed in the owners file for every path the change touches.
- The author cannot approve their own change, and neither can anyone who wrote part of it. A pairing partner who co-wrote the change counts as an author.
- Bots never count as approvers, including the dependency update bot (see the [dependency update policy](../release/dependency-updates.md)).
- An approval survives a rebase that does not change the diff. On payments services, a new commit that changes behaviour dismisses existing approvals automatically; elsewhere, use judgement, and ask again if the change is more than a typo.

## Keep changes under 400 lines

We count lines added plus lines removed, excluding generated code, lock files, snapshot files and test fixtures. The CI check `pr-size` comments on the change with the count and labels it `size/xl` once it passes 400 lines.

Review quality drops sharply with size. Above a few hundred lines, reviewers skim, and the defects they miss are the ones that matter. Small changes are also quicker to review, which is how we keep the one-business-day turnaround without asking anyone to stop their own work for an afternoon.

To check before you open the change:

```bash
# lines added plus removed against main, ignoring lock files and generated code
git diff --numstat origin/main...HEAD -- . ':!*.lock' ':!**/generated/**' \
  | awk '{ total += $1 + $2 } END { print total }'
```

Ways to stay under the limit:

1. **Separate the refactor from the behaviour change.** A pure rename or move goes first, on its own, and is quick to approve.
2. **Ship dark.** Land the new code path behind a Switchboard flag and switch it on later; see [feature flags and kill switches](../release/feature-flags.md).
3. **Stack the changes.** Open the second change against the branch of the first, and say so in both descriptions.
4. **Keep migrations apart.** A schema migration goes in its own change, reviewed against the [database migrations](../release/database-migrations.md) guidance, before the code that uses it.

Some changes cannot be split sensibly: a mechanical rename across a repository, a dependency upgrade that touches every import, a vendored library. Add the label `large-change`, explain why in the description, and tell the reviewer which files deserve real attention. The reviewer may still ask you to split it, and that request is always reasonable.

## First review within one business day

When a change is marked ready for review, someone gives it a first review within one business day. A business day is Monday to Friday, excluding the bank holidays of the reviewer's office; remember that Paris is one hour ahead of London. A first review is substantive: an approval, a request for changes, or real questions. A thumbs-up emoji is not a review.

Each team keeps a review rota so that this does not depend on goodwill. The person on the rota looks at the queue twice a day, at the start of the day and after lunch. In any week when one of the team's regular reviewers is away, two people share the rota; the [September 2026 backend guild](guild-backend-2026-09.md) added this rule after a summer of slow first reviews.

To see the queue:

```bash
qm review queue --team payouts     # changes waiting for your team
qm review queue --mine             # changes where you were asked by name
```

If a change has waited a full business day, the author may ask in the team's channel. After two business days, raise it with the team lead: something is wrong with capacity, not with the author's patience. Draft changes are not in the queue, and the clock starts when the change leaves draft.

The one-day target is for the first review, not for the whole conversation. Later rounds should be quicker, because the reviewer already has the context, and we aim to answer them on the same day.

## Before you ask for a review

- [ ] CI is green, or the description says which check is failing and why.
- [ ] The change is under 400 lines, or labelled `large-change` with a reason.
- [ ] The description follows the template below.
- [ ] New behaviour has tests, and the tests fail without the change.
- [ ] The new path has logs, metrics and traces, following [logging and tracing](logging-and-tracing.md).
- [ ] You have read the diff yourself, in the code host, as a reviewer would.

The template is filled in automatically when you open a change:

```text
## Why
One or two sentences: the problem, and the Jira ticket.

## What
The approach, and anything a reviewer would not guess from the diff.

## Risk
What could break in production, and how we would notice.
Payments services: idempotency, retries, in-flight work, ledger balance.

## Testing
What you ran, locally and in staging.

## Rollout
Flag name, migration order, or "plain deploy".
```

## How to review

Read the description first, then the tests, then the code. The tests tell you what the author believes the change does; the code tells you whether they are right. Formatting and most questions of style belong to the linters, so do not spend comments on them.

What we look for, roughly in order of importance:

| Area | Questions to ask |
|---|---|
| Correctness | Does it do what the description says? What input breaks it? |
| Failure paths | What happens on a timeout, a partial failure, a retry? Is every error handled or deliberately passed up? |
| Idempotency | Does every write path take an idempotency key, as [ADR-008](../architecture/adr-008-idempotency-keys.md) requires? |
| Money | Is every amount an integer in minor units, as [ADR-017](../architecture/adr-017-money-minor-units.md) requires? |
| Data | Does the change log, store or send personal or cardholder data? See the [secure code review checklist](../security/secure-code-review.md). |
| Operability | Will on-call understand what happened from the logs and dashboards alone? |
| Design | Is this the simplest thing that works? Does it put logic where the next person will look for it? |
| Tests | Do they test behaviour rather than implementation? Would they catch a regression? |

### Two examples

A change to `payout-gateway` added a loop that submits a batch to the bank adapter:

```python
def submit_batch(self, batch: Batch) -> None:
    for payout in batch.payouts:
        self.bank.submit(payout)
```

A useful review comment:

> **blocking:** if `submit` raises on the tenth payout, the scheduler retries the whole batch and the first nine are submitted again. Could we pass `payout.idempotency_key` to `bank.submit`, so that the adapter returns the earlier result for payouts it has already accepted? A test that fails half-way through a batch and then retries would pin this down.

The comment names the failure, proposes a fix, and asks for the test that would have caught it. Compare a change to a handler in `card-auth`:

```go
func (h *Handler) Authorise(w http.ResponseWriter, r *http.Request) {
	req, err := decode(r)
	if err != nil {
		writeError(w, err)
		return
	}
	go h.audit.Record(context.Background(), req)
	res, err := h.auth.Authorise(r.Context(), req)
	// ...
}
```

> **blocking:** nothing waits for this goroutine, so the process can exit while an audit write is still in flight and records are lost on every deploy; and with `context.Background()` it ignores the request's deadline as well. The [coding standards](coding-standards.md) ask for an owner for every goroutine; could the audit write go through the existing buffered recorder, which drains on shutdown?
>
> **nit:** `req` is the decoded message, so `authReq` would read better next to `res`.

## Comment labels

Start each comment with a label, so that the author knows what is expected of them.

| Label | Meaning | Must the author act? |
|---|---|---|
| `blocking:` | This must change before merge | Yes |
| `question:` | I do not understand; the answer may lead to a change | Answer it |
| `suggestion:` | I would do this differently; your call | No |
| `nit:` | Trivial; take it or leave it | No |
| `praise:` | This is good; keep doing it | No |

Request changes only when there is at least one `blocking:` comment. Approve with comments when everything left is a suggestion or a nit, and trust the author to deal with them.

## Responding as the author

Reply to every blocking comment and every question, even if only with "done". Push follow-up commits rather than force-pushing during review, so that the reviewer can see what changed since they last looked; the change is squashed at merge, as the [Git conventions](git-conventions.md) describe. Resolve a thread only when the reviewer's point is addressed, and leave threads you disagree with open for the reviewer to close.

## When reviewer and author disagree

After two rounds of comments on the same point, stop typing and talk, in person or on a call. Most disagreements dissolve in five minutes of conversation. If they do not, the team's tech lead decides. If the disagreement is about architecture rather than this change, the change can usually merge as it stands while someone writes an ADR; see [ADR-001](../architecture/adr-001-record-decisions.md).

Whatever the outcome, record it in the thread, so that the next reader understands why the code looks the way it does.

## Special cases

- **Hotfixes.** The approval counts do not relax during an incident. Find a second reviewer in the incident channel; the [hotfix process](../release/hotfix-process.md) covers the rest.
- **Security-sensitive changes.** Authentication, authorisation, cryptography, secrets handling and anything that touches cardholder data: add the `security-review` label, which requests a reviewer from Security.
- **Front-end changes.** Attach before and after screenshots to the change, in both themes, and use Inkwell components rather than new ones; see [contributing to Inkwell](../design/contributing.md).
- **Code you did not write by hand.** Generated code, code from a coding assistant, or code copied from elsewhere is reviewed like any other. The author answers for every line.
- **Changes in another team's repository.** They need an approval from that team, whatever their size.

## How we know it works

The Lantern dashboard "engineering review health" shows, for each team, the median and 90th percentile time to first review, the distribution of change sizes, and the share of changes merged with the `large-change` label. The backend guild looks at it once a month. We do not use these numbers to rank people; we use them to notice when a team's rota is not working.
