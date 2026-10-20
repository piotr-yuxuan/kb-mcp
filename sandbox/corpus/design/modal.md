---
title: "Modal dialog component"
---

# Modal dialog component

> Owner: Dafydd Morrow, Design System team. Last reviewed 2026-06-18. Chat: `#team-inkwell`.

A modal dialog interrupts. It blocks the page behind it until the user deals with it, so we use it sparingly: to confirm a consequential action, or to complete a short, self-contained task without losing the page's context.

## Should this be a modal?

| Situation | Use |
|---|---|
| Confirm a destructive action: revoke a key, delete a webhook | `ConfirmDialog` |
| A short task of one to four fields: rename a report, add a team member | `Modal` |
| A long form, or anything with its own steps | A full page |
| Details the user wants to compare with the list behind | A side drawer (`Drawer`) |
| "Your changes were saved" | A [toast](toast.md), never a modal |
| Marketing announcements | Nothing. Not in Merchant Hub |

If you find yourself opening a modal from inside a modal, stop. Stacked dialogs are not supported and the second one will throw in development.

## Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `open` | `boolean` | required | Controlled only |
| `onClose` | `() => void` | required | Called on Escape, on the close button, and on a backdrop click if `dismissible` |
| `title` | `string` | required | Rendered as the dialog heading and used as its label |
| `description` | `string` | | A sentence under the title, linked with `aria-describedby` |
| `size` | one of `small`, `medium`, `large` | `medium` | 400, 560 and 720 px wide; full screen under 600 px |
| `dismissible` | `boolean` | `true` | Set `false` while a save is in flight |
| `initialFocus` | ref | first field | Override only with good reason |
| `footer` | `ReactNode` | | Buttons, right-aligned, primary last |

## Example

```typescript
import { Button, Modal, TextField } from "@quillmoor/inkwell";

export function RenameReportModal({ open, report, onClose, onSave }: RenameProps) {
  const [name, setName] = useState(report.name);
  const [saving, setSaving] = useState(false);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Rename report"
      size="small"
      dismissible={!saving}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={saving}
            onClick={async () => {
              setSaving(true);
              await onSave(name);
              onClose();
            }}
          >
            Save name
          </Button>
        </>
      }
    >
      <TextField label="Report name" value={name} onChange={(e) => setName(e.target.value)} />
    </Modal>
  );
}
```

## ConfirmDialog

`ConfirmDialog` is a small modal with a fixed layout: title, body, "Cancel", and a confirm button. Destructive buttons open it through their `confirm` prop, as described on the [button page](button.md), so you rarely render it directly. It differs from `Modal` in two ways: initial focus goes to "Cancel", not to the confirm button; and the confirm button uses the destructive variant when the action is destructive.

## Behaviour and a11y

- Opening moves focus into the dialog; closing returns it to the element that opened it. If that element no longer exists, focus goes to the page's main heading.
- Tab and Shift+Tab cycle within the dialog. Escape closes it unless `dismissible` is `false`.
- The page behind is made inert, so screen readers cannot wander out of the dialog.
- The dialog has `role="dialog"` and `aria-modal="true"`, labelled by its title.
- Scrolling of the page behind is locked; the dialog body scrolls if its content is taller than the viewport, with the header and footer fixed.
- Entry and exit use `motion.duration.base`; with reduced motion the dialog appears without scaling.

## Do and don't

- **Do** write the title as a question or an action: "Revoke this key?", "Add a team member".
- **Do** keep the footer to two buttons. Three is acceptable only for "Save", "Discard" and "Cancel" on unsaved changes.
- **Don't** open a modal on page load.
- **Don't** put a data table or a multi-step wizard in a modal.
- **Don't** close the dialog on backdrop click while a form inside it has unsaved input; Inkwell asks before discarding if you pass `hasUnsavedChanges`.
