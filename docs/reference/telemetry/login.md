# login

What `login` records, besides what every command does ([README](README.md)). A
run is a trace of one span, `login`: the sign-in happens in a Chrome window, which records
nothing. What to do in the window is a line on stderr for the user, not an event. Before a
window opens, the session kept before sessions were a site's moves into the site's folder,
as [fetch](fetch.md) records it: `session.moved` and `session.not_moved`.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `login.signed_in` | info | `site` | A site is signed in, its session saved |
| `login.refused` | error | `source`, `reason` | A source in use, not named, whose location, such as its site, is not set, and which the login would sign in, not one that it leaves, such as one that signs in by an API token: it is not signed in, the others are, and the run exits 1 at least; named, the source refuses the run before it starts, `run.refused`, exit 2 |
| `login.not_signed_in` | error | `site`, `reason` | A site's sign-in did not complete, such as the window closed: the next site is tried, and the run exits 3 |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
