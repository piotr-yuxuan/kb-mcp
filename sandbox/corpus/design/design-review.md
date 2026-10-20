---
title: "Design review ritual"
---

# Design review ritual

Run by the Design System team. Page owner: Priya Castellane. Last reviewed 2026-08-11.

Design review is a weekly hour where product designers and engineers bring work in progress to the Design System team and to each other. Its purpose is to catch problems while they are cheap: before the build, not after the audit. It is a conversation about the work, never a judgement of the person who made it.

## When and where

- **Thursdays, 11:00 to 12:00 UK time.** Paris colleagues join at 12:00 their time.
- In the large meeting room on floor 4 of Quill House, booked as a standing slot, with a video link in the calendar invitation for Paris and remote colleagues.
- Cancelled in the change freeze weeks around the end of the year and when there are no submissions by Tuesday evening.

## How to get a slot

Post in `#team-inkwell` by **Tuesday at 17:00** with:

1. a link to the frames in the design tool, or to a Storybook branch for engineering work;
2. one or two sentences on the problem and the user;
3. the questions you want answered. "Is this OK?" is not a question. "Should the refund amount be editable inline or in a modal?" is.

Each session has room for three slots of 15 minutes, plus 15 minutes at the end for Inkwell news. Slots go in order of submission, with priority for work that is about to start being built.

## How a slot runs

| Minutes | What happens |
|---|---|
| 0 to 4 | The presenter sets the context: user, task, constraints. No walkthrough of every screen. |
| 4 to 13 | Discussion, led by the presenter's questions. The chair keeps it on them. |
| 13 to 15 | The chair states the outcome and any actions, and a note-taker posts them in the slot's thread. |

The chair rotates among the designers on the Design System team. Priya Castellane and at least one Inkwell engineer attend every session.

## What reviewers look for

Reviewers work from the same short list each week, so presenters know what to expect:

- **The principles** on the [design tokens and principles](tokens.md) page, especially "clear before clever" and "consistent, then local".
- **The starred items** on the [a11y checklist](accessibility.md): contrast, focus, targets and form labels.
- **Both themes.** Frames in light only are reviewed, but the first action will be to produce dark frames. See [theming](theming.md).
- **Content**, against the [content style guide](content-style.md): sentence case, British English, labels that say what happens.
- **Reuse.** Is there an Inkwell component that does this already? If the design needs a new one, the slot often ends with "write a proposal", as described in [contributing](contributing.md).

## Outcomes

Every slot ends with one of three outcomes:

- **Go**: build it.
- **Go with changes**: build it after the listed changes; no need to come back.
- **Come back**: the open questions are big enough to need a second look. The presenter books the next free slot.

Outcomes are not approvals in any formal sense, and nobody needs a "go" to ship. In practice, teams that skip review for anything user-facing tend to meet the same feedback later, from a merchant.

## Smaller things

Not everything needs a slot. For a copy change, a new icon or a single state of an existing component, post in `#team-inkwell` with "async review" in the message. Someone from the team will answer within two working days.
