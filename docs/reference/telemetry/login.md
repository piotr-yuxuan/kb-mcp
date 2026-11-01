# login

What `login atlassian` records, besides what every command does ([README](README.md)). A
run is a trace of one span, `login`: the sign-in happens in a Chrome window, which records
nothing. What to do in the window is a line on stderr for the user, not an event.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `login.not_signed_in` | error | `reason` | The sign-in did not complete, such as the window closed: exit 3 |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
