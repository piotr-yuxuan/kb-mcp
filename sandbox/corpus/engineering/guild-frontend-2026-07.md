---
title: "Frontend guild notes July 2026"
---

# Frontend guild notes July 2026

Wednesday 2026-07-15, 11:00 to 12:00 UK time, in the floor 3 project room at Quill House and on video.

| Role | Who |
|---|---|
| Chair | Priya (Design System) |
| Notes | Joss (Merchant Experience) |
| Present | Priya and Wren (Design System); Noor, Felix and Joss (Merchant Experience); Hamza (Platform) |
| Apologies | none |

## Dark mode: where ENG-26 stands

Felix opened with the audit that started ENG-26 in sprint 31. Merchant Hub had 212 colour values written straight into stylesheets and components. A codemod has replaced 170 of them with Inkwell tokens; the remaining 42 are in charts and in the email previews, and each needs a design decision rather than a search and replace.

Priya does not want every page choosing its own dark chart colours. Inkwell will publish chart palettes for both themes, and Merchant Hub will take its chart colours only from them. Until then, chart-heavy pages stay out of the dark theme.

Dark mode reaches merchants area by area, behind a Switchboard flag, starting with settings. How the theme is applied and how to test both themes is in [theming and dark mode](../design/theming.md); nobody should need a second write-up of it.

**Decided:** from sprint 34, a lint rule in `merchant-hub` rejects literal colour values in new code. Existing literals are allowed until the epic removes them.

## Keeping the a11y work from sliding back

Wren reported that two a11y regressions reached staging after ENG-25 closed in sprint 27: a new card layout clipped the focus ring of the links inside it, and a toast took focus away from the form the merchant was filling in. Both were found by chance during a demo, not by any check of ours.

Discussion:

- Automated checks catch some of this, but not focus order or what a screen reader announces.
- Joss suggested that every new screen gets a keyboard-only pass at [design review](../design/design-review.md), with the [a11y checklist](../design/accessibility.md) open.
- Hamza can add an automated a11y check to `merchant-hub`'s CI, run against the main journeys and against Inkwell's component examples.

**Decided:** both. The automated check is advisory for a sprint, then required.

## Token aliases left over from ENG-24

Wren counted three deprecated token aliases from ENG-24 still in use in Merchant Hub, all in reports. Inkwell will remove the aliases in its next major version. Noor agreed that Merchant Experience removes them before dark mode work reaches reports, since the dark theme does not define the old names. The current names are in [Inkwell design tokens and principles](../design/tokens.md).

## Bundle size

Joss showed that Merchant Hub's main bundle grew by about a fifth since January, mostly from a date library pulled in twice under different versions. Hamza suggested a size budget as an extra check in `merchant-hub`'s `ci.yaml`, the way [continuous integration](continuous-integration.md) describes for repository-specific checks.

**Decided:** a budget at the current size plus 5%, failing the build when exceeded. Raising the budget needs a sentence in the change description saying why.

## Actions

| Action | Owner | Due |
|---|---|---|
| Lint rule against literal colours in `merchant-hub` | Felix | Sprint 34 |
| Chart palettes for both themes in Inkwell | Priya | Sprint 35 |
| Automated a11y check in CI, advisory then required | Hamza | Sprint 34, required from sprint 35 |
| Keyboard-only pass added to the design review agenda | Wren | Next design review |
| Remove the three deprecated token aliases from reports | Noor | Before ENG-26 reaches reports |
| Bundle size budget check | Joss | Sprint 34 |

Next meeting: Wednesday 2026-08-19. Chair: Noor.
