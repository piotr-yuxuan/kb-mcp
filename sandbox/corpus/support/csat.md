---
title: "Customer satisfaction surveys"
---

Owner: Joss Fairweather, support operations analyst. Last reviewed 2026-10-19.

After we solve a ticket, the merchant gets a one-question survey about how we did. The answers are the main way we hear about the quality of our replies, as opposed to their speed, which the SLA reports already cover.

## How the survey works

- Harbour sends the survey by email 24 hours after a ticket is set to **Solved**, unless the merchant has replied in the meantime.
- One question: "How satisfied are you with the help you received?", rated from 1 (very dissatisfied) to 5 (very satisfied), with an optional comment.
- Tickets from merchants whose account language is French get the survey in French, written by the Paris team.
- A merchant receives at most one survey every 14 days, however many tickets they open.

## When no survey is sent

Harbour skips the survey for:

- tickets merged into another ticket;
- tickets tagged `dsar`, `formal-complaint` or `inc-` followed by an incident's short name;
- tickets in the `fraud-reports` and `refund-approvals` queues;
- tickets solved as spam or as sent to the wrong company;
- tickets from cardholders rather than merchants.

These exclusions exist either because the survey would be insensitive, or because the rating would measure a decision rather than our help.

## The score

The **survey score** is the share of ratings that are 4 or 5, out of all ratings received, over a period. Our target is 90% for every queue, measured monthly. From July to September 2026 the score was 89% on a response rate of 23%; the weekly figures are in [Support weekly review October 2026](weekly-review-2026-10.md).

The score is reported per queue, per tier and per agent. Per-agent scores are for coaching conversations between an agent and their lead; they are never ranked or shared in a team meeting, and they do not count on their own in [performance reviews](../people/performance-reviews.md).

## Low ratings

A rating of 1 or 2 opens a follow-up task for the ticket owner's team lead, due within 2 business days.

1. Read the whole ticket and the merchant's comment.
2. Decide what the rating is really about: our reply, the time it took, or a policy the merchant dislikes, such as a hold or a refused refund.
3. If our reply fell short, contact the merchant with the `survey-follow-up` macro, adapted, and put it right if you can.
4. Record the cause on the task: **reply quality**, **speed**, **policy** or **product**. Product causes go to the product team through the tag `feedback-product`.

Never ask a merchant to change their rating, and never reopen a ticket only to send a second survey.

`survey-follow-up`:

> Thank you for telling us how we did on your recent request. I am sorry our answer did not help as it should have. I have read through your ticket, and {{follow_up.summary}}. If there is anything still open, reply to this message and I will look after it personally.

## Reading the comments

Comments are often more useful than the scores. Every month Joss collects the comments into themes, and the weekly review discusses the top three. Themes that keep recurring become changes: a macro rewritten (see [Support macros](macros.md)), a step added to a guide, or a request to the product team.
