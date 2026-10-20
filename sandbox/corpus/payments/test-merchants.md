---
title: "Test merchants and test cards"
---

> [!NOTE]
> This page contains no card numbers, and never will. See "Test cards" below for where to find them.

Maintained by Payments Core. Last reviewed 2026-09-21.

The merchant sandbox, at `sandbox.quillmoor.example` with its API at `api.sandbox.quillmoor.example`, is the copy of Quillmoor Pay and Quillmoor Payouts that merchants integrate against. It runs the same services as production, against a simulated acquiring bank, simulated issuers and a simulated settlement bank. No real money moves. Engineers use it to reproduce merchant problems and to try a flow end to end without a staging deploy.

## Sandbox merchant accounts

These accounts belong to us and are shared by every team. Do not change their settings without saying so in `#team-payments-core`.

| Merchant ID | Name | Country | Currency | Use it for |
|---|---|---|---|---|
| `mer_test_gb_marketplace` | Quillmoor Test Marketplace GB | United Kingdom | GBP | Everyday card payments and GBP payouts |
| `mer_test_fr_marketplace` | Marché d'essai FR | France | EUR | SEPA payouts, French-language emails |
| `mer_test_multi` | Test Multi-Currency Ltd | United Kingdom | GBP and EUR | Cross-currency payments and `fx-quote` |
| `mer_test_risky` | Test High-Risk Goods | United Kingdom | GBP | High `risk-scorer` scores, 3DS step-ups, declines |
| `mer_test_new_sellers` | Test New Sellers | United Kingdom | GBP | Sellers recreated each night, so new-seller holds apply |
| `mer_test_webhooks_down` | Test Broken Endpoint | United Kingdom | GBP | An endpoint that always answers 503, for webhook retries and replays |

Each account has a Merchant Hub login on `example.com`, such as `test-gb@example.com`. The passwords and API keys are in Strongroom under `payments/sandbox/merchants`, never on the wiki or in chat; see [Using Strongroom](../security/strongroom-how-to.md).

Every Sunday at 03:00 UTC the sandbox resets these accounts: payments, payouts and balances from the past week are cleared, sellers are recreated, and settings go back to their defaults.

## Test cards

The sandbox accepts only the card schemes' published test numbers. We keep them, with the behaviour each triggers, in `card-auth`'s repository at `fixtures/test_cards.yaml`. That file is the only place they live at Quillmoor.

Why not here? The rule for the card data environment is that a PAN never leaves it, and we apply the same habit to anything that looks like one. A wiki page full of sixteen-digit numbers teaches people to paste sixteen-digit numbers into tickets and chat, and nobody reading a ticket can tell a test number from a real one. So we refer to test cards by **scenario**, never by number:

| Scenario | What the simulated issuer does |
|---|---|
| `approve` | Approves at once |
| `decline_insufficient_funds` | Declines with an insufficient funds reason |
| `decline_stolen` | Declines as reported stolen |
| `issuer_timeout` | Does not answer, so `card-auth` returns `CAU-1207` after 3 seconds |
| `stepup_challenge` | Requires a 3DS step-up; the sandbox challenge page accepts the code shown on it |
| `stepup_frictionless` | Completes 3DS without a challenge |
| `chargeback_fraud` | Approves, then raises a fraud chargeback 10 minutes after capture |

In tickets and chat, write "the `issuer_timeout` card", not a number.

## Payouts in the sandbox

The simulated settlement bank acknowledges batches after about 30 seconds and settles them at once, whatever the time or the calendar, so cut-offs cannot be tested here. To see a stuck batch, pay out to the seller `sel_test_stuck` on `mer_test_gb_marketplace`: its batches are never acknowledged and raise `PGW-5021` after 10 minutes.

## Common problems

**"Authentication failed" on the sandbox API.** Sandbox keys start with `qm_test_` and only work against `api.sandbox.quillmoor.example`. A production key there, or a sandbox key in production, fails the same way. Check the prefix before anything else.

**A card scenario behaves like `approve` whatever you do.** The scenario is chosen by the card number, so a number copied from somewhere other than `fixtures/test_cards.yaml` is probably not a test number the simulated issuer recognises. It falls back to approving. Copy from the fixture.

**The account looks empty on a Monday.** The weekly reset ran. Anything you need to keep for longer, such as a reproduction for a bug, should be scripted so that it can be recreated after each reset; `card-auth`'s repository has examples under `scripts/sandbox/`.

**Someone changed the settings of a shared account.** It happens. Post in `#team-payments-core`, put the setting back, and if you need an unusual configuration for more than a day, ask for a dedicated account rather than changing a shared one.

## Related pages

- [Payments platform architecture](platform-architecture.md), for the card data environment
- [Payout holds and releases](payout-holds.md), for what `mer_test_new_sellers` exercises
- [Staging environments](../release/staging-environments.md), for testing unreleased code rather than the merchant-facing sandbox
