---
title: "Interviewing engineers"
---

# Interviewing engineers

Owners: the heads of engineering, with People for the process. Last reviewed: 2026-05-14.

Hiring is part of every senior engineer's job. This page explains how our interview loop works, what each interview is for, and how to write feedback that helps the panel decide.

## The loop

| Stage | Length | Who | What it assesses |
|---|---|---|---|
| Recruiter call | 30 minutes | People | Motivation, logistics, level |
| Technical screen | 60 minutes | One engineer | Coding: a small problem, paired, in Python, Go or TypeScript |
| Systems design | 60 minutes | One engineer at E3 or above | Designing a service with failure in mind |
| Code review exercise | 45 minutes | One engineer | Reading and reviewing someone else's change |
| Collaboration and ownership | 45 minutes | An engineering manager | How they work with others, and with production |
| Debrief | 30 minutes | All the interviewers | A decision and a level |

Each stage maps to the dimensions in the [career ladder](career-ladder.md), and the debrief discusses the candidate dimension by dimension.

## The exercises

**Technical screen.** Problems come from the interview bank, each with its rubric. Candidates may look things up; we care how they reason, test and talk, not whether they remember a library function. Use the candidate's choice of language among the three.

**Systems design.** The current prompts are a payout scheduler that must never pay a seller twice, and a currency quote service whose quotes expire. Strong answers raise idempotency, retries and observability without being prompted; weaker ones reach for a particular database before they understand the problem.

**Code review exercise.** The candidate reviews a prepared change of about 200 lines, with three planted defects and a few honest differences of style. We look at whether they find the defects, how they phrase their comments, and whether they can tell a defect from a preference. The exercise uses the comment labels from our [code review guidelines](code-review.md), which we explain at the start.

## Before you interview

- Shadow two interviews of the kind you will run, then lead one with an experienced interviewer watching.
- Read the candidate's CV and the stage's rubric, and nothing else. Do not read other interviewers' feedback before writing your own.
- Start on time, introduce yourself and the format, and leave five minutes for the candidate's questions.

## Writing feedback

Write your feedback within one business day, and before the debrief or any conversation with the other interviewers.

```text
Recommendation: strong yes / yes / no / strong no
Level signal:   E2 / E3 / E4
Evidence:
  - what they did, described or quoted, against the rubric
Concerns:
  - what you did not see, and whether another stage could check it
```

Write down what the candidate did, not what you inferred about them. "Did not mention retries until asked, then designed a sound backoff" is evidence; "not very senior" is not.

## Fairness

Every candidate for a role gets the same exercises and the same rubric. Adjustments for a disability or other circumstances are arranged by People, and never mentioned in feedback. Never ask about age, family plans, health, religion or nationality, and steer the conversation away if the candidate raises them.

Know someone who would do well here? Refer them through the [employee referral scheme](../people/referral-scheme.md).
