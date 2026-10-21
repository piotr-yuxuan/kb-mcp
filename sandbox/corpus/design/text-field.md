---
title: "Text field component"
---

# Text field component

Owner: Teodor Ashby (`#team-inkwell`). Last reviewed: 2026-07-09.

`TextField` collects a single line of text: a business name, an IBAN, a webhook URL, a refund amount. For several lines use `TextArea`; for a fixed set of choices use `Select` or `RadioGroup`.

```typescript
import { TextField } from "@quillmoor/inkwell";
```

## Anatomy

From top to bottom: the **label** (always visible), an optional **hint**, the **input** (40 px high, `radius.small`, border in `color.border.strong`), and the **message line**, which shows either the error or the character count.

## Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `label` | `string` | required | Visible label. There is no way to hide it |
| `hint` | `string` | | One sentence of help, shown under the label |
| `error` | `string` | | Shows the field in its error state and replaces the count |
| `required` | `boolean` | `false` | Adds "(required)" to the label only if the form marks required fields |
| `optional` | `boolean` | `false` | Adds "(optional)". Our forms mark whichever kind is rarer |
| `type` | one of `text`, `email`, `url`, `tel`, `password`, `search` | `text` | Use `NumberField` or `MoneyField` for numbers and amounts |
| `prefix`, `suffix` | `string` or icon name | | For units: "£", "%", "days" |
| `maxLength` | `number` | | Pair with `showCount` |
| `showCount` | `boolean` | `false` | Shows "12 of 40 characters" on the message line |
| `width` | one of `short`, `medium`, `full` | `full` | Match the width to the expected answer: a sort code is `short` |
| `autoComplete` | `string` | | Set it for personal and business details |

## Example

```typescript
export function WebhookUrlField({ value, onChange, error }: WebhookUrlFieldProps) {
  return (
    <TextField
      label="Endpoint URL"
      hint="We send events here as POST requests. It must use HTTPS."
      type="url"
      autoComplete="url"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      error={error}
    />
  );
}
```

## Validation

- Validate when the user leaves the field or submits, not on every keystroke. An error that appears while someone is still typing their email address is noise.
- Once a field shows an error, re-validate on each change so the error clears as soon as it is fixed.
- Error messages say what to do: "Enter a URL starting with https://", not "Invalid input". The [content style guide](content-style.md) has more examples.
- On submit, Merchant Hub forms show an `ErrorSummary` at the top and move focus to it; each entry links to its field.

## Do and don't

Do:

- Keep labels short and specific: "Business name", not "Please enter the name of your business".
- Use `prefix` for currency symbols rather than putting "£" in the label.
- Allow paste everywhere, including into password and one-time code fields.

Don't:

- Don't use the placeholder as a label or a hint. Placeholders vanish on input and fail contrast. `TextField` does not accept a `placeholder` prop for that reason, except with `type="search"`.
- Don't split one answer across several fields, such as a sort code in three boxes. One field with a hint about the format is easier to fill and to paste into.
- Don't disable a field to show a value that cannot change. Use read-only text, or `readOnly`, which keeps it focusable and selectable.

## a11y notes

The label is a real `label` element tied to the input. The hint and error are linked with `aria-describedby` in that order, and the error state sets `aria-invalid="true"`. The error is shown with an icon and text, never by the red border alone. Border contrast meets 3:1 against the surface in both themes. See the [a11y checklist](accessibility.md) for the form section in full.

## Edge cases

- **Very long values**, such as webhook URLs, scroll inside the input; the field does not grow. Show the full value elsewhere if the user needs to check it.
- **Autofill** colours are reset to Inkwell surfaces, so autofilled fields look right in the dark theme too.
- **Leading and trailing spaces** are not trimmed by the component; trim them in your submit handler. Merchants paste API keys with stray spaces more often than you would think.
