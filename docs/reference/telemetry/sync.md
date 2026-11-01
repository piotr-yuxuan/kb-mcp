# sync

What `sync` records, besides what every command does ([README](README.md)). A run is one
trace: its root `sync`, then a span per row, `sync.step`, in which the row's role records
what its source's own command does: Confluence's and Jira's fetch what
[fetch.md](fetch.md) lists, each source's prepare what [prepare.md](prepare.md) lists, and
the index what [index.md](index.md) or [embed.md](embed.md) lists, reading the alias file
as `index` does.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `sync.start` | info | `steps`, `dry_run` | The rows begin: each row planned, in order, the fetch of each source taken that has a fetcher, the prepare of each, then the index (`fetch confluence`, `fetch jira`, `prepare confluence`, `prepare jira`, `prepare worklog`, `index`), and whether it is a dry run |
| `sync.step` | info | `step`, `outcome` | A row ends, named as `sync.start` names it: `done`, `failed`, `sign in` or `not run` |
| `sync.interrupted` | warning | `step` | Ctrl-C stopped the run in this row, none if every row had ended; no later row runs: exit 130 |
| `sync.end` | info | `status`, `steps` | The rows end: the exit status, and each row as `<row>: <outcome>` |
| `sync.refused` | error | `reason` | What the run cannot go on with, found before the rows: a role that its source's declaration names by a module path that does not load, or that lacks the role's methods, naming the source and the path; what a role's preflight refuses, after its source and its step (`source 'confluence': fetch: ...`), such as a target with nowhere to start, a damaged record of what is covered or, for Confluence's fetch, of what answered as gone, a work log that is not a folder: exit 2. An embedding endpoint that `index` would refuse, or an option of the period that does not read, is refused before, as `run.refused`, the endpoint except in a dry run |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `sync.step` | internal | `kb_mcp.step`, `kb_mcp.source`, `kb_mcp.outcome` | A row, `fetch` (once for each source fetched), `prepare` (once for each source prepared) or `index`, its source, none for the index, and how it ended; its role's own spans within. The row that Ctrl-C stops has no outcome, and the rows after it no span |
