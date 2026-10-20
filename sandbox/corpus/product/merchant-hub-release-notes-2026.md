---
title: "Merchant Hub release notes 2026"
---

Owner: Linnea Ashdown, product manager for Merchant Hub and Merchant API, with the Merchant Experience team (`#team-merchant-hub`). Last reviewed: 2026-10-20.

Merchant Hub ships continuously, several times a week, through the normal [deployment pipeline](../release/deployment-pipeline.md). These notes summarise what changed for merchants each month, newest first. They are written for internal readers: support, account managers and anyone who needs to know when something reached merchants. The merchant-facing changelog is drawn from this page, minus the epic keys and internal notes.

Each entry gives the feature, its release stage (pilot, preview or generally available, as defined in [Product terminology](terminology.md)) and, where the work had one, its epic in ENG.

## 2026 at a glance

| Month | Headline | Epic |
|---|---|---|
| January | Euro settlement pilot; payout search | ENG-4 |
| February | Team roles | None |
| March | Euro settlement generally available | ENG-4 |
| April | Accessibility remediation complete; webhooks on the new event log | ENG-25, ENG-29 |
| May | Merchant Hub in French; live conversion previews | ENG-5 |
| June | Saved views; refunds pilot | ENG-6 |
| July | Self-serve refunds generally available | ENG-6 |
| August | Chargeback evidence submitted automatically; incident banner | ENG-28, ENG-13 |
| September | Dark mode preview; dated API versions for new keys | ENG-26, ENG-30 |
| October | Dark mode on 14 pages; API version upgrade assistant | ENG-26, ENG-30 |

Two of the year's merchant-facing epics are still open: ENG-26 and ENG-30. Everything else in the table above is finished, and its epic is closed in ENG.

## October 2026 (to 20 October)

**Dark mode preview reaches 14 pages.** The preview now covers disputes, refunds, settlement reports, team settings and the developer pages, on top of the six pages it launched with. That makes 14 of the 20 most visited pages. Merchants opt in from their profile menu. 1,150 merchant accounts have at least one user with the preview on. Preview; ENG-26.

**API version upgrade assistant.** The developer page lists, for each API key, the dated version it is pinned to and the changes a merchant would see by moving to the latest version, endpoint by endpoint. It is read-only for now: merchants change versions in their integration, not in Hub. Preview; ENG-30. The versioning policy is [ADR-023](../architecture/adr-023-api-versioning.md).

**Held payouts explained.** A payout on hold now shows a "held" status on the payouts list and the payout page, with a plain explanation of why new sellers' payouts are held and who releases them. Support no longer has to explain this case by case. The policy is on [Payout holds and releases](../payments/payout-holds.md). Generally available.

**Fixed**

- The refund dialog trapped keyboard focus after a failed submission. Focus now returns to the error message.
- Settlement reports exported in French used a full stop as the decimal separator. They now follow the account's language.
- The payouts list sometimes showed a payout as "in transit" after the bank had confirmed it, until the page was reloaded.

> [!NOTE]
> ENG-26 and ENG-30 both reach their last planned sprint, ENG Sprint 40, with work remaining. The [Q4 2026 OKRs](okrs-2026-q4.md) carry the plan for finishing them.

## September 2026

**Dark mode preview.** On 15 September we opened a dark theme to any merchant who opts in, on six pages: home, payments, payment detail, payouts, payout detail and profile settings. Pages outside the preview stay light, and the switch between them is deliberate rather than a bug. 640 accounts opted in by the end of the month. Preview; ENG-26. The design reasoning is in the [brief](brief-dark-mode.md); how the theme is built is on [Theming and dark mode](../design/theming.md).

**Dated API versions for new keys.** Since 21 September every new Merchant API key is pinned to a dated version when it is created, and the developer page shows that version. Existing keys are unchanged for now. Generally available for new keys; ENG-30.

**Refund approval status.** Refunds waiting for approval by our support team now have their own filter on the refunds list, and the requester gets a notification in Hub as well as the email from `notify` once a refund is approved.

**Fixed**

- Saved views lost their column order after a browser update.
- The chargeback evidence upload rejected files with upper-case extensions.

## August 2026

**Chargeback evidence, submitted for you.** Merchants upload evidence on the dispute page and Quillmoor assembles it and submits it to the card schemes automatically, ahead of each scheme's deadline. Merchants see the submission date and the evidence pack that went out. The timing rules are on [Chargebacks and disputes](../support/chargebacks.md). Generally available on 27 August; ENG-28.

**Incident banner.** When the status page reports an incident that affects a merchant's products, Merchant Hub shows a banner with the same wording and a link to `status.quillmoor.example`. The banner and the status page are now fed from the same template. Generally available; ENG-13. How status updates are written and approved is on [Status page communications](../incidents/status-page.md).

**Refunds in the payment timeline.** The payment detail page shows every refund against a payment, with who requested it, who approved it and when it reached the buyer's card.

**Fixed**

- The payouts calendar showed the wrong week start for accounts set to French.
- Search on the disputes list ignored the buyer's email address.

## July 2026

**Self-serve refunds.** Merchants can refund a payment, fully or partly, from the payment page or through the Merchant API, without contacting support. Each refund takes an idempotency key, following [ADR-008](../architecture/adr-008-idempotency-keys.md), so a retried request never refunds twice. Large refunds need a second approver before they are sent; the threshold and the rules on refund windows are on [Handling merchant refund requests](../support/refunds.md). Generally available on 28 July, after a pilot with twenty merchants in June; ENG-6. See the [brief](brief-self-serve-refunds.md).

**Refund webhooks.** Three new webhook events (`refund.requested`, `refund.succeeded`, `refund.failed`) let a marketplace update its own order pages. Generally available; ENG-6.

**Team roles: refund permission.** A new permission lets an owner choose who may request refunds, separate from who may see payments.

**Fixed**

- Date range filters on the payments list included one extra day when the range crossed a change of clocks.

## June 2026

**Saved views.** Merchants can save a set of filters and columns on the payments, payouts and disputes lists, name it, and share it with their team. The most used views on the first day were "Failed payouts this week" and "Disputes awaiting evidence". Generally available.

**Refunds pilot.** Twenty merchants, chosen from those who raised the most refund tickets in Q1, started issuing refunds from Hub and the Merchant API. Pilot; ENG-6.

**API key last used.** The developer page shows when each API key was last used and which endpoint it last called. Merchants asked for this to find keys they could retire.

**Evidence due column.** The disputes list has a column for the date by which evidence should be uploaded, and can be sorted by it. Disputes with no evidence and fewer than ten days left are highlighted.

**Fixed**

- Large payout exports timed out above about 50,000 rows. Exports are now streamed and arrive by email when ready.
- The settlement report did not show the currency next to totals on accounts settling in both pounds and euros.

## May 2026

**Merchant Hub in French.** Every page, email and error message in Hub is available in French. Users choose their language in profile settings; new users from accounts registered in France default to French. Inès Moreau's team reviewed every string before launch. Generally available.

**Live conversion previews.** Where a payout or settlement involves a currency conversion, Hub shows the rate, the time the quote was issued, and how long it remains valid, and fetches a new quote automatically when it expires. This uses the rewritten `fx-quote` service. Generally available; ENG-5. How quotes work is on [fx-quote service](../payments/fx-quote-service.md).

**Settlement report clarity.** Settlement reports now show the settlement date and the payout date in separate columns, after merchants in the May interviews told us they confused the two.

**Fixed**

- The sign-in page's "remember this device" option was ignored on some browsers.

## April 2026

**Accessibility remediation complete.** The last fixes from the accessibility audit shipped this month. Across January to April, Merchant Hub gained:

- full keyboard navigation of the payments, payouts and disputes tables;
- a visible focus indicator on every interactive element, including the destructive buttons, where it had been invisible;
- contrast fixes on status badges, links and disabled controls;
- labels for every form field and icon-only button, and live announcements for toasts.

Generally available; ENG-25. The standard we hold Hub to is the [Accessibility checklist](../design/accessibility.md).

**Webhooks on the new event log.** Behind the scenes, the events that feed merchant webhooks now come from the replicated event log. Event identifiers, payloads and delivery behaviour did not change. Generally available; ENG-29.

**Fixed**

- Screen readers announced the payouts total twice.
- The disputes list's sort order reset after opening a dispute.

## March 2026

**Euro settlement.** Merchants with a euro bank account can settle euro card payments in euros through SEPA, instead of having them converted to pounds. In Hub, they add a euro bank account in settings, see euro and sterling settlements as separate reports, and see an expected settlement date for each batch. Generally available on 9 March; ENG-4. Settlement windows are on [Settlement windows and cut-off times](../payments/settlement-cutoffs.md); the product reasoning is in the [brief](brief-multi-currency.md).

**Bank account changes need a second confirmation.** Changing the bank account a merchant settles to now needs confirmation by email from a second account owner.

**Fixed**

- Payout detail pages showed seller names truncated at 30 characters.

## February 2026

**Team roles.** Owners can invite team members with one of six roles: owner, administrator, finance, support, developer and read-only. Finance users see settlements and payouts but cannot change bank details; support users can see payments and disputes but not reports. Generally available.

**Sign-in status message.** After the Merchant Hub sign-in outage of 11 February, the sign-in page shows a message whenever the status page reports an incident affecting Merchant Hub, so merchants are not left guessing. The incident itself is described in its [incident report](../incidents/report-2026-02-11-hub-login.md).

**Fixed**

- Inviting a user whose email address contained a plus sign failed silently.

## January 2026

**Euro settlement pilot.** Eight French marketplaces started settling euro payments in euros, with a new euro settlement report in Hub. Pilot; ENG-4.

**Payout search.** The payouts list can be searched by seller reference, payout identifier or exact amount. Before this, support handled around 150 tickets a week asking "where is this payout?"; merchants can now answer most of these themselves, with the help of [Payout delays: what to tell merchants](../support/payout-delay-faq.md) for the rest.

**Account time zone.** Dates and filters across Hub now follow the account's time zone instead of the browser's.

**Fixed**

- The home page's "payments today" total excluded payments authorised before midnight and captured after it.

## How to add an entry

Product managers add their items by the third working day of the next month. Keep each entry to the feature, what changed for merchants, its stage and its epic. Link to the page that holds the rules, such as refund limits or settlement windows, rather than repeating them: those pages change, and this page is a record.

## Related pages

- [Product roadmap 2026](roadmap-2026.md)
- [Launch checklist](launch-checklist.md)
- [Product terminology](terminology.md)
