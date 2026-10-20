---
title: "Inkwell design tokens and principles"
---

# Inkwell design tokens and principles

| | |
|---|---|
| Owner | Design System team (`#team-inkwell`) |
| Page owner | Priya Castellane, design system lead |
| Maintainers | Teodor Ashby (design engineering), Dafydd Morrow (interaction design) |
| Package | `@quillmoor/inkwell`, tokens under `@quillmoor/inkwell/tokens` |
| Last reviewed | 2026-09-30 |

Inkwell is the design system behind Merchant Hub and every internal tool that wants to look like it. This page explains the principles we design by and the tokens that carry them into code. If you only read one section, read "Using tokens in code": nearly every visual bug we triage in `#team-inkwell` starts with a hard-coded value that should have been a token.

## Principles

We wrote these principles in 2024, rewrote two of them during tokens v2 (ENG-24), and use them to settle arguments in [design review](design-review.md). They are ordered: when two pull in different directions, the earlier one wins.

1. **Clear before clever.** Merchants come to Merchant Hub to check money: a payout that has not arrived, a refund they need to issue, a dispute with a deadline. Every screen should answer "what happened to my money?" before it delights anyone. Decoration that competes with an amount, a status or a date is removed.
2. **Name the intent, not the value.** A token says what a value is for (`color.surface.raised`), never what it looks like (`grey-50`). Intent names survive a rebrand, a dark theme and a contrast fix; literal names do not.
3. **One source of truth.** Every colour, space, radius, shadow, font size and duration comes from a token. Components consume tokens; product code consumes components and, where it must, tokens. Nothing consumes a raw hex value.
4. **Usable by everyone, by default.** A component that ships from Inkwell meets the [a11y checklist](accessibility.md) without the product team doing anything extra. Token pairs are chosen so that the default combinations pass contrast in both themes.
5. **Quiet by default, loud on purpose.** Most of the interface sits on neutral surfaces. Colour is spent on meaning: an action, a status, a warning. If everything is highlighted, nothing is.
6. **Consistent, then local.** Reuse the pattern that already exists before inventing one. A local variation is fine when the job is genuinely different, and it should be proposed back to Inkwell if a second team needs it.

## Token tiers

Inkwell tokens come in three tiers. Product code should almost never reach below the second.

| Tier | Example | Who uses it |
|---|---|---|
| Palette | `palette.ink.900`, `palette.quill.500` | Only the theme files inside Inkwell |
| Semantic | `color.surface.raised`, `color.text.secondary`, `space.4` | Components, and product code when no component fits |
| Component | `button.primary.background`, `table.row.hover` | The component that owns them |

Palette tokens are raw values: each hue in ten steps from 50 to 900. They exist so that theme files have something to point at, and they are not exported from the public entry point. If you find yourself importing `palette.*`, you are about to break the dark theme.

Semantic tokens carry the meaning. A semantic token resolves to a different palette token in each theme, which is how [theming](theming.md) works without a single component knowing which theme is active.

Component tokens let a component expose a narrow set of knobs. `button.primary.background` points at `color.action.primary.background` by default; a product team should not override it, but Inkwell can retune the button without touching every other primary action.

## Naming grammar

Token names follow `category.role.variant.state`, lowercase, dot-separated in the source and hyphenated as CSS custom properties with the prefix `--ink-`.

```text
color.surface.raised          ->  --ink-color-surface-raised
color.action.primary.hover    ->  --ink-color-action-primary-hover
space.4                       ->  --ink-space-4
radius.medium                 ->  --ink-radius-medium
```

Rules we hold to:

- The category comes first: `color`, `space`, `size`, `radius`, `shadow`, `font`, `motion`, `z`.
- The role says where the value is used: `surface`, `text`, `border`, `action`, `feedback`, `focus`.
- States are the last segment and use the same words everywhere: `hover`, `active`, `disabled`, `selected`.
- No hues in semantic names. `color.feedback.critical`, not `color.red`.

## Colour tokens

These are the semantic colour tokens most teams need. The full list, with values for both themes, is generated in the token reference in Storybook.

| Token | Use it for | Light value | Dark value |
|---|---|---|---|
| `color.surface.default` | The page background | `#FFFFFF` | `#14161A` |
| `color.surface.raised` | Cards, panels, table containers, anything that sits one level above the page | `#FFFFFF` with `shadow.small` | `#1D2026` |
| `color.surface.sunken` | Wells, code samples, read-only inputs | `#F4F5F7` | `#0F1114` |
| `color.surface.overlay` | Modals, popovers, menus | `#FFFFFF` | `#262A31` |
| `color.text.primary` | Body text and headings | `#1A1D23` | `#ECEEF2` |
| `color.text.secondary` | Hints, metadata, timestamps | `#525866` | `#A9AFBB` |
| `color.text.on-action` | Text on a filled action | `#FFFFFF` | `#0F1114` |
| `color.border.subtle` | Dividers, table rules | `#E2E4E9` | `#2F343C` |
| `color.border.strong` | Input outlines, control boundaries | `#7A8190` | `#8A92A0` |
| `color.action.primary.background` | Primary buttons, selected tabs | `#2B4ACB` | `#8EA6FF` |
| `color.action.destructive.background` | Destructive buttons | `#C2272D` | `#FF8A8A` |
| `color.feedback.success` | Success icons and borders | `#1C7C4A` | `#5FD39A` |
| `color.feedback.warning` | Warning icons and borders | `#9A5B00` | `#F2B45A` |
| `color.feedback.critical` | Error text, critical icons | `#B3261E` | `#FF9C94` |
| `color.focus.ring` | The outer focus ring | `#2B4ACB` | `#8EA6FF` |
| `color.focus.gap` | The inner gap of the focus ring | `#FFFFFF` | `#14161A` |

`color.surface.raised` deserves a word, because it is the token people most often reach past. In the light theme a raised surface is the same white as the page, and the shadow does the lifting. In the dark theme shadows barely show, so the raised surface is lighter than the page instead. If you hard-code white for a card, it looks right in light and glows in dark. Use the token and both themes work.

> [!NOTE]
> Before tokens v2 these were called `color.bg.card`, `color.bg.page` and so on. ENG-24 renamed every surface colour to `color.surface.*` in Inkwell 3.0. The old names were removed, not aliased; the codemod in the [3.0 release notes](release-notes-inkwell-3-0.md) rewrites them.

## Spacing scale

Spacing moves in steps of 4 px. Every padding, margin and gap in Inkwell is a multiple of 4, and the scale names the multiple: `space.3` is 3 × 4 = 12 px.

| Token | Value | Typical use |
|---|---|---|
| `space.0` | 0 px | Resetting a gap |
| `space.1` | 4 px | Icon to label inside a button; tight inline gaps |
| `space.2` | 8 px | Between related controls; table cell padding in compact density |
| `space.3` | 12 px | Input padding; table cell padding in comfortable density |
| `space.4` | 16 px | Card padding on small screens; default stack gap |
| `space.5` | 20 px | Between form fields |
| `space.6` | 24 px | Card padding on large screens; modal padding |
| `space.8` | 32 px | Between sections of a page |
| `space.10` | 40 px | Page gutters on wide screens |
| `space.12` | 48 px | Between major page regions |
| `space.16` | 64 px | Empty states and hero spacing |

There is no `space.7`, `space.9`, `space.11` or anything between 48 and 64. We removed them in 3.0 after finding that almost every use was someone nudging a layout by eye. If the scale does not have the value you want, the layout usually needs a different structure, not a new number. Sizes of controls (`size.control.small` at 32 px, `size.control.medium` at 40 px, `size.control.large` at 48 px) sit on the same 4 px grid but are a separate category, so that changing a gap never changes a button.

## Typography, radius and elevation

Typography tokens bundle size, line height and weight so that they travel together:

| Token | Size / line height | Weight |
|---|---|---|
| `font.body.medium` | 14 / 20 px | 400 |
| `font.body.large` | 16 / 24 px | 400 |
| `font.label.medium` | 14 / 20 px | 500 |
| `font.heading.small` | 16 / 24 px | 600 |
| `font.heading.medium` | 20 / 28 px | 600 |
| `font.heading.large` | 28 / 36 px | 600 |
| `font.numeric.medium` | 14 / 20 px, tabular figures | 500 |

Every line height is a multiple of 4 px, which keeps text on the same grid as spacing. The font stack is `"Quill Sans", system-ui, sans-serif`; amounts in tables use `font.numeric.*` so that digits line up.

Radius has three steps: `radius.small` (4 px) for inputs and tags, `radius.medium` (8 px) for cards and buttons, `radius.large` (12 px) for modals. Elevation has `shadow.small`, `shadow.medium` and `shadow.large`; in the dark theme the shadows are deliberately weak and the surface token does the work. Motion tokens live on the [motion guidelines](motion.md) page.

## Using tokens in code

In CSS, use the custom properties. They are defined on `:root` and redefined under the dark theme selector, so you get both themes for free.

```text
.payout-summary {
  background: var(--ink-color-surface-raised);
  color: var(--ink-color-text-primary);
  border: 1px solid var(--ink-color-border-subtle);
  border-radius: var(--ink-radius-medium);
  padding: var(--ink-space-4) var(--ink-space-6);
  display: grid;
  gap: var(--ink-space-3);
}

.payout-summary__amount {
  font: var(--ink-font-numeric-medium);
}
```

In TypeScript, import the typed `tokens` object when a value has to be computed, for example to size a chart. The object returns the CSS variable reference, not the resolved value, so it still follows the theme.

```typescript
import { tokens } from "@quillmoor/inkwell/tokens";

const chartPadding = {
  top: tokens.space[4],    // "var(--ink-space-4)"
  left: tokens.space[8],
};

export function SettlementBar({ settled }: { settled: boolean }) {
  return (
    <rect
      fill={settled ? tokens.color.feedback.success : tokens.color.surface.sunken}
      height={8}
      rx={4}
    />
  );
}
```

If you need the resolved number, say to pass a width to a canvas library, use `resolveToken("space.4")`, which reads the computed style. It is slower and does not update when the theme changes unless you subscribe with `useTheme()`; prefer the CSS variable.

Two lint rules enforce the principle of one source of truth. `inkwell/no-raw-colour` rejects hex, `rgb()` and named colours in stylesheets and inline styles; `inkwell/spacing-scale` rejects pixel values for margin, padding and gap that are not on the scale. Both run in continuous integration for Merchant Hub and fail the build.

## Do and don't

Do:

- Pick the token by what the element is, not by what colour you want. A panel is `color.surface.raised` even if it happens to be white today.
- Use `space.*` for gaps between elements and let components handle their own internal padding.
- Ask in `#team-inkwell` when no token fits. Someone else probably hit the same gap.
- Check the token reference for the dark value before assuming a pairing works.

Don't:

- Don't import `palette.*` in product code.
- Don't override component tokens such as `button.primary.background` to make one button "pop". Use the right variant instead; see the [button guidance](button.md).
- Don't use `opacity` to make a secondary colour. It changes contrast unpredictably on raised surfaces.
- Don't add `!important` to beat a token. If a token is wrong, it is wrong for everyone, and we want to fix it once.

## Adding or changing a token

Tokens are a public interface: renaming one is a breaking change, and adding one is a promise to maintain it. The process is the same as for any Inkwell change described in [contributing](contributing.md), with three extra steps:

1. Open a proposal in the Inkwell repository with the token name, its purpose, its value in each theme, and two places it would be used. One use is not enough to earn a semantic token.
2. Run the contrast script, `pnpm tokens:contrast`, which checks every documented foreground and background pairing in both themes and prints any pair below the thresholds on the [a11y checklist](accessibility.md).
3. Bring it to design review. Colour tokens need sign-off from Priya Castellane or Dafydd Morrow.

Changing a value without renaming is a minor release if contrast still passes everywhere, and a major release if any documented pairing changes its contrast class.

## History

- **2023**: tokens v1, with literal names such as `grey-50` and `blue-primary`.
- **2024**: semantic names introduced alongside the literal ones; both coexisted for a year, which was a mistake.
- **July to October 2025**: tokens v2 under ENG-24. Surface colours renamed to `color.surface.*`, the spacing scale trimmed to steps of 4 px, the literal names removed. Shipped in Inkwell 3.0.
- **2026**: dark values added for every semantic colour token under ENG-26, the dark mode epic for Merchant Hub. See [theming](theming.md).

## Questions people ask

**Why is `color.surface.raised` white in light mode if it is meant to be raised?** Because in light mode elevation is shown by shadow. The token is about the role, and the role is "one level up".

**Can I use `space.2` plus `space.1` to get 12 px?** Use `space.3`. Adding tokens together in `calc()` works but hides intent, and the lint rule allows it only for negative margins.

**Our internal tool does not use React. Can we still use the tokens?** Yes. `@quillmoor/inkwell/tokens/css` ships the custom properties as a plain stylesheet with both themes, and `@quillmoor/inkwell/tokens/json` exports the raw values for anything else.

**Who decides when a token is deprecated?** The Design System team, in design review, with at least one minor release of warnings before removal.
