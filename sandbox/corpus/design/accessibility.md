---
title: "Accessibility checklist"
---

# Accessibility checklist

Owners: Dafydd Morrow and Priya Castellane, Design System team. Questions go to `#team-inkwell`.
Last reviewed: 2026-10-06. Applies to: Merchant Hub, every Inkwell component, and internal tools built on Inkwell.

## What this page is for

Accessibility, which we shorten to **a11y** (an "a", eleven letters, a "y"), means that people can use what we build whatever their vision, hearing, movement, cognition or circumstances. A merchant reading payout figures with a screen magnifier, a finance assistant who only uses the keyboard because of a wrist injury, a seller checking a refund on a phone in bright sunlight: all of them are our users, and none of them should need a workaround.

Our standard is **WCAG 2.2 at level AA**. That is the bar for every Inkwell component and every Merchant Hub page, new or changed. Internal tools aim for the same bar; where a tool falls short, the gap is recorded in its README with a date to close it.

This page is a checklist rather than an essay. Use it in three places:

1. **In design**, before a design goes to [design review](design-review.md). The reviewer will ask about the items marked with a star.
2. **In code review**, where the pull request template links here and asks the author to tick the sections that apply.
3. **Before release**, as the manual pass described under "Testing", which takes about fifteen minutes for a typical feature.

Inkwell components meet the checklist out of the box when used as documented. Most a11y bugs we see come from product code around the components: a custom colour, a click handler on a `div`, a dialog built by hand. Each section says what Inkwell does for you and what remains yours.

## 1. Colour and contrast

- [ ] ★ **Text contrast is at least 4.5:1** against its background. This applies to all text, large or small. WCAG relaxes the ratio for large text; Inkwell does not, because our "large" headings sit next to small figures and we want one rule.
- [ ] ★ **Interface parts reach 3:1** against what surrounds them: input borders, checkbox outlines, the boundary of a secondary button, icons that carry meaning, chart segments next to each other, and the focus ring.
- [ ] Colour is never the only signal. A failed payout has a red icon **and** the word "Failed". A required field has a label suffix, not just a red asterisk. Chart series differ in pattern or label as well as hue.
- [ ] Contrast is checked in **both themes**. A pairing that passes in light can fail in dark. The contrast script (`pnpm tokens:contrast`) checks every documented token pairing; your custom combinations are your responsibility. See [theming](theming.md).
- [ ] Disabled controls are exempt from contrast rules in WCAG, but their label must still be legible enough to read. Inkwell's disabled text sits at about 3:1.

What Inkwell does: semantic token pairings are tested in continuous integration. What remains yours: anything that uses an image, a chart palette, a brand colour supplied by a merchant, or an opacity you added.

## 2. Focus

- [ ] ★ **Focus is always visible.** Every element that can receive keyboard focus shows a focus indicator, in every state, in both themes. No exceptions for "it looks cleaner without".
- [ ] Never write `outline: none` or `outline: 0` without drawing a replacement indicator of at least the same strength. The lint rule `inkwell/no-outline-none` fails the build if you try.
- [ ] The focused element is **not hidden** by sticky headers, cookie banners or toasts (WCAG 2.4.11). Merchant Hub's sticky table header uses `scroll-padding-top` so that focused rows scroll into view below it.
- [ ] Focus order follows reading order. If you rearrange content visually with CSS grid or `order`, check the tab order still makes sense.
- [ ] When a dialog opens, focus moves into it; when it closes, focus returns to the element that opened it. The [modal dialog](modal.md) does this; a hand-built overlay will not.
- [ ] After a page action removes the focused element, such as deleting a row, move focus somewhere sensible: the next row, or the table heading.

The Inkwell focus ring is two-tone: a 2 px inner ring in `color.focus.gap` and a 2 px outer ring in `color.focus.ring`, drawn with `outline` and `box-shadow` so that it survives `overflow: hidden` on most containers.

```text
.my-custom-control:focus-visible {
  outline: 2px solid var(--ink-color-focus-ring);
  outline-offset: 2px;
  box-shadow: 0 0 0 2px var(--ink-color-focus-gap);
}
```

The two tones exist because of a real bug. Under ENG-25 the December 2025 audit found the focus ring invisible on the destructive button: a red ring on a red fill. The inner gap now separates the ring from any fill colour. The [button page](button.md) tells the full story.

## 3. Keyboard

- [ ] ★ Every action you can take with a pointer, you can take with the keyboard alone.
- [ ] Interactive elements are real interactive elements: `button`, `a` with `href`, `input`, `select`. A `div` with `onClick` is not focusable and has no role.
- [ ] Composite widgets follow the expected keys: arrow keys move within a menu, tab list or radio group; Tab moves out of it.
- [ ] There is no keyboard trap. The only intentional trap is inside a modal dialog, and Escape always releases it.
- [ ] Single-character shortcuts are off by default, or can be remapped or turned off (WCAG 2.1.4). Merchant Hub's "/" to search is the only one enabled by default and can be switched off in settings.

## 4. Target size

- [ ] ★ **Pointer targets are at least 24 by 24 CSS pixels** (WCAG 2.5.8), or have enough space around them that a 24 px circle centred on each target does not overlap another target.
- [ ] Inkwell's smallest controls are 32 px high (small buttons, compact table row actions), so this mostly bites custom controls: close crosses, inline icon actions, chart legend toggles.
- [ ] Links inside a sentence are exempt, but a row of standalone links in a footer is not.
- [ ] On touch layouts, aim for 44 by 44 CSS pixels. This is our house rule for mobile, not a WCAG AA requirement.

```typescript
// A custom inline action that would be 16 px: pad the hit area, not the icon.
const InlineRemove = ({ onRemove, label }: { onRemove: () => void; label: string }) => (
  <button
    type="button"
    className="inline-remove"   // min-width and min-height: 24px, icon stays 16 px
    aria-label={label}
    onClick={onRemove}
  >
    <Icon name="close" size={16} />
  </button>
);
```

## 5. Structure and semantics

- [ ] Each page has one `h1`, and headings do not skip levels.
- [ ] Page regions use landmarks: `header`, `nav`, `main`, `footer`. Merchant Hub's layout component provides them; don't add a second `main`.
- [ ] Lists are lists and tables are tables. A data table has column headers with `scope`, and a caption or a heading referenced by `aria-labelledby`.
- [ ] ARIA is a last resort. If a native element does the job, use it. A wrong ARIA role is worse than none.
- [ ] The page `title` changes on navigation and names the page first: "Payouts, Merchant Hub", not "Merchant Hub, Payouts".

## 6. Forms

- [ ] ★ Every field has a visible label. Placeholder text is not a label: it disappears as soon as someone types. The [text field](text-field.md) requires a `label` prop for this reason.
- [ ] Errors are shown in text, next to the field, and linked to it with `aria-describedby`. On submit, focus moves to an error summary at the top of the form.
- [ ] Required and optional fields are marked in words.
- [ ] Fields that collect personal details use the right `autocomplete` value (WCAG 1.3.5), so browsers and password managers can help.
- [ ] Don't ask for the same information twice in one flow (WCAG 3.3.7). If a seller's address was entered on step one, prefill it on step three.
- [ ] Sign-in does not depend on a memory or puzzle test (WCAG 3.3.8). Password and one-time code fields accept paste.

## 7. Images, icons and charts

- [ ] Informative images have alternative text that says what the image tells you, not what it looks like.
- [ ] Decorative images and icons next to a text label are hidden from assistive technology. Inkwell's `Icon` does this when you omit `label`.
- [ ] Charts have a text equivalent: a summary sentence and, for anything a merchant might need to act on, the underlying table.

## 8. Motion and flashing

- [ ] Nothing flashes more than three times in one second.
- [ ] Non-essential animation stops when the user has asked for reduced motion. Inkwell components read `prefers-reduced-motion`; your custom transitions must too. The [motion guidelines](motion.md) give the pattern.
- [ ] Anything that moves, scrolls or updates on its own for more than five seconds can be paused.

## 9. Dynamic content and status messages

- [ ] Status messages that appear without a focus change are announced (WCAG 4.1.3). Use the [toast component](toast.md), which uses a polite live region for most tones and an assertive one for errors.
- [ ] Loading states are announced once, not on every progress tick.
- [ ] Session time-outs warn at least two minutes ahead and let the user extend.

## 10. Zoom, reflow and text spacing

- [ ] Content reflows without horizontal scrolling at 320 CSS pixels wide, which is what 400% zoom on a laptop looks like (WCAG 1.4.10). Data tables are the allowed exception: they may scroll sideways inside their own container.
- [ ] Nothing breaks when users increase letter, word and line spacing (WCAG 1.4.12). Avoid fixed heights on containers of text.
- [ ] Text is set in relative units so that browser font-size settings work.

## 11. Dragging

- [ ] Anything done by dragging can also be done with a single pointer action without dragging (WCAG 2.5.7). Reordering table columns in Merchant Hub works by drag and through the column menu's "Move left" and "Move right".

## Testing

Automated tests catch about a third of real problems. They are necessary and nowhere near sufficient.

**Automated, in continuous integration:**

- axe-core runs against every Storybook story in both themes. Violations with impact "serious" or "critical" fail the Inkwell build.
- Merchant Hub's Playwright suite runs axe-core on the twenty most visited pages after each merge, again in both themes.
- The lint rules `inkwell/no-outline-none`, `inkwell/no-raw-colour` and `jsx-a11y/no-static-element-interactions` run on every pull request.

**Manual, before release (about fifteen minutes):**

1. Unplug the mouse, or at least ignore it. Complete the main task of the feature using only Tab, Shift+Tab, Enter, Space, Escape and the arrow keys. Watch the focus ring the whole way.
2. Zoom the browser to 200% and then 400%. Check nothing overlaps or disappears.
3. Switch to the dark theme and repeat step 1 quickly.
4. Turn on a screen reader (NVDA, or the one built into your laptop's or phone's operating system). Listen to the page headings list, then complete the main task. Every control should announce a name, a role and a state.
5. Turn on reduced motion in the operating system and check animations stop.

Write down what you tested in the pull request. "Keyboard and zoom checked, screen reader not checked" is a perfectly good note; silence is not.

## Who owns what

| Area | Inkwell guarantees | Product team owns |
|---|---|---|
| Contrast | Token pairings in both themes | Custom colours, images, charts |
| Focus | Ring on every component; dialog focus management | Focus after page actions; custom controls |
| Keyboard | Component key handling | Page flows, custom widgets |
| Target size | Component sizes | Custom icon actions |
| Labels | Required label props | Meaningful label text |
| Announcements | Toasts and loading states | Choosing to use them |

## Background: the 2025 to 2026 remediation

Epic ENG-25, "Accessibility remediation", ran from sprint 19 to sprint 27 (22 December 2025 to 26 April 2026). It began with an audit of Merchant Hub against WCAG 2.2 AA that logged 47 issues. Forty-one sat in Inkwell components and shipped as fixes in [Inkwell 3.2](release-notes-inkwell-3-2.md); six sat in Merchant Hub code and were fixed by Merchant Experience. The largest classes were focus visibility (the destructive button among them), targets under 24 by 24 CSS pixels on icon actions, and form errors that were not linked to their fields. This checklist was rewritten at the end of the epic so that the same classes are caught in design review instead of in an audit.

## Reporting a problem

If you find an a11y bug in an Inkwell component, raise a ticket in the ENG project naming the component and the WCAG success criterion, and post the link in `#team-inkwell`. If it is in a product page, raise it with the owning team; for Merchant Hub, that is Merchant Experience in `#team-merchant-hub`. Blocking issues in a release, such as a flow that cannot be completed by keyboard, hold the release until fixed.
