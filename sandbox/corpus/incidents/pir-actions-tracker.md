---
title: "PIR actions tracker"
---

# PIR actions tracker

Every action agreed in a PIR becomes an ENG ticket labelled `pir-action`, as the
[PIR template](post-incident-review.md) requires. This page summarises them by
incident, lists what is still open, and is where Site Reliability looks before the
monthly review and quarterly planning.

Status as at **2026-10-20**, when Lukas Brennand last reviewed it. He updates it on the
first Monday of each month, and whenever an action changes state.

## Finding the tickets

The tickets are the source of truth; this page is a summary. The saved filter "PIR
actions, open" in the ENG project runs this query:

```text
project = ENG AND labels = pir-action AND statusCategory != Done ORDER BY duedate ASC
```

Drop the status clause to see closed actions too. Actions filed under an epic carry
it; most recent ones have no epic, because the epics that would have fitted had
already closed.

## Open actions

| Incident | Action | Owner | Planned for | Status |
|---|---|---|---|---|
| [2026-05-20, orders late](report-2026-05-20-orders-late.md) | Restart procedure for stalled `dw-ingest` consumers on the data on-call page | Hana Ostrowska | Due 2026-07-31 | In Progress, **overdue** |
| [2026-08-08, stale FX](report-2026-08-08-stale-fx.md) | Decide the permanent setting of `sb.fx-quote.refuse-stale-rates` | Nadia Ferreira | ENG Sprint 40 | In Progress |
| [2026-04-22, game day](game-day-2026-04.md) | Failback written up as its own runbook | Teodor Halloran | Before the next game day | In Progress |
| [2026-02-11, Hub login](report-2026-02-11-hub-login.md) | Sign-in completion rate in `merchant-hub`'s canary analysis | Malik Fairbairn | ENG Sprint 40 | In Progress |
| [2026-05-20, orders late](report-2026-05-20-orders-late.md) | `dw-ingest` consumers detect their own lack of progress and restart | Signe Abernethy | Backlog | To Do |
| [2026-08-08, stale FX](report-2026-08-08-stale-fx.md) | A second FX rate feed, with failover | Corinne Aske | Backlog | To Do |

Notes on the open items:

- The restart procedure slipped behind ENG-20, the backfill tooling epic, which has
  taken the Data Platform team's time since the summer. Tomasz Wilde will agree a new
  date at the next monthly review, once ENG-20's last sprint is over.
- The refuse-stale-rates decision is a policy question: whether a cross-currency
  payment should be declined rather than priced on a rate older than 60 seconds. The
  flag has been on since 2026-08-08 while it is decided.
- The second rate feed needs a new supplier contract, so it depends on Legal as much
  as on engineering.

## Summary by incident

| Incident | Level | Actions | Done | Open | Won't Do | Epics used |
|---|---|---|---|---|---|---|
| [2025-06-03, payouts delayed](report-2025-06-03-payouts-delayed.md) | SEV2 | 5 | 5 | 0 | 0 | ENG-1 |
| [2025-09-17, card authorisation latency](report-2025-09-17-card-auth-latency.md) | SEV1 | 5 | 5 | 0 | 0 | ENG-3, ENG-13 |
| [2025-12-02, ledger break](report-2025-12-02-ledger-break.md) | SEV3 | 4 | 4 | 0 | 0 | None |
| [2026-02-11, Hub login](report-2026-02-11-hub-login.md) | SEV2 | 5 | 4 | 1 | 0 | None |
| [2026-04-22, game day](game-day-2026-04.md) | SEV4 | 4 | 3 | 1 | 0 | None |
| [2026-05-20, orders late](report-2026-05-20-orders-late.md) | SEV3 | 5 | 3 | 2 | 0 | None |
| [2026-08-08, stale FX](report-2026-08-08-stale-fx.md) | SEV2 | 5 | 2 | 2 | 1 | None |
| **Total** | | **33** | **26** | **6** | **1** | |

The one Won't Do, a weekend review of low-urgency notifications in payments channels,
was superseded when the `FXQ-2002` alert was made to page.

## Recently closed

| Closed | Incident | Action |
|---|---|---|
| 2026-08-26 | 2025-09-17 | First SEV1 Beacon update drafted from a template, delivered by ENG-13 in ENG Sprint 36 |
| 2026-08-21 | 2026-08-08 | Page when `FXQ-2002` exceeds 1% of quotes for 2 minutes |
| 2026-08-14 | 2026-08-08 | Read deadline and heartbeat on the rate feed connection |
| 2026-07-09 | 2026-05-20 | Remove the ingestion alerts left over from the RabbitMQ era |
| 2026-06-25 | 2026-04-22 | Lantern dashboards follow the active region |

## How this list is used

- **Monthly.** Overdue actions are posted in `#team-sre` on the first Monday of the
  month, with their owners. An action overdue twice in a row goes to the head of the
  owning department.
- **Quarterly.** Open actions are an input to quarterly planning, so that they are
  staffed rather than squeezed in.
- **Before a game day.** Open actions from earlier game days are checked first; the
  failback runbook above must be done before the next one, planned for November.

To add or change an action, change the ticket, not this page. How incidents and PIRs
are run is on [production incident management](incident-management.md).
