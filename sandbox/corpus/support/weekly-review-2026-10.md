---
title: "Support weekly review October 2026"
---

Running notes of the Monday review for October 2026. Same format as [Support weekly review September 2026](weekly-review-2026-09.md): figures for the previous Monday to Sunday, then discussion and actions. Chair: Femi Haldane. Notes taken in turn; this month by Ewan Mabry.

## Monday 5 October

Attendees: Femi Haldane, Inès Moreau, Dorian Pask, Ewan Mabry, Joss Fairweather.

**Figures.** 2,276 tickets. P1: 7, all on time. On time: P2 97%, P3 93%, P4 92%. Survey score 90%.

**September close.** P1 finished September at 97.4%, 37 on time out of 38, below the 98% target. The single breach was the overnight one of 12 September, already reviewed. P2, P3 and P4 met their targets in every queue. No further action beyond the support duty checklist change.

**API versioning questions.** Merchants' developers have started asking about the `Quillmoor-Version` header, now that ENG-30 is under way. T1 should point them to the API documentation at `docs.quillmoor.example`; questions about how long an old version stays supported go to T2, who answers from the decision itself, [ADR-023: Version public APIs by date](../architecture/adr-023-api-versioning.md), rather than from memory.

**Access review.** The October access review has started. Femi will certify Harbour access for the whole team, and leads should tell her by Friday of anyone whose role changed during the quarter. See [Quarterly access reviews](../security/access-reviews.md).

Actions:

- Ewan Mabry: add a short `api-version-question` note to the T1 knowledge base, linking to the documentation.
- Leads: send role changes to Femi by Friday 9 October.

## Monday 12 October

Attendees: Femi Haldane, Inès Moreau, Dorian Pask, Ewan Mabry. Joss Fairweather sent figures.

**Figures.** 2,338 tickets. P1: 10, all on time. On time: P2 95%, P3 92%, P4 94%. Survey score 89%.

**The P1 that was the merchant's own.** On Wednesday a marketplace reported that no buyer could pay. The ticket was set to P1, which paged the payments on-call. Within twenty minutes the on-call found that the merchant's checkout was using an API key the merchant had revoked themselves. By our rules the priority was right: the merchant could not take payments. The on-call stood down quickly and agreed. To shorten that path, T1 will ask, in the first reply to any P1, whether the merchant changed anything in their integration that day. Ewan will add the question to `ack-p1`.

**Paris at the start of November.** Several Paris agents have booked annual leave for the first days of November. Inès confirmed that `fr-marchands` keeps two agents each business day; French-speaking London colleagues will cover the gaps in the late afternoon.

**Dark mode.** The preview has been open since 15 September to merchants who opt in from their profile menu, and covers fourteen pages since early October. Merchant Experience briefed support before it opened. The September agreement holds: no dates to merchants for the remaining pages.

**Instant payouts.** Oskar Ngata's draft FAQ arrived. Dorian and Inès will comment by 16 October.

Actions:

- Ewan Mabry: update `ack-p1` and `fr-p1-accuse-reception` with the integration question.
- Dorian Pask and Inès Moreau: comments on the instant payouts FAQ by 16 October.

## Monday 19 October

Attendees: Femi Haldane, Inès Moreau, Dorian Pask, Ewan Mabry, Joss Fairweather.

**Figures.** 2,419 tickets. P1: 8, all on time. On time: P2 96%, P3 94%, P4 95%. Survey score 91%.

**Survey results, July to September.** Over the three months, the survey score was 89%, on a response rate of 23%. French-language tickets scored 92%. The lowest-scoring queue was `kyc`, as expected during the review wave. Full method on [Customer satisfaction surveys](csat.md).

**Requests to raise the approval threshold.** Two merchants have asked for refunds over £10,000 to skip T2 approval on their accounts. Declined: the threshold applies to every merchant, and protects the merchant as much as us if their account is compromised. Dorian will reply to both personally. See [Handling merchant refund requests](refunds.md).

**November rota.** Published on 9 October as planned, with the London late shift until 20:00 on weekdays and a second support duty agent on Fridays and Saturdays. Joss reminded leads that swaps for November need her agreement, given the thin margins.

**Chargebacks after the peak.** Disputes typically rise a few weeks after a busy month. T2 expects the rise from early December and has asked that no T2 specialist's annual leave overlap in the first half of December without Dorian's agreement.

Actions:

- Dorian Pask: reply to the two merchants about the refund threshold.
- Joss Fairweather: send the December T2 leave overview to Dorian.
- All leads: review open tickets older than 10 business days before the next meeting.
