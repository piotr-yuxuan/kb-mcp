---
title: "Content style guide"
---

# Content style guide

Owner: Wren Halloway, content designer, Design System team. Last reviewed: 2026-09-22.

This guide covers the words in Merchant Hub and in anything built with Inkwell: labels, buttons, messages, empty states, help text and emails sent by `notify`. It does not cover marketing copy or legal text, which have their own owners.

Our merchants are busy people dealing with money. Our words should be short, plain and exact, and they should sound like a competent colleague, not a machine and not a friend trying too hard.

## The two rules everyone remembers

1. **British English.** Colour, organisation, cancelled, licence (noun), catalogue, centre. In code, use whatever the platform spells (`color` in CSS), but never in text a person reads.
2. **Sentence case** for everything: page titles, headings, buttons, menu items, table headers, tabs. Capitalise only the first word and proper nouns.

| Write | Not |
|---|---|
| Payout schedule | Payout Schedule |
| Issue refund | Issue Refund |
| API keys and webhooks | API Keys And Webhooks |
| Merchant Hub settings | merchant hub settings |

Product names keep their capitals: Merchant Hub, Merchant API, Quillmoor Pay, Quillmoor Payouts. Use the terms in [product terminology](../product/terminology.md) and do not invent synonyms: a payout is a payout, never a "transfer" or a "withdrawal".

## Voice

- **Plain.** "We could not send your payout" beats "Payout disbursement failed".
- **Active.** "We paused your payouts" says who did it. "Your payouts have been paused" hides it.
- **Calm.** No exclamation marks, no "Oops", no "Uh-oh". Something going wrong with money is not cute.
- **Direct.** Address the merchant as "you". Use "we" for Quillmoor.
- **No "please" in instructions.** "Enter your sort code" is polite enough. Save "please" and "sorry" for when we have actually caused a problem, and then mean it.

## Buttons and links

- Start with a verb and name the object: "Issue refund", "Download statement", "Revoke key". See the [button page](button.md).
- Two or three words. Buttons truncate after 32 characters.
- The confirm button in a dialog repeats the verb of the action. "Revoke key", not "Yes" or "OK".
- Link text makes sense on its own. "View payout PO-2041", never "click here".

## Messages

**Errors** say what happened and what to do, in that order, without blame:

| Write | Not |
|---|---|
| Enter an amount of £1 or more | Invalid amount |
| This refund is more than the remaining payment of £42.10. Enter a smaller amount. | Error 422: refund exceeds captured amount |
| We could not reach your webhook endpoint. Check the URL and try again. | Webhook failed |

**Success messages** use the past tense and stay short: "Refund issued", "Payout schedule updated". They go in a [toast](toast.md) unless the page itself changes enough to show the result.

**Empty states** say why the page is empty and what to do next: "No payouts yet. Payouts appear here once your first sale settles."

**Hints** under a field answer the question the merchant is about to ask: the format, where to find the value, or why we need it. "You can find this on your bank statement" is useful; "Enter your account number" repeats the label. One sentence, two at most. If the help needs a paragraph, link to a help article instead.

## Talking about money that has not arrived

The hardest messages we write are about payouts that are late, held or failed. A merchant reading them may be worried about paying their own suppliers. A few rules from experience:

- Give a date or a time, not "soon". If we do not know, say what happens next and when we will update them.
- Say what the merchant can do, even if the answer is "nothing; we will email you when it is sent".
- Do not explain internal causes ("the batch was not acknowledged"). Say what it means for them: "Your payout is taking longer than usual."
- Never imply the merchant did something wrong unless they did, and then say exactly what to fix.

Support uses the same wording in its replies, so changes to these messages are shared with Merchant Support before release.

## Numbers, money and dates

- Amounts show the currency symbol and two decimal places in the merchant's locale: £1,250.00 in English; 1 250,00 € in French.
- Use numerals for all numbers in the interface, including one to nine: "3 payouts".
- Dates in full where there is room: 14 October 2026. In tables: 14 Oct 2026. Never 14/10/2026, which half the world reads differently.
- Times use the 24-hour clock with the time zone when it matters: 15:30 UK time, 14:00 CET.
- Ranges use "to": "1 to 7 days", "09:00 to 16:00".

## Punctuation

- No full stop at the end of headings, labels, buttons or single-sentence toasts. Use full stops in hints and messages of more than one sentence.
- Use the Oxford comma only when it prevents ambiguity.
- Hyphens join compound words ("two-factor", "same-day settlement"). Do not use long dashes; rewrite the sentence with a comma, a colon or brackets.
- Ellipses mean "more to come" in a menu item that opens a dialog: "Rename...". Nowhere else.

## French

Merchant Hub is available in French. French copy follows French conventions, not translated English ones: sentence case still applies, a non-breaking space goes before ":", ";", "?" and "!", and amounts are written 1 250,00 €. Strings are translated by the localisation process, not by engineers in pull requests; flag new strings in the changeset so they reach translation before release.

## Words we avoid

| Avoid | Use |
|---|---|
| Utilise | Use |
| In order to | To |
| Simply, just, easily | Nothing; if it were simple, they would not be reading the help |
| Disbursement | Payout |
| Submit (on a button) | The action: "Save changes", "Send request" |
| Hot new, powerful, seamless | A plain description of what it does |

Questions about wording go to Wren in `#team-inkwell`. Bring the screen, not just the sentence: context changes the answer.
