---
title: "Contributing to Inkwell"
---

# Contributing to Inkwell

Page owner: Priya Castellane. Last reviewed: 2026-10-01.

Inkwell is maintained by the Design System team, but most of its components started life in a product team that needed something we did not have. Contributions are welcome from anyone at Quillmoor. This page explains how to get a change from an idea into a release without surprises on either side.

## First, ask

Before you write code or draw anything, post in `#team-inkwell`. Say what you need and where it will be used. Half the time the answer is "that already exists", "there is a prop for that" or "another team is building it". The other half, we will tell you which of the routes below fits.

The team also runs **office hours on Wednesdays from 14:00 to 15:00 UK time**, in person on floor 4 of Quill House and on video for Paris and remote colleagues. Bring a screen, a sketch or a half-finished branch.

## Which route?

| Change | Route | Typical time to release |
|---|---|---|
| Bug fix, including an a11y fix | Pull request straight away | Next patch |
| Documentation or story fix | Pull request straight away | Next patch |
| New icon | Request in chat; see the [icon library](icons.md) | Next minor |
| New prop or variant on an existing component | Short proposal, then pull request | Next minor |
| New token | Proposal, contrast check, design review; see [design tokens](tokens.md) | Next minor |
| New component | Proposal, [design review](design-review.md), pull request in stages | One to two minors |
| Breaking change | Proposal and agreement from the design system lead | Next major |

## Writing a proposal

Proposals are Markdown files in the `proposals/` folder of the Inkwell repository, one per change, opened as a draft pull request so that discussion happens in one place. Copy `proposals/TEMPLATE.md`, which asks for:

1. **The problem**, in terms of a user and a task, not a component. "Merchants cannot see at a glance which payouts are on hold" beats "we need a badge".
2. **Two real uses.** Name the pages. A component with one use belongs in the product codebase until a second team needs it.
3. **What exists today** and why it does not fit.
4. **An API sketch**: props, their defaults, and an example.
5. **Both themes and the a11y checklist.** Say how the design behaves in dark mode and which [a11y checklist](accessibility.md) items it touches.
6. **Open questions.**

The team responds to proposals within five working days, even if the response is "we need to discuss this at design review".

## Working in the repository

```bash
pnpm install
pnpm dev               # Storybook on port 6006, both themes in the toolbar
pnpm test              # unit and interaction tests
pnpm lint              # including inkwell/no-raw-colour and inkwell/spacing-scale
pnpm tokens:contrast   # contrast of every documented token pairing, both themes
pnpm changeset         # describe your change for the release notes
```

## Definition of done

A change is ready for review when:

- [ ] Every new or changed state has a Storybook story, and the stories render correctly in light and dark.
- [ ] Tests describe behaviour a user can observe: what is announced, what is focused, what is called. We do not snapshot DOM structure.
- [ ] axe-core reports nothing serious or critical on the new stories.
- [ ] The component's wiki page is updated, or a draft is linked for a new component.
- [ ] A changeset says whether this is a patch, minor or major change, in a sentence a product engineer would understand.
- [ ] Visual regression changes are expected and explained in the pull request.

Inkwell follows the company's [code review guidelines](../engineering/code-review.md): one approval, from a Design System maintainer. Changes to tokens or to the focus ring also need a designer's approval.

## Releases and versions

Inkwell uses semantic versioning:

- **Patch** releases ship on Thursdays when there are fixes to ship.
- **Minor** releases ship roughly every three months: 3.1 in January 2026, 3.2 in April, 3.3 in July and 3.4 in September.
- **Major** releases are rare and planned. The last was [Inkwell 3.0](release-notes-inkwell-3-0.md) in October 2025.

Nothing is removed without a deprecation warning in at least one minor release first. Warnings appear in the browser console in development builds and in the changeset, and they name the replacement.

Merchant Hub and internal tools pick up new versions through the usual [dependency update policy](../release/dependency-updates.md). Merchant Experience usually takes a minor within two weeks of release.

## After it ships

Tell us how it went. If your component behaves differently from what the docs say, or if real merchant data broke an assumption (very long business names have a habit of doing this), post in `#team-inkwell`. A contribution is not finished when it merges; it is finished when the second team uses it without asking a question.
