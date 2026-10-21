---
title: "Button component"
---

# Button component

**Owner:** Teodor Ashby, Design System team (`#team-inkwell`)
**Status:** stable since Inkwell 1.0; current API since 3.0
**Last reviewed:** 2026-08-27

Buttons start actions. They are the most used component in Merchant Hub (roughly 1,900 instances at the last count) and the one most often bent out of shape, so this page is longer than most. If you only need the props, skip to the props table.

```typescript
import { Button } from "@quillmoor/inkwell";
```

## When to use a button, and when not to

Use a button when pressing it **does something**: saves a form, issues a refund, opens a dialog, starts an export.

Use a link instead when pressing it **goes somewhere**: another page, a document, an anchor further down. A button that navigates breaks the browser's "open in new tab" and confuses screen-reader users, who hear "button" and expect an action.

A rough test: if the action still makes sense when the user middle-clicks, it is a link.

## Variants

Inkwell has four variants. Pick by the weight of the action, not by the colour you want.

| Variant | Looks like | Use it for | Per view |
|---|---|---|---|
| `primary` | Filled with `color.action.primary.background` | The single most important action on the page or in a dialog: "Save changes", "Issue refund", "Create payout" | At most one per region |
| `secondary` | Outlined, transparent fill | Alternatives to the primary action: "Cancel", "Save as draft", "Export CSV" | Any number |
| `tertiary` | Text only, no border until hover | Low-emphasis actions in dense places: table row actions, "Show more", "Clear filters" | Any number |
| `destructive` | Filled with `color.action.destructive.background` | Actions that remove or end something and cannot be quietly undone: "Delete webhook", "Revoke API key", "Close account" | At most one per region |

A "region" is a card, a dialog, or the page header. A page can have a primary action in its header and another in a dialog it opens; it should not have two primary buttons side by side.

There is no "ghost", "link" or "success" variant, and we are not adding one. Requests for a green "Approve" button come up every quarter; the answer is a primary button whose label says "Approve".

## Sizes

| Size | Height | Horizontal padding | Font token | Typical place |
|---|---|---|---|---|
| `small` | 32 px | `space.3` (12 px) | `font.label.medium` | Table rows, toolbars, filters |
| `medium` | 40 px | `space.4` (16 px) | `font.label.medium` | Forms, dialogs, page headers (default) |
| `large` | 48 px | `space.6` (24 px) | `font.body.large` | Single-action screens, mobile sign-in |

Every size clears the 24 by 24 CSS pixel minimum target on the [a11y checklist](accessibility.md) with room to spare. The small size is the floor: do not shrink a button with custom CSS to fit a cramped table. Use a tertiary icon button, or rethink the table.

## Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `variant` | one of `primary`, `secondary`, `tertiary`, `destructive` | `secondary` | Secondary is the default on purpose: primary should be a choice |
| `size` | one of `small`, `medium`, `large` | `medium` | |
| `children` | `ReactNode` | | The visible label. Required unless `iconOnly` is set |
| `iconStart`, `iconEnd` | icon name | | From the [icon library](icons.md). Do not pass both |
| `iconOnly` | icon name | | Renders a square button. Requires `aria-label` |
| `loading` | `boolean` | `false` | See "Loading state" |
| `loadingLabel` | `string` | `"Loading"` | Announced to screen readers when `loading` turns on |
| `disabled` | `boolean` | `false` | Prefer explaining why over disabling; see "Disabled buttons" |
| `confirm` | `ConfirmOptions` or `false` | | Required for `destructive`; see "Destructive actions" |
| `fullWidth` | `boolean` | `false` | Stretches to the container. Use on mobile layouts only |
| `type` | one of `button`, `submit`, `reset` | `button` | Note the default is `button`, not the browser's `submit` |
| `onClick` | `(event) => void` or `Promise` | | If it returns a promise and `loading` is not controlled, the button manages its own loading state |
| `as` | `"a"` | | Renders an anchor styled as a button, for the rare link that must look like one |

All other props pass through to the underlying element.

## Examples

A form footer: one primary, one secondary, primary on the right.

```typescript
import { Button, Stack } from "@quillmoor/inkwell";

export function PayoutScheduleFooter({ onCancel }: { onCancel: () => void }) {
  return (
    <Stack direction="row" gap="space.2" justify="end">
      <Button variant="secondary" onClick={onCancel}>
        Cancel
      </Button>
      <Button variant="primary" type="submit">
        Save schedule
      </Button>
    </Stack>
  );
}
```

An icon-only tertiary button in a table row. The label is not optional: without it, a screen reader announces "button" and nothing else.

```typescript
<Button
  variant="tertiary"
  size="small"
  iconOnly="download"
  aria-label={`Download statement for ${statement.period}`}
/>
```

## Destructive actions ask for confirmation

A destructive button never performs its action on the first click. It opens a confirmation, and only the confirmation performs the action. This is the rule with the fewest exceptions in Inkwell.

The `confirm` prop does the wiring: it opens a `ConfirmDialog` (built on the [modal dialog](modal.md)) with your title, body and confirm label, and calls `onConfirm` only when the user confirms.

```typescript
import { Button } from "@quillmoor/inkwell";

export function RevokeKeyButton({ keyId, keyName, onRevoke }: RevokeKeyProps) {
  return (
    <Button
      variant="destructive"
      iconStart="key-off"
      confirm={{
        title: `Revoke ${keyName}?`,
        body:
          "Requests signed with this key will be refused straight away. " +
          "This cannot be undone; you can create a new key afterwards.",
        confirmLabel: "Revoke key",
        onConfirm: () => onRevoke(keyId),
      }}
    >
      Revoke key
    </Button>
  );
}
```

Guidance for the confirmation:

- **Repeat the verb.** The confirm button says "Revoke key", not "OK" or "Yes". Someone skimming should be able to read only the button and know what happens.
- **Say what is lost.** Name the object and the consequence. "This cannot be undone" alone is not enough.
- **Focus starts on the safe choice.** `ConfirmDialog` places initial focus on "Cancel", so a stray Enter does nothing harmful.
- **Type to confirm for the worst cases.** For actions that cannot be recovered even by Support, such as closing a merchant account, pass `confirm.requireText` with the account name. The confirm button stays disabled until it matches.

In development builds Inkwell logs a console error when a `destructive` button has neither a `confirm` object nor `confirm={false}`. Pass `confirm={false}` only when the button is itself the confirming button inside a dialog, which is the one legitimate case of a destructive button that acts on click.

> [!TIP]
> If the action can be undone, it is probably not destructive. Archiving a report that can be restored is a secondary button followed by a toast with an "Undo" action; see the [toast component](toast.md).

## Loading state

Set `loading` while the action is in flight. The button:

- keeps its width, so the layout does not jump;
- replaces `iconStart`, or adds before the label, a spinner sized to the text;
- keeps the visible label, so the user still knows which button they pressed;
- sets `aria-busy="true"` and `aria-disabled="true"`, and announces `loadingLabel` once through a polite live region;
- ignores further clicks and Enter presses until `loading` is false again, which is what stops a double submission of a refund;
- **stays focusable.** We use `aria-disabled` rather than the `disabled` attribute so that keyboard focus is not thrown back to the top of the page.

The spinner appears only if the action takes longer than 150 ms, and stays for at least 400 ms once shown, so a fast response does not flash. Both delays come from the [motion tokens](motion.md).

If `onClick` returns a promise and you have not set `loading` yourself, the button sets it for you until the promise settles:

```typescript
<Button
  variant="primary"
  onClick={async () => {
    await api.exports.create({ range: "last-30-days" });
    toast.show({ tone: "success", message: "Export started" });
  }}
>
  Export payments
</Button>
```

Do not change the label to "Saving..." during loading. Changing the label changes the width, and screen readers announce the change inconsistently.

## Disabled buttons

A disabled button tells the user that something is wrong without saying what. Before disabling, try leaving the button enabled and showing a clear validation message when it is pressed; that is the default for forms in Merchant Hub.

When you must disable, for example because the user lacks a permission, put the reason next to the button or in a tooltip on a wrapping element, since disabled elements do not receive focus or hover.

## a11y notes

- The focus ring is the Inkwell two-tone ring: a 2 px `color.focus.gap` inner ring and a 2 px `color.focus.ring` outer ring. It is drawn outside the button with `outline` and never removed.
- Button text meets 4.5:1 against its fill in both themes; button boundaries for secondary buttons meet 3:1 against the surface.
- An icon-only button needs `aria-label`. The icon itself is decorative and hidden from assistive technology.
- Do not put a button inside a link or a link inside a button.
- A button that toggles a state, such as "Pause payouts", should use `aria-pressed` or be replaced by a switch.

### The destructive focus ring bug

Before Inkwell 3.2 the destructive button's focus ring was effectively invisible. The ring used `color.focus.ring`, but a component token override set it to the destructive red for "visual harmony", which put a red ring on a red button. The a11y remediation epic, ENG-25, found it in the December 2025 audit of Merchant Hub; it was fixed by introducing the two-tone ring, whose white (light theme) or near-black (dark theme) inner gap separates the ring from any fill. The [3.2 release notes](release-notes-inkwell-3-2.md) list it among the fixes. If you see a red ring on a destructive button, you are on an old version or still overriding `button.destructive.focus`, a token that has had no effect since 3.2 and goes in 4.0.

## Edge cases

- **Long labels.** Labels do not wrap; they truncate with an ellipsis after 32 characters and expose the full label as a tooltip. If yours truncates, shorten it. The [content style guide](content-style.md) asks for two or three words.
- **Translated labels.** French labels run about 20% longer. Test with `fr-FR` before shipping a button row that is tight in English.
- **Buttons in forms.** Our default `type` is `button`. Set `type="submit"` explicitly on the submitting button, or pressing Enter in a field will do nothing.
- **Many buttons in a row.** More than three buttons in one row is a sign the actions should move into a menu.
- **Right-to-left.** `iconStart` and `iconEnd` follow the writing direction, so arrows flip automatically.

## Do and don't

| Do | Don't |
|---|---|
| Use one primary button per region | Put two primary buttons next to each other |
| Label buttons with a verb and an object: "Issue refund" | Label buttons "OK", "Submit" or "Click here" |
| Ask for confirmation before every destructive action | Rely on a red colour to warn the user |
| Keep the button enabled and validate on press | Disable a submit button with no explanation |
| Use `loading` while a request is in flight | Swap the label to "Loading..." |
| Use a link for navigation | Use a button with `window.location` in `onClick` |
