---
title: "Motion guidelines"
---

# Motion guidelines

Owner: Dafydd Morrow. Last reviewed 2026-03-04.

Motion in Inkwell has one job: to help people follow what changed. A panel slides in from the side it lives on; a removed row fades so the eye notices the gap; a dialog grows from the centre so it reads as "on top". Motion that does not explain a change is decoration, and in a dashboard about money we have very little room for decoration.

## Motion tokens

Use the tokens; never write a duration or an easing curve by hand.

| Token | Value | Use |
|---|---|---|
| `motion.duration.instant` | 0 ms | State changes that should not animate, and every duration under reduced motion |
| `motion.duration.fast` | 100 ms | Hover and press feedback, fades out, tooltips |
| `motion.duration.base` | 200 ms | Most entrances: menus, toasts, modals |
| `motion.duration.slow` | 300 ms | Large surfaces: drawers, full-screen dialogs on mobile |
| `motion.easing.standard` | `cubic-bezier(0.2, 0, 0, 1)` | Things moving on screen |
| `motion.easing.enter` | `cubic-bezier(0, 0, 0, 1)` | Things arriving |
| `motion.easing.exit` | `cubic-bezier(0.3, 0, 1, 1)` | Things leaving |
| `motion.delay.spinner` | 150 ms | Wait before showing a spinner |
| `motion.minimum.spinner` | 400 ms | Keep a spinner at least this long once shown |

Nothing in Inkwell animates for longer than 300 ms, and nothing should in product code either. If an animation feels like it needs 500 ms, the movement is probably too large.

The two spinner tokens explain a behaviour people ask about: a [button](button.md) in its loading state shows no spinner for quick actions, and a spinner that does appear does not vanish after a flicker.

## Reduced motion

Some people get dizzy, nauseous or distracted from animation. When the operating system's reduced motion setting is on, Inkwell sets every duration token to `motion.duration.instant`, except fades, which drop to 100 ms so that changes are still noticeable. Your custom animations must follow the same rule.

```text
.payout-timeline__step {
  transition: transform var(--ink-motion-duration-base) var(--ink-motion-easing-standard);
}

@media (prefers-reduced-motion: reduce) {
  .payout-timeline__step {
    transition: none;
  }
}
```

In React, `useReducedMotion()` returns `true` when you should skip a JavaScript-driven animation:

```typescript
import { useReducedMotion } from "@quillmoor/inkwell";

export function useCountUp(target: number) {
  const reduced = useReducedMotion();
  const animated = useAnimatedNumber(target, {
    durationToken: "motion.duration.slow",
    disabled: reduced,
  });
  return reduced ? target : animated;
}
```

## Do and don't

- **Do** move things along the path they would take in space: a drawer from its edge, a menu from its trigger.
- **Do** animate opacity and transform. They are cheap, smooth and do not shift layout.
- **Don't** animate width, height, top or left on large elements; they jank on slow laptops.
- **Don't** animate numbers counting up on balances or amounts by default. Merchants read the number mid-count and panic. If you must, keep it to `motion.duration.slow` and skip it under reduced motion.
- **Don't** loop anything. Spinners are the exception, and they stop when the work stops.
- **Don't** flash. Nothing may flash more than three times in a second, per the [a11y checklist](accessibility.md).

## Edge cases

- **Content that updates often**, such as a live payments feed, should not animate each update. Highlight new rows once with a background fade of `motion.duration.slow`, then stop.
- **Route changes** in Merchant Hub do not animate. Page transitions slow down people who move between pages all day.
- **Hidden tabs** pause animations automatically in the browser; do not rely on an animation's end event to drive application logic.
