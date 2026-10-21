---
title: "Icon library"
---

# Icon library

Maintained by Dafydd Morrow and the Design System team. Last reviewed 2026-04-22.

Inkwell ships 236 icons, drawn on a 24 px grid with a 1.5 px stroke and exported as React components. They live in `@quillmoor/inkwell/icons` and are tree-shaken, so you only pay for what you import.

```typescript
import { Icon } from "@quillmoor/inkwell";

<Icon name="payout" size={20} />                         // decorative, hidden from screen readers
<Icon name="warning" size={16} label="Payout delayed" /> // informative, announced
```

## Sizes

| `size` | Use |
|---|---|
| 16 | Inline with body text, inside small buttons, table cells |
| 20 | Inside medium and large buttons, navigation, form prefixes |
| 24 | Empty states, page headers, standalone status |

Other sizes are not supported. Icons are optimised for these three, and an 18 px icon is a blurry 24 px icon. Colour comes from `currentColor`, so an icon takes the colour of its text; set colour with a `color.*` token on the parent, never on the icon.

## Naming

Names are lowercase, hyphenated, and describe what the icon **shows**, not what it is used for in one place: `arrow-left`, not `back`; `bank`, not `settlement`. Product-specific concepts are the exception, because they have no generic picture: `payout`, `refund`, `chargeback`, `merchant`.

Filled variants end in `-filled` and are used only for selected states, such as the active item in the navigation.

## Decorative or informative?

- If the icon sits next to text that says the same thing, it is **decorative**: omit `label` and the icon is hidden with `aria-hidden`.
- If the icon is the only thing carrying the meaning, it is **informative**: pass `label`.
- An icon-only button takes its label from the button's `aria-label`, not from the icon. See the [button page](button.md).

## Do and don't

- **Do** pair status icons with words. A red circle means nothing to someone who cannot see red.
- **Do** mirror directional icons in right-to-left layouts; `Icon` does it for names starting `arrow-` and `chevron-`.
- **Don't** use an icon as decoration in a heading just to fill space.
- **Don't** import SVG files from elsewhere into product code. If an icon is missing, request it.
- **Don't** reuse an icon for an unrelated meaning. `key` means API keys in Merchant Hub; it does not also mean "password".

## Requesting a new icon

1. Search the library in Storybook and in the design tool's Inkwell library first, including synonyms.
2. Post in `#team-inkwell` with the concept, where it will appear, and a rough sketch if you have one.
3. Dafydd or another designer on the team draws it to the grid, usually within one sprint.
4. It ships in the next minor release. The steps for code changes are in [contributing to Inkwell](contributing.md).

Brand marks, such as the Quillmoor logo, are not icons and are not in this library.
