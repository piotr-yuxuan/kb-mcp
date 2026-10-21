---
title: "Toast notification component"
---

# Toast notification component

Owner: Teodor Ashby. Last reviewed 2026-05-12.

A toast is a short message that confirms something just happened, without stopping the user. "Refund issued." "Webhook endpoint saved." "Export started; we will email you when it is ready."

Toasts are for feedback on the user's own actions. They are not for system alerts, outages or anything the user must read: those belong in a banner on the page, which stays until it is dealt with.

## Usage

```typescript
import { useToast } from "@quillmoor/inkwell";

export function useArchiveReport() {
  const toast = useToast();

  return async (report: Report) => {
    await api.reports.archive(report.id);
    toast.show({
      tone: "success",
      message: `${report.name} archived`,
      action: { label: "Undo", onAction: () => api.reports.restore(report.id) },
    });
  };
}
```

## Options

| Option | Values | Default | Notes |
|---|---|---|---|
| `tone` | `info`, `success`, `warning`, `error` | `info` | Sets the icon and the live region |
| `message` | string, at most 100 characters | required | One sentence, no full stop needed for fragments |
| `action` | label and handler | | At most one action. Typically "Undo" or "View" |
| `duration` | milliseconds, or `null` | 6,000; 10,000 with an action | `null` keeps the toast until dismissed |

Error toasts never dismiss themselves: an error that disappears before it is read is worse than no message.

## Behaviour

- Toasts appear bottom right on wide screens and bottom centre under 600 px, above everything except modals.
- At most three are visible. A fourth pushes out the oldest that is not an error.
- The timer pauses while the pointer is over the toast or focus is inside it, and while the browser tab is hidden.
- Pressing F6 moves focus to the toast region, so keyboard users can reach the action button.
- Toasts slide in with `motion.duration.base` and fade out with `motion.duration.fast`; with reduced motion they simply appear. See the [motion guidelines](motion.md).

## a11y notes

Info, success and warning toasts are announced through a polite live region (`role="status"`); errors through an assertive one (`role="alert"`). The live region exists from page load, so the first toast is not missed. A toast with an action must not be the only way to do that thing: "Undo" in a toast is a convenience, and the same result must be reachable from the page.

## Do and don't

- **Do** describe the outcome, in the past tense: "Payout schedule updated".
- **Do** offer "Undo" instead of a confirmation dialog when the action is reversible.
- **Don't** use a toast for errors that need the user to fix a form. Show the error at the field; see [text field](text-field.md).
- **Don't** fire a toast for every row in a bulk action. One toast: "12 refunds issued".
- **Don't** put links to other pages in the message itself; use the `action`.

Wording follows the [content style guide](content-style.md).
