---
title: "Inkwell 3.0 release notes"
---

# Inkwell 3.0 release notes

**Released:** 29 October 2025 · **Type:** major · **Release manager:** Teodor Ashby · **Epic:** ENG-24 · **Upgrade effort:** about half a day for a mid-sized app, mostly automated

## Summary

Inkwell 3.0 ships tokens v2. Every colour token now names its role rather than its look, surface colours move to `color.surface.*`, and the spacing scale is trimmed to steps of 4 px. The old names are removed, not aliased; a codemod rewrites them for you. This is the first major release since 2.0 in 2023, and the next one is not expected for at least a year.

## Highlights

- **Surface tokens.** `color.surface.default`, `color.surface.raised`, `color.surface.sunken` and `color.surface.overlay` replace the old `color.bg.*` family. They are the foundation for a future dark theme. See [design tokens](tokens.md).
- **A stricter spacing scale.** Every space is a multiple of 4 px, from `space.1` (4 px) to `space.16` (64 px).
- **Typed tokens in TypeScript.** `import { tokens } from "@quillmoor/inkwell/tokens"` gives autocompletion for every semantic token.
- **Two lint rules**, `inkwell/no-raw-colour` and `inkwell/spacing-scale`, catch values that bypass tokens.

## Breaking changes

| Change | What to do |
|---|---|
| Literal colour names such as `grey-50` and `blue-primary` removed | Run the codemod, which maps each to its semantic token |
| `color.bg.page` renamed `color.surface.default` | Run the codemod |
| `color.bg.card` renamed `color.surface.raised` | Run the codemod |
| `color.bg.well` renamed `color.surface.sunken` | Run the codemod |
| `color.bg.modal` renamed `color.surface.overlay` | Run the codemod |
| `color.fg.default` and `color.fg.muted` renamed `color.text.primary` and `color.text.secondary` | Run the codemod |
| CSS custom property prefix changed from `--qm-` to `--ink-` | Run the codemod; check hand-written stylesheets |
| `space.7`, `space.9`, `space.11` and the 2 px half-step removed | The codemod rounds to the nearest step and leaves a comment; review each one |
| `Button` default `variant` is now `secondary` | Add `variant="primary"` where you relied on the old default |
| `Button` default `type` is now `button` | Add `type="submit"` to submitting buttons |
| `Banner` prop `kind` renamed `tone` | Run the codemod |
| React 18 is the minimum | Upgrade React first |

## New

- `Stack` layout component, with `gap` taking spacing tokens.
- `size.control.small`, `size.control.medium` and `size.control.large` tokens, at 32, 40 and 48 px.
- `font.numeric.*` tokens with tabular figures for amounts.
- `@quillmoor/inkwell/tokens/css` for apps that do not use React.

## Fixed

- `Select` menus no longer open off-screen near the bottom of a modal.
- `DataTable` keeps its scroll position when rows update.
- `Tooltip` no longer stays open after its trigger is removed.

## Deprecated

- `Toast` option `type` is deprecated in favour of `tone`. It still works and logs a warning in development.

## Upgrading

```bash
pnpm add @quillmoor/inkwell@^3.0.0
pnpm exec inkwell-codemod tokens-v2 src/
pnpm lint
```

The codemod touches TypeScript, CSS and styled components. It prints a summary of what it changed and lists the spacing values it rounded, which need a human look. In Merchant Hub it rewrote 3,412 token references; 57 rounded spacing values needed manual review. Merchant Hub moved to 3.0 on 12 November 2025.

If something does not migrate cleanly, ask in `#team-inkwell` with the file and the error. [Contributing to Inkwell](contributing.md) explains how versions and deprecations work.

## Thanks

To Merchant Experience for piloting the codemod on Merchant Hub, to Dafydd Morrow for retuning every colour pairing, and to everyone who answered the token naming survey in July.
