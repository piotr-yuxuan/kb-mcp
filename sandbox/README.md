# Sandbox corpus: the world bible

This folder holds a fictional company's wiki and engineering tickets, seeded into the
sandbox site to evaluate search (plan 002, `docs/work/plans/002-sandbox-corpus.md`).
Everything here is invented. This file is the single reference for the facts that
pages, tickets and golden questions share: write against it, and change it first when
a shared fact changes.

- `corpus/<section>/<name>.md`: Confluence pages of the space `QM`; `corpus/index.md`
  is the space home, and each `index.md` a section page.
- `jira/eng/<epic>.yaml`: the tickets of the Jira project `ENG`, one file per epic.
- `jira/ideas/<name>.md`: the Jira Product Discovery ideas of the project `PRB`.
- `golden.yaml`: the golden questions.
- `seed_corpus.py`: seeds the sandbox, or checks it with `--check`.

## Writing rules

- British English, sentence-case headings, the voice of a working internal wiki. French
  pages are in French, with French typography.
- Markdown in GitHub's dialect: headings, tables, lists, fenced code blocks with a
  language (`bash`, `python`, `sql`, `yaml`, `json`, `go`, `typescript`, `text`), and
  alerts (`> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`) sparingly. No raw
  HTML, no images.
- Front matter: `title` in double quotes, and `lang: fr` on French pages.
- Links to other pages are relative paths to their files (`../people/onboarding.md`,
  or `refunds.md` within a section), with no `#anchor`. Other addresses use only
  `quillmoor.example` (and its subdomains) or `example.com`.
- No Unicode dashes (U+2013, U+2014): write "to" in ranges and a hyphen in compounds.
- No real organisation, commercial product or person, but Jira and Confluence, which
  host the corpus. Open-source technologies and public standards may be named (PostgreSQL, Apache Kafka, RabbitMQ, Kubernetes,
  Python, Go, React, OpenTelemetry, Trino, Apache Iceberg, WCAG, GDPR, SEPA, PCI DSS).
  Card networks are "the card schemes"; banks are "the issuer", "the acquiring bank",
  "our settlement bank". Chat is "chat" with channels such as `#inc-payments`; email
  is "email".
- An acronym is spelt out only on the page that defines it (see "Acronyms"); other
  pages use it bare and may link to that page.
- Nothing is dated after 2026-10-20, the corpus's "today".
- Long pages hold 1,500 to 3,000 words; short pages 300 to 1,500. Vary structure from
  page to page, as different authors would.
- A page holds every fact its brief lists under **Holds**, with numbers exactly as
  given, and none of those under **Not**: that is what keeps near-duplicates apart.

## The company

Quillmoor Ltd, founded in 2017, accepts card payments for online marketplaces and pays
out their sellers. About 420 staff: 300 in London (Quill House, floors 3 to 5), 60 in
Paris (Maison Lanterne, 4th floor), the rest remote in the UK and France. The fiscal
year runs from 1 April to 31 March. Products:
- **Quillmoor Pay**: card acceptance for marketplaces.
- **Quillmoor Payouts**: payouts to marketplace sellers, in GBP and EUR.
- **Merchant Hub**: the merchants' web dashboard.
- **Merchant API**: the public API, versioned by date (ADR-023).

### People (all invented)

The main people; pages and tickets add others, all invented too.

| Name | Role |
|---|---|
| Hollis Varga | Chief executive |
| Ottilie Marsh | Chief technology officer |
| Idris Kallenberg | Chief financial officer |
| Saoirse Lindqvist | General counsel |
| Beatrix Sallow | Data protection officer |
| Bram Oyelaran | Head of platform engineering |
| Nadia Ferreira | Head of payments engineering |
| Kwabena Stroud | Ledger team lead |
| Yusuf Achterberg | Payouts team lead |
| Lukas Brennand | Site reliability lead |
| Callum Ibe | Head of security |
| Tomasz Wilde | Data platform lead |
| Mireille Okonkwo | Head of risk and fraud machine learning |
| Priya Castellane | Design system lead |
| Rhiannon Dace | Head of people |
| Femi Haldane | Head of customer support |
| Inès Moreau | Support team lead, France |
| Élodie Vasseur | Paris office manager |
| Gwen Talbot | Workplace manager, London |
| Arjun Pelletier | Finance director |
| Ama Rowntree | Head of product |
| Oskar Ngata | Product manager, payouts |

### Teams and their chat channels

Payments Core (`#team-payments-core`), Payouts (`#team-payouts`), Ledger
(`#team-ledger`), Platform (`#team-platform`), Site Reliability (`#team-sre`), Security
(`#team-security`), Data Platform (`#team-data`), Risk ML (`#team-risk-ml`), Design
System (`#team-inkwell`), Merchant Experience (`#team-merchant-hub`), Merchant Support,
People, Legal, Finance, Workplace, Product. Incidents run in `#inc-<short name>`
channels. Role addresses: `payments-oncall@quillmoor.example`,
`security@quillmoor.example`, `phish@quillmoor.example`,
`privacy@quillmoor.example`, `people@quillmoor.example`,
`workplace@quillmoor.example`, `finance@quillmoor.example`,
`legal@quillmoor.example`.

### Services

| Service | Owner | What it does |
|---|---|---|
| `card-auth` | Payments Core | Card authorisation; p99 budget 800 ms |
| `payout-gateway` | Payouts | Sends payouts to sellers in batches every 15 minutes |
| `ledger` | Ledger | Double-entry ledger on PostgreSQL |
| `fx-quote` | Payments Core | Currency quotes, valid for 30 seconds |
| `settlement-batcher` | Payouts | Builds settlement files for our settlement bank |
| `merchant-api` | Merchant Experience | The public API |
| `merchant-hub` | Merchant Experience | The dashboard's web front end |
| `risk-scorer` | Risk ML | Serves the fraud model's scores |
| `notify` | Merchant Experience | Merchant emails and webhooks |

### Internal tools (all invented)

| Tool | What it is |
|---|---|
| Shipwright | Deployment pipeline and CLI (`shipwright deploy`, `shipwright rollback`, `shipwright exec`, `shipwright migrate`) |
| Switchboard | Feature flags (`sb.<service>.<flag>`) and kill switches (`ks.<service>.<feature>`) |
| Klaxon | Paging and on-call rotas; `/klaxon declare` opens an incident |
| Lantern | Dashboards, metrics and alerting, at `lantern.quillmoor.example` |
| Beacon | The public status page, `status.quillmoor.example` |
| Strongroom | The secrets manager |
| Conveyor | The data orchestrator and its CLI (`conveyor run`, `conveyor backfill`) |
| Kiln | The GPU cluster's scheduler |
| `modelctl` | The model registry's CLI |
| Inkwell | The design system, package `@quillmoor/inkwell` |
| Haven | The HR system: leave, absence, payroll documents |
| Perch | Desk, room and visitor booking |
| Tally | Expenses and purchase orders |
| Harbour | The support desk |
| Clausebook | Contract requests and the template library |
| Change Register | Change tickets for risky production changes, keyed `CHG-` |

### Identifiers

| Identifier | Meaning | Where it is explained |
|---|---|---|
| `PGW-5021 PAYOUT_BATCH_STUCK` | A payout batch has not been acknowledged by the bank after 10 minutes | `payments/payout-gateway-rollback` |
| `LDG-4091 UNBALANCED_JOURNAL` | A journal's debits and credits differ | `payments/ledger-reconciliation` |
| `LDG-4102 MISSING_SETTLEMENT_LINE` | A bank statement line has no ledger entry | `payments/ledger-reconciliation` |
| `CAU-1207 ISSUER_TIMEOUT` | The issuer did not answer within 3 seconds | `payments/card-auth-latency` |
| `CAU-1301 HSM_QUEUE_FULL` | The hardware security module queue is full | `payments/card-auth-latency` |
| `FXQ-2002 STALE_RATE` | A quote used a rate older than 60 seconds | `payments/fx-quote-service` |
| `DQ-017 FRESHNESS_BREACH` | A table missed its freshness deadline | `data/quality-alerts` |
| `DQ-031 ROW_COUNT_DRIFT` | Row count more than 25% off the 7-day median | `data/quality-alerts` |
| `DQ-044 SCHEMA_DRIFT` | An upstream column changed type or vanished | `data/quality-alerts` |
| `SCN-` findings | The secret scanner's findings, such as `SCN-7731` | `security/leaked-secret` |
| `CHG-2291` | The change ticket for the 2026 ledger schema migration | `release/change-tickets` |
| `CardAuthP99High` | Alert: `card-auth` p99 over 800 ms for 10 minutes | `payments/card-auth-latency` |
| `PayoutQueueBacklog` | Alert: more than 2,000 payouts queued | `payments/payout-gateway-rollback` |
| `LedgerReconBreak` | Alert: the nightly reconciliation found breaks | `payments/ledger-reconciliation` |
| `merchant_orders_daily` | Pipeline, ready by 06:00 UTC | `data/merchant-orders-daily` |
| `payouts_hourly`, `fraud_features_daily` | Pipelines | their pages in `data` |
| `fraudscore-v7`, `fraudscore-v6` | The current and previous fraud models | `ml` |

### Severity scales: three, never mixed

- **Production incidents, SEV1 to SEV4**, defined only in
  `incidents/incident-management`. SEV1: payments or payouts down for many merchants,
  or data lost. SEV2: a major degradation, or one product down. SEV3: a minor
  degradation with a workaround. SEV4: no merchant impact.
- **Security incidents, S1 to S4**, defined only in `security/incident-response-plan`.
  S1: confirmed exposure of cardholder or personal data. S2: an active compromise,
  with no data exposure confirmed. S3: a contained event of low impact. S4: suspicious
  and unconfirmed.
- **Support tickets, P1 to P4**, defined only in `support/priorities-and-slas`. P1: a
  merchant cannot take payments; first response within 15 minutes, at all hours. P2:
  a major function is impaired; 1 hour, in business hours. P3: 8 business hours. P4:
  2 business days.

### Acronyms: each defined on one page only

| Acronym | Meaning | Defined in |
|---|---|---|
| PAN, 3DS | primary account number; 3-D Secure | `payments/platform-architecture` |
| IC | incident commander | `incidents/incident-management` |
| PIR | post-incident review | `incidents/post-incident-review` |
| SLO | service level objective | `incidents/slo-catalogue` |
| SIRT | security incident response team | `security/incident-response-plan` |
| JML | joiners, movers and leavers | `security/access-reviews` |
| DPA, DSAR, SCCs, DPO | data processing agreement; data subject access request; standard contractual clauses; data protection officer | `legal/dpa-playbook` |
| MSA | master services agreement | `legal/msa-clause-guide` |
| KYC | know your customer | `support/kyc-queries` |
| FinOps | cloud financial operations | `finance/cloud-cost-allocation` |
| RTT | réduction du temps de travail | `people/conges-payes-rtt` |
| ADR | architecture decision record | `architecture/adr-001-record-decisions` |
| a11y | accessibility | `design/accessibility` |

### Synonyms kept apart

| One page says | Its neighbour or the question says |
|---|---|
| roll back, rollback (`payments/payout-gateway-rollback`, `ml/model-rollback`) | revert (`release/reverting-a-release`) |
| annual leave (`people/annual-leave-uk`), never "holiday" but in "bank holidays" | holiday, time off, vacation |
| post-incident review (`incidents/post-incident-review`), never "postmortem" | postmortem, retro |
| erasure request (`data/erasure-requests`), never "delete my data" or "right to be forgotten" | delete my data, forget me |
| backfill (`data/backfills`) | rerun or reprocess old data |
| desk booking (`workplace/desk-booking`), never "hot-desking" | hot desk, reserve a seat |

## Jira

### Project `ENG`, Quillmoor Engineering

Company-managed, with a Scrum board and a Kanban board. Sprint *n* (1 to 40) is named
"ENG Sprint *n*", starts on a Monday, 2025-04-14 plus 14 × (*n* - 1) days, and lasts
14 days: sprint 1 is 2025-04-14 to 2025-04-27, sprint 38 is 2026-09-14 to 2026-09-27,
sprint 39 is 2026-09-28 to 2026-10-11, and sprint 40, the active one, is 2026-10-12 to
2026-10-25. Statuses: To Do, In Progress, Done; a ticket abandoned is Done with the
resolution Won't Do.

Each epic file holds the epic and exactly 39 tickets. Epic *i* has key `ENG-i`, and its
tickets have keys `ENG-(31 + 39 × (i - 1))` to `ENG-(30 + 39 × i)`, in file order.

| Key | Epic | Sprints | Label | Notable tickets the epic must hold |
|---|---|---|---|---|
| ENG-1 | Payout-gateway resilience | 1 to 8 | payments | a bug: retry storm after `PGW-5021` in 4.12, fixed in 4.13; a story: cap batches at 500 payouts |
| ENG-2 | Ledger reconciliation hardening | 5 to 14 | payments | a bug: `LDG-4102` raised for refunds settled after midnight; a story: auto-clear breaks under £5 |
| ENG-3 | Card authorisation latency | 10 to 18 | payments | a story: issuer timeout lowered from 5 to 3 seconds; a bug: `CAU-1301` under load tests |
| ENG-4 | Multi-currency settlement | 15 to 24 | payments | a story: EUR settlement through SEPA with a 14:00 CET cut-off |
| ENG-5 | fx-quote rewrite | 20 to 28 | payments | a bug: `FXQ-2002` when the rate feed lags |
| ENG-6 | Self-serve refunds API | 26 to 34 | payments | a story: refunds over £10,000 need a second approver |
| ENG-7 | Shipwright canary analysis | 3 to 10 | platform | a story: canary 5% of traffic for 30 minutes |
| ENG-8 | Switchboard kill switches | 8 to 15 | platform | a story: audit log of every kill switch flip |
| ENG-9 | Kubernetes 1.31 upgrade | 16 to 20 | platform | a task: drain and upgrade node pools one region at a time |
| ENG-10 | Zero-downtime database migrations | 22 to 30 | platform | a story: lint migrations that drop a column in the same release |
| ENG-11 | Klaxon paging migration | 2 to 7 | sre | a task: move every rota to weekly hand-overs on Mondays at 10:00 |
| ENG-12 | SLO dashboards in Lantern | 12 to 19 | sre | a story: error budget burn alerts |
| ENG-13 | Beacon status page automation | 30 to 36 | sre | a story: post the first SEV1 update from a template |
| ENG-14 | Secrets rotation in Strongroom | 6 to 13 | security | a story: rotate production database credentials every 30 days |
| ENG-15 | Access review tooling | 18 to 25 | security | a story: revoke leavers' access within 24 hours automatically |
| ENG-16 | Hardware security keys for admins | 28 to 35 | security | a task: enrol every production administrator |
| ENG-17 | merchant_orders_daily rebuild | 1 to 9 | data | a story: move the run to 01:30 UTC |
| ENG-18 | Data quality alert framework | 9 to 17 | data | a story: `DQ-031` threshold set to 25% of the 7-day median |
| ENG-19 | Warehouse erasure automation | 24 to 32 | data | a story: apply erasure requests within 30 days |
| ENG-20 | Conveyor backfill tooling | 33 to 40 | data | a story: cap a backfill at 31 partitions per run |
| ENG-21 | fraudscore-v7 training pipeline | 4 to 12 | risk-ml | a story: train on a 13-month window |
| ENG-22 | Shadow mode and promotion gates | 13 to 21 | risk-ml | a story: 14 days in shadow mode before promotion |
| ENG-23 | Kiln GPU quotas | 25 to 31 | risk-ml | a story: preempt idle interactive jobs after 4 hours |
| ENG-24 | Inkwell tokens v2 | 7 to 14 | design-system | a story: rename colour tokens to `color.surface.*` |
| ENG-25 | Accessibility remediation | 19 to 27 | design-system | a bug: focus ring invisible on the destructive button |
| ENG-26 | Dark mode for Merchant Hub | 31 to 40 | merchant-hub | a story: switch theme with `data-theme="dark"` |
| ENG-27 | Harbour escalation workflow | 11 to 18 | support | a story: route P1 tickets to the payments on-call |
| ENG-28 | Chargeback evidence automation | 27 to 36 | support | a story: submit evidence 7 days before the scheme deadline |
| ENG-29 | Event log migration (ADR-019) | 14 to 26 | architecture | a task: dual-publish events during the migration |
| ENG-30 | Date-based API versioning (ADR-023) | 34 to 40 | architecture | a story: the `Quillmoor-Version` header |

Epics whose sprints end before 40 are Done, with every ticket Done (about one in
twenty Won't Do). Epics reaching sprint 40 (ENG-20, ENG-26, ENG-30) are In Progress:
about six in ten of their tickets are Done, the rest In Progress (in sprint 40) or To
Do (in the backlog).

### Ideas in `PRB` (Jira Product Discovery)

| Key | Summary | Cites |
|---|---|---|
| `jira/self-serve-payout-rollback` | Let payout operators roll back a payout-gateway release themselves | `payments/payout-gateway-rollback`, `release/reverting-a-release` |
| `jira/one-severity-scale` | One severity scale for incidents, security and support | `incidents/incident-management`, `security/incident-response-plan`, `support/priorities-and-slas` |
| `jira/automated-erasure` | Automate erasure requests end to end | `data/erasure-requests`, `legal/dpa-playbook` |
| `jira/dark-mode-dashboard` | Dark mode for every Merchant Hub page | `design/theming` |
| `jira/carry-over-tracker` | Show each employee's leave carry-over balance | `people/annual-leave-uk`, `people/conges-payes-rtt` |

## Page map

`L` marks a long page, `S` a short one. Section pages (`index.md`) hold one sentence
and the list of their children.

### `payments`: Payments platform

- `platform-architecture` L "Payments platform architecture". **Holds:** the services
  table above; defines PAN and 3DS; `card-auth` p99 budget 800 ms; `payout-gateway`
  batches every 15 minutes; `fx-quote` quotes valid 30 seconds; the ledger is
  double-entry on PostgreSQL; PANs never leave the card data environment.
- `payout-gateway-rollback` L "Runbook: rolling back payout-gateway". **Holds:** roll
  back when `PGW-5021` errors exceed 2% of batches for 5 minutes after a deploy, or
  `PayoutQueueBacklog` fires; first pause the scheduler with
  `ks.payout-gateway.batch-scheduler`; then drain the payout queue, since in-flight
  batches would be resubmitted and paid twice
  (`shipwright exec payout-gateway -- pgw-admin drain --wait`); then
  `shipwright rollback payout-gateway --to <release>`; never roll back across a ledger
  schema migration without the Ledger team; links to `incidents/on-call` and
  `release/database-migrations`. **Not:** the word "revert".
- `ledger-reconciliation` L "Runbook: ledger reconciliation breaks". **Holds:** the
  `recon-daily` job runs at 02:00 UTC; `LDG-4091` and `LDG-4102`; alert
  `LedgerReconBreak`; breaks under £5 in total are cleared automatically; unexplained
  amounts go to the suspense account `9999-SUSPENSE`; breaks older than 3 business days
  go to the finance controller.
- `card-auth-latency` L "Runbook: card authorisation latency". **Holds:**
  `CardAuthP99High`; `CAU-1207` and `CAU-1301`; the Lantern dashboard "card-auth
  overview"; reduce 3DS step-up sampling with `sb.card-auth.stepup-sampling`; scale
  `card-auth` between 12 and 40 pods.
- `settlement-cutoffs` L "Settlement windows and cut-off times". **Holds:** a table by
  currency; GBP same-day cut-off 15:30 UK time; EUR (SEPA) 14:00 CET; a batch after the
  cut-off settles the next business day; weekends and bank holidays.
- `glossary` S "Payments glossary": authorisation, capture, settlement, payout,
  interchange, chargeback. **Not:** PAN or 3DS spelt out.
- `teams` S "Payments engineering teams": Payments Core, Payouts, Ledger; leads and
  channels.
- `release-notes-payout-gateway-4-10` S "payout-gateway 4.10 release notes", and `-4-11`,
  `-4-12`, `-4-13`, S each, alike in shape. 4.12 caps batches at 500 payouts; 4.13
  fixes the retry storm after `PGW-5021` (ENG-1's bug).
- `weekly-sync-2026-08-04` S "Payments weekly sync 2026-08-04", and `-2026-08-18`,
  `-2026-09-01`, `-2026-09-15`: attendees, decisions, actions with ENG keys. The
  2026-09-01 sync decides to add a 30-minute buffer before the EUR cut-off.
- `replay-webhook` S "How to replay a merchant webhook": `notify-admin replay
  --event-id`.
- `test-merchants` S "Test merchants and test cards": the sandbox merchant accounts; no
  card numbers.
- `fx-quote-service` S "fx-quote service": `FXQ-2002 STALE_RATE`; quotes valid 30
  seconds.
- `payout-holds` S "Payout holds and releases": new sellers' payouts are held 7 days;
  Risk releases holds.

### `release`: Release engineering

- `deployment-pipeline` L "How code reaches production". **Holds:** Shipwright stages
  build, test, staging, canary, full rollout; the canary takes 5% of traffic for 30
  minutes; deploy windows Monday to Thursday 09:00 to 16:00 UK time; high-risk changes
  need a `CHG-` ticket.
- `reverting-a-release` L "Reverting a bad release". **Holds:** prefer a revert commit
  through the pipeline; for urgency, redeploy the previous release with Shipwright;
  roll forward instead when the release ran a database migration; a decision table.
  **Not:** draining queues, payout-gateway, models.
- `feature-flags` L "Feature flags and kill switches". **Holds:** Switchboard naming
  `sb.<service>.<flag>` and `ks.<service>.<feature>`; remove a flag within 90 days of
  full rollout; a kill switch flip needs no deploy and is logged.
- `database-migrations` L "Database migrations". **Holds:** expand then contract; never
  drop a column in the release that stops using it; `shipwright migrate`; down
  migrations exist but are a last resort.
- `change-freeze-2025` S "Change freeze calendar 2025": 24 November to 2 December 2025
  and 18 December 2025 to 5 January 2026.
- `change-freeze-2026` S "Change freeze calendar 2026": 23 November to 1 December 2026
  and 17 December 2026 to 4 January 2027; exceptions need a `CHG-` ticket approved by
  the head of platform engineering.
- `change-tickets` S "Raising a change ticket": the Change Register; `CHG-2291`.
- `shipwright-cheatsheet` S "Shipwright CLI cheat sheet".
- `canary-analysis` S "Canary analysis thresholds": fail when the error rate rises 0.5
  points or p99 rises 20%.
- `hotfix-process` S "Hotfix process".
- `release-train-faq` S "Release train FAQ".
- `staging-environments` S "Staging environments": `staging-eu`, data refreshed weekly.
- `build-cache` S "Build cache troubleshooting".
- `dependency-updates` S "Dependency update policy".
- `flag-cleanup-2026-q3` S "Flag clean-up report Q3 2026".

### `incidents`: Incidents and on-call

- `incident-management` L "Production incident management". **Holds:** SEV1 to SEV4 as
  above; defines IC; declare with `/klaxon declare`; a PIR within 5 business days for
  SEV1 and SEV2.
- `on-call` L "On-call rota and paging policy". **Holds:** acknowledge a SEV1 page
  within 5 minutes, a SEV2 within 15; rotas hand over on Mondays at 10:00; an allowance
  of £250 per week on call; time off in lieu after a call-out after 23:00; swaps
  agreed in Klaxon at least 24 hours ahead.
- `post-incident-review` L "Post-incident review template". **Holds:** defines PIR;
  blameless; sections of the template; actions are ENG tickets labelled `pir-action`;
  the review meets within 5 business days of resolution. **Not:** "postmortem".
- `status-page` L "Status page communications". **Holds:** Beacon; first update within
  15 minutes of a SEV1, then every 30 minutes; the IC and the communications lead
  approve updates; templates.
- `report-2025-06-03-payouts-delayed` S "Incident report 2025-06-03: payouts delayed":
  SEV2, `PGW-5021`.
- `report-2025-09-17-card-auth-latency` S "Incident report 2025-09-17: card
  authorisation latency": SEV1, `CAU-1207`.
- `report-2025-12-02-ledger-break` S "Incident report 2025-12-02: ledger
  reconciliation break": SEV3, `LDG-4091`.
- `report-2026-02-11-hub-login` S "Incident report 2026-02-11: Merchant Hub login
  outage": SEV2.
- `report-2026-05-20-orders-late` S "Incident report 2026-05-20: merchant_orders_daily
  late": SEV3, `DQ-017`.
- `report-2026-08-08-stale-fx` S "Incident report 2026-08-08: stale FX quotes": SEV2,
  `FXQ-2002`.
- `klaxon-setup` S "Setting up Klaxon on your phone".
- `handover-checklist` S "On-call handover checklist".
- `slo-catalogue` S "SLO catalogue": defines SLO; `card-auth` 99.95%,
  `payout-gateway` 99.9%, `merchant-api` 99.9%.
- `roles-quick-reference` S "Incident roles quick reference".
- `escalation-contacts` S "Escalation contacts for incidents".
- `game-day-2026-04` S "Game day April 2026: region failover".
- `pir-actions-tracker` S "PIR actions tracker": ENG keys labelled `pir-action`.

### `security`: Security

- `incident-response-plan` L "Security incident response plan". **Holds:** S1 to S4 as
  above; defines SIRT; the regulator is told within 72 hours of awareness, through the
  DPO; `security@quillmoor.example`; links to `legal/dpa-playbook`.
- `leaked-secret` L "Playbook: leaked secret or API key". **Holds:** rotate in
  Strongroom first, then revoke the old value; production secrets within 1 hour;
  scanner findings such as `SCN-7731`; merchant API keys revoked through the
  `merchant-api` admin console.
- `phishing` L "Playbook: reported phishing". **Holds:** the "Report phish" button;
  `phish@quillmoor.example`; if credentials were entered, reset the password and revoke
  sessions; S3 by default, S2 for an administrator.
- `access-reviews` L "Quarterly access reviews". **Holds:** defines JML; reviews in
  January, April, July and October; managers certify within 10 business days; leavers
  lose access within 24 hours.
- `password-and-mfa` S "Password and MFA standard": hardware security keys for
  administrators.
- `laptop-baseline` S "Laptop security baseline": disk encryption; lock after 5
  minutes.
- `vulnerability-slas` S "Vulnerability management SLAs": critical 7 days, high 30,
  medium 90.
- `secure-code-review` S "Secure code review checklist".
- `security-faq` S "Security FAQ".
- `data-classification` S "Data classification": Public, Internal, Confidential,
  Restricted; cardholder data is Restricted.
- `strongroom-how-to` S "Using Strongroom".
- `pen-test-2026` S "Penetration test 2026 summary".
- `travel-with-devices` S "Travelling with company devices".
- `vendor-security-review` S "Vendor security review".

### `data`: Data platform

- `platform-overview` L "Data platform overview". **Holds:** Apache Iceberg tables
  queried with Trino; layers `raw`, `staging`, `marts`; Conveyor runs the pipelines.
- `merchant-orders-daily` L "Pipeline: merchant_orders_daily". **Holds:** runs at 01:30
  UTC, ready by 06:00 UTC; writes `marts.merchant_orders_daily`; owned by Data
  Platform; its quality checks.
- `backfills` L "Backfilling historical partitions". **Holds:** `conveyor backfill
  merchant_orders_daily --from 2026-01-01 --to 2026-01-31`; at most 31 partitions per
  run; never between 00:00 and 06:00 UTC.
- `quality-alerts` L "Data quality alerts". **Holds:** `DQ-017`, `DQ-031`, `DQ-044` as
  above; a late finance mart is handled as a SEV3.
- `erasure-requests` L "Erasure requests in the warehouse". **Holds:** uses DSAR and DPA
  bare; GDPR Article 17; applied within 30 days; logged in `privacy.erasure_log`;
  backups expire after 35 days; links to `legal/dpa-playbook`. **Not:** "delete my
  data", "right to be forgotten".
- `pipeline-payouts-hourly` S "Pipeline: payouts_hourly".
- `pipeline-fraud-features-daily` S "Pipeline: fraud_features_daily".
- `warehouse-access` S "Requesting warehouse access".
- `naming-conventions` S "Warehouse naming conventions".
- `writing-a-dag` S "Writing a Conveyor DAG".
- `sql-style-guide` S "SQL style guide".
- `table-ownership` S "Data catalogue and table ownership".
- `query-costs` S "Keeping warehouse queries cheap".
- `office-hours-2026-07` S "Data office hours notes July 2026", and
  `office-hours-2026-09` S "Data office hours notes September 2026".
- `retention-schedule` S "Data retention schedule": payment records 7 years;
  application logs 90 days.
- `personal-data-columns` S "Tagging personal data columns".
- `data-on-call` S "Data platform on-call".

### `ml`: Machine learning

- `fraud-model-training` L "Training the fraud model". **Holds:** `fraudscore-v7`,
  gradient-boosted trees with a sequence embedding trained on Kiln; features from
  `fraud_features_daily`; a 13-month training window; labels wait 60 days for
  chargebacks.
- `evaluation-and-promotion` L "Model evaluation and promotion". **Holds:** AUC-PR and
  recall at a 0.5% decline rate; a challenger must beat the champion by 2 points of
  recall at that rate; 14 days in shadow mode; sign-off by the head of risk ML.
- `model-rollback` L "Rolling back a model in production". **Holds:** `modelctl pin
  fraudscore --version v6`; takes effect within 2 minutes, with no deploy; tell Risk
  Operations; roll back when the decline rate jumps more than 30%. **Not:**
  `shipwright rollback`, queues.
- `gpu-cluster` L "GPU cluster quotas and scheduling". **Holds:** Kiln queues
  `train-long`, `train-short`, `interactive`; 8 GPUs per team by default; idle
  interactive jobs preempted after 4 hours.
- `model-card-fraudscore-v7` S "Model card: fraudscore-v7", and
  `model-card-fraudscore-v6` S "Model card: fraudscore-v6", alike in shape.
- `feature-store` S "Feature store guide".
- `experiment-2026-03-sequence-features` S "Experiment notes: sequence features (March
  2026)".
- `experiment-2026-06-merchant-graph` S "Experiment notes: merchant graph features (June
  2026)".
- `chargeback-labels` S "Labelling fraud from chargebacks".
- `notebooks` S "Notebook environment".
- `reading-group` S "ML reading group notes".
- `risk-ops-reviews` S "Risk operations: reviewing declined payments".
- `drift-monitoring` S "Model drift monitoring".

### `design`: Design system

- `tokens` L "Inkwell design tokens and principles". **Holds:** tokens such as
  `color.surface.raised`; a spacing scale in steps of 4 px; principles.
- `button` L "Button component". **Holds:** variants primary, secondary, tertiary,
  destructive; a destructive action asks for confirmation; the loading state.
- `accessibility` L "Accessibility checklist". **Holds:** WCAG 2.2 AA; defines a11y;
  contrast 4.5:1 for text and 3:1 for interface parts; targets at least 24 by 24 CSS
  pixels; focus always visible.
- `theming` L "Theming and dark mode". **Holds:** `data-theme="dark"`; every colour
  through tokens; testing both themes.
- `text-field` S "Text field component", `modal` S "Modal dialog component", `toast` S
  "Toast notification component", `data-table` S "Data table component".
- `icons` S "Icon library".
- `contributing` S "Contributing to Inkwell".
- `release-notes-inkwell-3-0` S "Inkwell 3.0 release notes", `release-notes-inkwell-3-2`
  S "Inkwell 3.2 release notes".
- `design-review` S "Design review ritual".
- `content-style` S "Content style guide": British English, sentence case.
- `motion` S "Motion guidelines".

### `people`: People and HR

- `onboarding` L "New joiner onboarding: your first two weeks". **Holds:** uses JML
  bare; a buddy; the laptop on day one; links to `annual-leave-uk`,
  `../finance/expenses.md`, `../workplace/desk-booking.md` and
  `../security/access-reviews.md`.
- `annual-leave-uk` L "Annual leave policy (UK)". **Holds:** 27 days a year plus bank
  holidays; the leave year is the calendar year; carry over up to 8 days, to be used
  by 31 March; book in Haven; two weeks' notice for more than 5 consecutive days;
  effective from 1 January 2024. **Not:** "holiday" outside "bank holidays".
- `annual-leave-uk-2022` L "Annual leave policy 2022 (UK)". **Holds:** a warning alert
  that it was superseded on 1 January 2024 by `annual-leave-uk`; 25 days a year; carry
  over up to 5 days, used by 28 February.
- `conges-payes-rtt` L, French, "Congés payés et RTT (France)". **Holds:** defines RTT;
  25 jours ouvrés de congés payés; 10 jours de RTT par an; report jusqu'au 31 mai; pose
  dans Haven.
- `parental-leave` L "Parental leave policy". **Holds:** 20 weeks at full pay for the
  primary carer; 6 weeks at full pay for the other parent; shared parental leave.
- `sickness-absence` L "Sickness absence". **Holds:** tell your manager by 10:00;
  self-certify up to 7 calendar days, then a fit note; 10 days at full pay a year.
- `benefits-uk` S "Benefits in the UK": private medical insurance; pension with 6%
  employer contribution.
- `mutuelle-et-prevoyance` S, French, "Mutuelle et prévoyance (France)".
- `performance-reviews` S "Performance reviews": April and October.
- `learning-budget` S "Learning budget": £1,000 a year.
- `working-abroad` S "Working from abroad": up to 20 working days a year.
- `payroll-dates` S "Payroll dates": paid on the 25th.
- `time-off-faq` S "Time off FAQ": points to the policies. **Not:** day counts or
  carry-over limits.
- `referral-scheme` S "Employee referral scheme": £2,000.
- `probation` S "Probation period": 3 months.
- `haven-how-to` S "Using Haven".
- `wellbeing` S "Wellbeing support".
- `leaving` S "Leaving Quillmoor".

### `legal`: Legal

- `nda` L "Mutual NDA: template and guidance".
- `msa-clause-guide` L "MSA clause guide". **Holds:** defines MSA; liability capped at
  12 months' fees; 24 months for strategic merchants with the general counsel's
  approval.
- `dpa-playbook` L "DPA playbook". **Holds:** defines DPA, DSAR, SCCs and DPO; answer a
  DSAR within one month; tell affected merchants of a breach within 48 hours, by
  contract; the sub-processor list.
- `contract-signature-authority` L "Contract signature authority". **Holds:** total
  contract value under £50,000: the head of department signs; £50,000 to £250,000: the
  CFO; over £250,000: the chief executive, after Legal's review. **Not:** purchase
  order thresholds.
- `contract-requests` S "Requesting a contract review": Clausebook.
- `template-library` S "Contract template library".
- `brand-use` S "Using the Quillmoor name and logo".
- `open-source-licences` S "Open-source licence policy": MIT, Apache 2.0 and BSD
  allowed; GPL needs Legal's review.
- `gifts-and-hospitality` S "Gifts and hospitality": register gifts over £50.
- `anti-bribery` S "Anti-bribery policy".
- `whistleblowing` S "Whistleblowing".
- `legal-faq` S "Legal FAQ".

### `workplace`: Workplace

- `london-office` L "London office guide". **Holds:** Quill House, floors 3 to 5; open
  07:00 to 21:00; Wi-Fi `QM-Staff` and `QM-Guest`; 40 bicycle spaces.
- `bureau-de-paris` L, French, "Bureau de Paris : guide pratique". **Holds:** Maison
  Lanterne, 4e étage; ouvert de 8 h à 20 h; Wi-Fi `QM-Staff`; badge.
- `desk-booking` L "Desk booking and hybrid working". **Holds:** Perch; team days on
  Tuesday and Thursday; book up to 14 days ahead; a desk not checked into by 10:00 is
  released. **Not:** "hot-desking".
- `visitors-and-deliveries` L "Visitors and deliveries". **Holds:** register visitors in
  Perch 24 hours ahead; deliveries to reception; large deliveries through the loading
  bay.
- `london-office-faq` S "London office FAQ", and `faq-bureau-de-paris` S, French, "FAQ
  du bureau de Paris".
- `fire-safety` S "Fire safety and evacuation".
- `meeting-rooms` S "Meeting rooms".
- `floor-5-refurbishment` S "Office notice: floor 5 refurbishment".
- `lost-property` S "Lost property".
- `first-aiders` S "First aiders and the wellbeing room".
- `business-travel` S "Booking business travel".

### `support`: Customer support

- `escalation` L "Support escalation playbook". **Holds:** tiers T1, T2 and T3; when to
  page the payments on-call; Harbour.
- `refunds` L "Handling merchant refund requests". **Holds:** a refund within 180 days
  of the payment; partial refunds; refunds over £10,000 need T2 approval. **Not:** the
  dispute fee.
- `remboursements-marchands` L, French, "Traiter une demande de remboursement
  (marchands français)". **Holds:** dans les 180 jours; au-delà de 10 000 €, validation
  par le niveau T2.
- `chargebacks` L "Chargebacks and disputes". **Holds:** submit evidence at least 7
  calendar days before the scheme's deadline; a dispute fee of £15. **Not:** the
  refund window.
- `priorities-and-slas` L "Ticket priorities and SLAs". **Holds:** P1 to P4 as above.
- `macros` S "Support macros".
- `harbour-how-to` S "Using Harbour".
- `kyc-queries` S "Answering KYC queries": defines KYC.
- `payout-delay-faq` S "Payout delays: what to tell merchants".
- `data-subject-requests` S "Forwarding data subject requests": uses DSAR bare;
  `privacy@quillmoor.example`.
- `strategic-merchants` S "Strategic merchants".
- `weekly-review-2026-09` S "Support weekly review September 2026", and
  `weekly-review-2026-10` S "Support weekly review October 2026".
- `csat` S "Customer satisfaction surveys".
- `shift-patterns` S "Support shift patterns".
- `merchant-fraud-reports` S "Merchants reporting fraud".
- `french-speaking-merchants` S "Supporting French-speaking merchants".

### `finance`: Finance

- `budget-cycle` L "Annual budget cycle". **Holds:** the fiscal year from 1 April;
  draft budgets due 15 January; board approval in March; reforecasts in the second and
  third quarters.
- `spend-approval` L "Spend approval matrix". **Holds:** purchase orders under £10,000:
  the budget holder; £10,000 to £100,000: the finance director; over £100,000: the
  CFO; software needs Security's review. **Not:** contract signature thresholds.
- `expenses` L "Expenses policy". **Holds:** claim within 60 days in Tally; receipts
  above £10; taxis after 21:00; hotels capped at £180 a night in London and £140
  elsewhere in the UK.
- `notes-de-frais` L, French, "Notes de frais (France)". **Holds:** sous 60 jours dans
  Tally; justificatif au-delà de 10 €; hôtel plafonné à 190 € la nuit à Paris; taxi
  après 21 h.
- `cloud-cost-allocation` L "Cloud cost allocation and tagging". **Holds:** defines
  FinOps; tags `cost-centre`, `service`, `env`; untagged costs land in `CC-9000
  Unallocated`; a monthly review.
- `month-end-close` S "Month-end close calendar": closed by the fifth working day.
- `corporate-cards` S "Corporate cards".
- `paying-suppliers` S "Paying suppliers": 30-day terms.
- `finance-faq` S "Finance FAQ".
- `cost-centres` S "Cost centre list".
- `per-diems` S "Travel per diems".
- `vat-on-expenses` S "VAT on expenses".
- `headcount-planning` S "Headcount planning".
- `purchase-orders` S "Raising a purchase order in Tally".

### `architecture`: Architecture decisions

- `adr-007-message-broker` L "ADR-007: Publish domain events through a message broker".
  **Holds:** a warning alert that ADR-019 superseded it; RabbitMQ topic exchanges;
  events kept only until consumed.
- `adr-012-database-per-service` L "ADR-012: One database per service".
- `adr-019-replicated-event-log` L "ADR-019: Move domain events to a replicated log".
  **Holds:** Apache Kafka; events kept 7 days; consumers track their offsets; the
  migration is epic ENG-29.
- `adr-023-api-versioning` L "ADR-023: Version public APIs by date". **Holds:** the
  header `Quillmoor-Version: 2026-04-01`; each version supported for 24 months.
- Short ADRs: `adr-001-record-decisions` "ADR-001: Record architecture decisions"
  (defines ADR), `adr-002-python-back-office` "ADR-002: Python for back-office
  services", `adr-003-go-latency-critical` "ADR-003: Go for latency-critical services",
  `adr-004-postgresql` "ADR-004: PostgreSQL as the default database",
  `adr-005-repository-per-team` "ADR-005: One repository per team",
  `adr-008-idempotency-keys` "ADR-008: Idempotency keys on every write API",
  `adr-010-kubernetes` "ADR-010: Run services on Kubernetes",
  `adr-011-opentelemetry` "ADR-011: OpenTelemetry for tracing",
  `adr-014-build-switchboard` "ADR-014: Build Switchboard for feature flags",
  `adr-016-no-graphql` "ADR-016: Do not adopt GraphQL for the Merchant API"
  (rejected), `adr-017-money-minor-units` "ADR-017: Represent money in integer minor
  units", `adr-020-strongroom` "ADR-020: Strongroom as the only secrets store",
  `adr-021-active-passive-regions` "ADR-021: Active-passive multi-region",
  `adr-024-react-merchant-hub` "ADR-024: React for Merchant Hub".

### `engineering`: Engineering handbook

- `code-review` L "Code review guidelines". **Holds:** two approvals for payments
  services, one elsewhere; a first review within one business day; changes under 400
  lines.
- `coding-standards` L "Coding standards".
- `local-development` L "Local development environment". **Holds:** `qm dev up`;
  development containers; seed data.
- `git-conventions` S "Git conventions", `testing-strategy` S "Testing strategy",
  `api-design` S "API design guidelines", `logging-and-tracing` S "Logging and tracing",
  `tech-debt` S "Managing technical debt", `continuous-integration` S "Continuous
  integration", `career-ladder` S "Engineering career ladder", `interviewing` S
  "Interviewing engineers", `new-engineer-checklist` S "New engineer checklist".
- `guild-backend-2026-06` S "Backend guild notes June 2026", `guild-backend-2026-09` S
  "Backend guild notes September 2026", `guild-frontend-2026-07` S "Frontend guild
  notes July 2026".
- `retro-sprint-38` S "ENG Sprint 38 retrospective", `retro-sprint-39` S "ENG Sprint 39
  retrospective": with sprint dates and ENG keys.

### `product`: Product and roadmap

- `roadmap-2026` L "Product roadmap 2026".
- `quarterly-planning` L "Quarterly planning process".
- `merchant-hub-release-notes-2026` L "Merchant Hub release notes 2026".
- `brief-self-serve-refunds` S "Product brief: self-serve refunds API",
  `brief-dark-mode` S "Product brief: dark mode for Merchant Hub",
  `brief-instant-payouts` S "Product brief: instant payouts",
  `brief-multi-currency` S "Product brief: multi-currency settlement".
- `okrs-2026-q3` S "OKRs Q3 2026", `okrs-2026-q4` S "OKRs Q4 2026".
- `merchant-interviews-2026-05` S "Merchant interviews May 2026".
- `pricing` S "Pricing overview".
- `launch-checklist` S "Launch checklist".
- `terminology` S "Product terminology".
- `discovery-process` S "Product discovery and the ideas board": the ideas in the
  Product Discovery project `PRB`.

## Seeding and checking

The sandbox site needs Confluence, Jira and Jira Product Discovery (all on the Free
plan), and the Product Discovery project `PRB`. `seed_corpus.py` does the rest, through
the sandbox token, which sops gives to that process alone. With `C` the absolute path of
`atlassian-test-credientials.sops.json`:

```bash
sops exec-env "$C" 'uv run sandbox/seed_corpus.py --import-file /tmp/eng-tickets.csv'
```

A run brings the site in line with the repository, then says what is left to do:

1. It creates the space `QM` if it is absent, then creates, updates or leaves each page:
   a page is left alone when its title, parent and body are what the corpus gives and
   nobody has edited it since. Pages it does not know are reported, never deleted.
2. It creates or updates the five ideas in `PRB`, found by summary.
3. It creates the project `ENG` with its Scrum board, a Kanban board and the 40 sprints.
4. It writes the tickets absent from `ENG` to the import file, in Jira's CSV format.
   Jira's REST API cannot backdate tickets; its CSV importer can. Import the file as a
   Jira administrator: Settings, System, External System Import, CSV, in the older
   experience. Choose the project `ENG`, the date format `yyyy-MM-dd HH:mm`, and map
   each column to the field of the same name (Work Item Key, Work item ID, Parent,
   Summary, Work Type, Status, Resolution, Priority, Date Created, Date Resolved,
   Sprint, Description, Labels, Comment). The importer keeps the keys; it sets every
   ticket's `updated` date to the time of the import.
5. Once every ticket is in, the next run starts and closes sprints 1 to 39 in order,
   and starts sprint 40. Jira stamps each closed sprint with the time it was closed.

Run it again until it reports nothing to do; a rerun after a failure resumes where it
stopped. Then check, which writes nothing and exits 1 on any difference:

```bash
sops exec-env "$C" 'uv run sandbox/seed_corpus.py --check'
```

It compares every page, its links and its section; every idea; every ticket's summary,
status, resolution, creation date and sprint; and it lists pages with their versions and
tickets with their `updated` dates, so that two listings can be compared.

A page is left alone when the hash of the storage format that pandoc writes for it is
the one recorded on the page, so the pandoc version matters: another version may write
other HTML for the same Markdown. Each page records the pandoc version that wrote it,
and `--check` names it when a page would change. The sandbox was seeded with pandoc
3.7.0.2.

The tests need pandoc on `PATH`:

```bash
uv run --with-requirements sandbox/seed_corpus.py --with pytest pytest sandbox
```
