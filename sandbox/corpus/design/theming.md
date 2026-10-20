---
title: "Theming and dark mode"
---

# Theming and dark mode

*Written by Joss Penhaligon (Merchant Experience) and Teodor Ashby (Design System). Owned jointly by `#team-inkwell` and `#team-merchant-hub`. Last reviewed 2026-10-14.*

Inkwell supports two themes, light and dark. Merchant Hub is moving to dark mode under epic ENG-26, and every team that builds on Inkwell will, sooner or later, be asked "does this work in dark?". This page explains how theming works, the rules that make it work, how to test it, and where the Merchant Hub rollout stands.

The short version:

1. The theme is set by one attribute on the root element: `data-theme="dark"` or `data-theme="light"`.
2. Every colour comes from a token. A hard-coded colour is a dark mode bug waiting to be found.
3. Test both themes, every time, automatically and by eye.

## How theming works

Inkwell's semantic tokens (see [design tokens](tokens.md)) are CSS custom properties. The light values are defined on `:root`; the dark values redefine the same properties under the dark theme selector. Components only ever read the semantic properties, so they change with the theme without any JavaScript.

```text
:root,
:root[data-theme="light"] {
  color-scheme: light;
  --ink-color-surface-default: #FFFFFF;
  --ink-color-surface-raised: #FFFFFF;
  --ink-color-text-primary: #1A1D23;
  --ink-color-focus-ring: #2B4ACB;
  /* ...the rest of the semantic tokens */
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --ink-color-surface-default: #14161A;
  --ink-color-surface-raised: #1D2026;
  --ink-color-text-primary: #ECEEF2;
  --ink-color-focus-ring: #8EA6FF;
}
```

The `color-scheme` declaration matters more than it looks. It tells the browser to draw native scrollbars, date pickers and autofill backgrounds in the matching scheme. Without it, a dark page gets a glaring white scrollbar.

You never write those blocks yourself: they are generated from the token source and shipped in `@quillmoor/inkwell/tokens/css`.

## Switching themes

### The attribute

The attribute goes on the `html` element, and only there. Setting `data-theme` on an inner `div` is not supported: portalled content such as modals, menus and toasts renders at the end of `body` and would escape the theme.

| Value | Result |
|---|---|
| attribute absent | Light theme |
| `data-theme="light"` | Light theme |
| `data-theme="dark"` | Dark theme |

### The provider

In React, let `ThemeProvider` manage the attribute. It accepts a `theme` of `light`, `dark` or `system`; `system` follows the operating system's preference through `prefers-color-scheme` and updates live when it changes.

```typescript
import { ThemeProvider, useTheme } from "@quillmoor/inkwell";

export function App({ savedPreference }: { savedPreference: ThemePreference }) {
  return (
    <ThemeProvider theme={savedPreference}>
      <Routes />
    </ThemeProvider>
  );
}

export function AppearanceSetting() {
  const { preference, resolvedTheme, setPreference } = useTheme();
  return (
    <RadioGroup
      label="Appearance"
      value={preference}
      onChange={setPreference}
      options={[
        { value: "light", label: "Light" },
        { value: "dark", label: "Dark" },
        { value: "system", label: "Match my device" },
      ]}
      hint={`Currently showing the ${resolvedTheme} theme.`}
    />
  );
}
```

`resolvedTheme` is always `light` or `dark`; use it when a value genuinely has to differ by theme in JavaScript, which should be rare.

### Avoiding the flash

If the attribute is set only after React hydrates, users with the dark preference see a white flash on every page load. Merchant Hub avoids it with a tiny script in the document head that runs before first paint. It reads the preference from the `qm_theme` cookie, which the settings page writes alongside the user's saved preference, and sets the attribute immediately.

```typescript
// Inlined into the document head by the Merchant Hub server template.
(function applyTheme() {
  const match = document.cookie.match(/(?:^|; )qm_theme=(light|dark|system)/);
  const preference = match ? match[1] : "light";
  const dark =
    preference === "dark" ||
    (preference === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
})();
```

`ThemeProvider` reads the attribute on mount and takes over from there, so the two never disagree.

## The rules

### Every colour through tokens

This is the rule that makes everything else possible. A component that reads `--ink-color-text-primary` is correct in both themes for free. A component that says `#1A1D23` is correct in exactly one.

- No hex, `rgb()`, `hsl()` or named colours in product stylesheets, inline styles or styled components. The lint rule `inkwell/no-raw-colour` enforces this in Merchant Hub and fails the build.
- No `palette.*` tokens in product code. Palette values do not change between themes, so a palette reference is a hard-coded colour with extra steps.
- No `opacity` or `filter: brightness()` to derive a colour. The result depends on what is underneath, which is different in each theme.
- `currentColor` is fine and often the right answer for icons.
- If no token fits, ask in `#team-inkwell` rather than adding a colour locally. We would rather add a token than discover the gap in a dark mode bug report.

There is one escape hatch: `ThemedValue`, for third-party code that insists on a literal colour string, such as a charting library's configuration object. It takes a token name and returns the resolved value for the current theme, re-rendering when the theme changes. Treat it as a last resort and leave a comment saying why.

### Dark is not inverted light

The dark theme was designed, not computed. Some decisions that surprise people:

- **The page is not black.** `color.surface.default` is `#14161A`. Pure black behind white text causes halation for many readers, and it leaves no room below the page for sunken surfaces.
- **Elevation is lightness, not shadow.** In light, a raised card is white on white with a shadow. In dark, shadows are nearly invisible, so `color.surface.raised` is lighter than the page and `color.surface.overlay` lighter again. This is why a hard-coded white card glows in dark mode.
- **Text is not pure white.** `color.text.primary` is `#ECEEF2`, which still clears 4.5:1 comfortably on every dark surface.
- **Accents are lighter and less saturated.** The primary blue in dark is `#8EA6FF` with dark text on top, because the light theme's `#2B4ACB` would not reach contrast against a dark surface.
- **Status colours keep their meaning.** Success is still green and critical still red, retuned for contrast.

### Images, logos and charts

- **Merchant logos** are uploaded by merchants, usually dark marks on transparent backgrounds. Always place them on a `LogoChip`, which draws a `color.surface.raised` tile with padding in light and a light neutral tile in dark, so a black logo never disappears.
- **Illustrations** owned by Inkwell have dark variants. Use `ThemedImage` with `lightSrc` and `darkSrc`; it follows the `data-theme` attribute. Don't use `picture` with a `prefers-color-scheme` media query: it follows the operating system, not the user's choice in Merchant Hub.
- **Charts** use `color.chart.1` to `color.chart.8`, which have tuned dark values, and draw gridlines with `color.border.subtle`. Adjacent series must reach 3:1 against each other and against the surface in both themes.
- **Screenshots and documents** are not themed. Show them on a `color.surface.sunken` frame so that a white screenshot reads as an object, not as a hole in the page.

### What is not themed

- Emails sent by `notify` stay light. Mail clients apply their own dark treatments unpredictably, and we design emails to survive them rather than to fight them.
- PDF statements and exports stay light, because they are printed.
- Beacon, the public status page, has its own styles and is out of scope.

## Testing both themes

Every change that touches the interface is tested in both themes. "I checked it in light" is not a review comment we accept.

**In Storybook.** Every story has a theme switch in the toolbar. The "Side by side" mode renders the story in both themes at once and is the quickest way to spot a missed token.

**Visual regression.** Snapshots are taken of every Inkwell story in both themes on every pull request. A change that alters only the dark snapshot is often the first sign of a raw colour.

**End-to-end.** Merchant Hub's Playwright suite runs the main journeys under both themes:

```typescript
import { test, expect } from "@playwright/test";

for (const theme of ["light", "dark"] as const) {
  test.describe(`payouts list (${theme})`, () => {
    test.use({ storageState: { cookies: [themeCookie(theme)], origins: [] } });

    test("shows the next payout date", async ({ page }) => {
      await page.goto("/payouts");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByRole("heading", { name: "Next payout" })).toBeVisible();
      await expectNoSeriousAxeViolations(page);
    });
  });
}
```

**Contrast.** `pnpm tokens:contrast` checks every documented token pairing in both themes against the thresholds on the [a11y checklist](accessibility.md): 4.5:1 for text and 3:1 for interface parts. Custom pairings in product code are your responsibility.

**By eye.** Before merging, open the feature in dark with the screen brightness turned down, and once more in a bright room. Look for: white flashes on navigation, focus rings that vanish, borders that disappear, images with white boxes around them, and charts whose series blur together.

## Rollout in Merchant Hub

Dark mode for Merchant Hub is epic ENG-26, which started in ENG Sprint 31 on 8 June 2026 and is planned to finish in ENG Sprint 40, the current sprint. The product case is in the [dark mode brief](../product/brief-dark-mode.md). The story at its heart was to switch the theme with `data-theme="dark"` rather than with a separate stylesheet, so that the same components serve both themes.

What shipped in Inkwell:

- **3.3** (July 2026): dark values for every semantic colour token, `ThemeProvider` with `system`, and `color-scheme` in the generated stylesheet.
- **3.4** (September 2026): dark chart palette, `ThemedImage`, `LogoChip` and `ThemedValue`.

What is live in Merchant Hub, behind the Switchboard flag `sb.merchant-hub.dark-mode` (see [feature flags](../release/feature-flags.md)):

| Page group | Converted | Notes |
|---|---|---|
| Home | Yes | |
| Payments | Yes | Including the payment detail drawer |
| Payouts | Yes | |
| Refunds | Yes | |
| Settings | Yes | Hosts the appearance setting |
| Developers (API keys, webhooks) | Yes | Code samples use the sunken surface |
| Reports | In progress | Chart migration under way in sprint 40 |
| Disputes | Not started | Evidence uploads show merchant documents |
| Onboarding | Not started | Shares components with the public sign-up flow |

The flag has been on for all Quillmoor staff since 17 August 2026 and for a pilot of 120 merchants since 21 September 2026. Pages not yet converted pass `forceTheme="light"` to the page layout, which pins the attribute to light while they are open and restores the user's choice on the way out. It is not elegant, but it is better than a half-dark page.

Bringing dark mode to every Merchant Hub page, including onboarding, is an idea on the Product Discovery board in `PRB`. It is not committed for this epic.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A card glows white in dark | Hard-coded `#FFFFFF` or a `palette.*` token | Use `color.surface.raised` |
| Text disappears in dark | Text colour hard-coded dark | Use `color.text.primary` or `color.text.secondary` |
| White flash on navigation | Attribute set after hydration | Use the head script; check the `qm_theme` cookie is written |
| Modal is light on a dark page | `data-theme` set on an inner element | Set it on `html` only |
| Scrollbars stay light | Old stylesheet without `color-scheme` | Upgrade to Inkwell 3.3 or later |
| Chart series indistinguishable | Library default palette | Pass `color.chart.*` through `ThemedValue` |
| Focus ring invisible on a coloured fill | Custom focus style | Use the two-tone ring from the [button page](button.md) |

Questions about the rollout go to `#team-merchant-hub`; questions about tokens and components to `#team-inkwell`.
