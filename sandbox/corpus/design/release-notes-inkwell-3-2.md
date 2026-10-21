---
title: "Inkwell 3.2 release notes"
---

# Inkwell 3.2 release notes

**Released:** 29 April 2026 · **Type:** minor · **Release manager:** Teodor Ashby · **Epic:** ENG-25 · **Upgrade effort:** under an hour; check visual diffs

## Summary

Inkwell 3.2 is the a11y release. It ships the component fixes from the Merchant Hub audit that opened epic ENG-25 in December 2025: 41 of the audit's 47 issues sat in Inkwell, and all 41 are fixed here. The other six were in Merchant Hub code and were fixed there. There are no breaking API changes, but several components look slightly different, so review your visual snapshots before merging the upgrade.

## Highlights

- **A focus ring you can always see.** The new two-tone ring, a 2 px inner gap in `color.focus.gap` and a 2 px outer ring in `color.focus.ring`, stays visible on every fill, including the destructive button. See the [button page](button.md).
- **Bigger hit areas.** Every icon action now meets the 24 by 24 CSS pixel minimum on the [a11y checklist](accessibility.md), without changing the icon's drawn size.
- **Errors linked to fields.** `TextField`, `Select` and `TextArea` link hint and error text with `aria-describedby`, and a new `ErrorSummary` component moves focus to the list of errors on submit.

## Breaking changes

None in the API. Visual changes to check:

| Change | What to do |
|---|---|
| The focus ring is 2 px wider overall because of the inner gap | Check tight layouts where rings may be clipped by `overflow: hidden` |
| Close buttons on `Tag` and `Banner` grow from 16 to 24 px hit areas | Check dense filter bars |
| The destructive button's focus ring is no longer red | Nothing; this is the fix |
| `DataTable` adds `scroll-padding-top` under a sticky header | Remove any workaround you wrote for focused rows hiding under the header |

## New

- `ErrorSummary` component for forms.
- `confirm.requireText` on destructive buttons, for type-to-confirm on unrecoverable actions.
- `loadingLabel` on `Button`, announced once when loading starts.
- Lint rule `inkwell/no-outline-none`, a warning in 3.2 and an error from 3.3.
- F6 moves focus to the toast region.

## Fixed

- The focus ring was invisible on the destructive button, because a component token set it to the same red as the fill (ENG-25).
- `TextField` error messages were not linked to their inputs, so screen readers did not read them.
- `Modal` returned focus to the page body when the element that opened it had been removed; it now falls back to the main heading.
- The first toast after page load was sometimes not announced, because the live region was created with it.
- `DataTable` did not announce sort changes.
- `Drawer` ignored `prefers-reduced-motion`.
- `chevron-` icons were not mirrored in right-to-left layouts.

## Deprecated

- Component token `button.destructive.focus` now has no effect and logs a warning. It will be removed in 4.0.

## Upgrading

```bash
pnpm add @quillmoor/inkwell@^3.2.0
pnpm lint            # look for new inkwell/no-outline-none warnings
pnpm test:visual     # review the expected focus ring and hit area changes
```

Merchant Hub moved to 3.2 on 6 May 2026. If a visual change looks wrong rather than different, post the snapshot in `#team-inkwell`. The [3.0 release notes](release-notes-inkwell-3-0.md) cover the last set of breaking changes.

## Thanks

To Dafydd Morrow, who ran the audit; to Merchant Experience, who fixed the six product-side issues in the same sprints; and to the colleagues who tested the release candidates with screen readers and keyboard only.
