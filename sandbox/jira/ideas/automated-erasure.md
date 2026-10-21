---
summary: "Automate erasure requests end to end"
---

## Problem

An erasure request travels from Support to Legal to the Data Platform team by email and
tickets. The warehouse side is described in [Erasure requests in the warehouse](../../corpus/data/erasure-requests.md),
and the contractual side in the [DPA playbook](../../corpus/legal/dpa-playbook.md). Each
hand-off waits for someone to notice it, and we came within four days of the 30-day
limit twice this year.

## Idea

One intake form that records the request once, checks the requester's identity, and
starts the warehouse job directly, with Legal approving in the same flow.

## Measure of success

Median time from request to completion under 7 days, and no request older than 20
days.

Raised by Beatrix Sallow.
