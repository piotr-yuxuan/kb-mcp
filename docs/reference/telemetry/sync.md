# sync

What `sync` records, besides what every command does ([README](README.md)). A run is one
trace: its root `sync`, then a span per row, `sync.step`, in which the row's role records
what its source's own command does: Confluence's and Jira's fetch what
[download.md](download.md) lists, their prepare what [mirror.md](mirror.md) lists, the
work log's prepare what this page lists, and the index what [index.md](index.md) lists,
reading the alias file as `index` does. The task `work-log documents` reports each
work-log document, by its title, as the README says of tasks.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `sync.start` | info | `steps`, `dry_run` | The rows begin: each row planned, in order, the fetch of each source taken that has a fetcher, the prepare of each, then the index (`fetch confluence`, `fetch jira`, `prepare confluence`, `prepare jira`, `prepare worklog`, `index`), and whether it is a dry run |
| `sync.step` | info | `step`, `outcome` | A row ends, named as `sync.start` names it: `done`, `failed`, `sign in` or `not run` |
| `sync.interrupted` | warning | `step` | Ctrl-C stopped the run in this row, none if every row had ended; no later row runs: exit 130 |
| `sync.end` | info | `status`, `steps` | The rows end: the exit status, and each row as `<row>: <outcome>` |
| `sync.refused` | error | `reason` | What the run cannot go on with, found before the rows: a role that its source's declaration names by a module path that does not load, or that lacks the role's methods, naming the source and the path; what a role's preflight refuses, such as a target with nowhere to start, a damaged record of what is covered, a work log that is not a folder: exit 2. An embedding endpoint that `index` would refuse, or an option of the period that does not read, is refused before, as `run.refused`, the endpoint except in a dry run |
| `worklog.read` | info | `entries`, `days`, `meetings`, `transcripts`, `html`, `problems` | The work log is read: its entries, days, meetings and transcripts, the HTML transcripts left out, the files not read |
| `worklog.document` | debug | `path`, `id`, `title`, `kind`, `outcome` | A document's file is built: its path in the mirror, its id, its title, `entry`, `day`, `meeting` or `transcript`, and `mirrored`, converted, or `kept`, its revision held |
| `worklog.end` | info | `documents`, `written`, `unchanged`, `removed`, `to_convert`, `to_remove`, `problems` | The work log's files are written, or in a dry run, counted: those that a run would convert and remove |
| `worklog.problem` | warning | `where`, `reason`, `held_back` | A file not read, or a document not converted, by its path, never its content, and what keeps its last copy for it, once a run until it is fixed: `every document` for `todo.org`, its archive or the work log's folder itself; a transcript's id for a transcript, whose last copy, if it has one, stays; `the transcripts not read under it` for a folder, the bound's problem or an HTML file linking out, which a path does not tell apart; the document's id for a conversion. Every other document is written, but the row fails |
| `worklog.same_id` | warning | `reason` | Two transcripts of one id: the second by the name of the folder that holds it, then by its own name, then in path order, is named by its whole path, both paths said. While the first is not read, a link to the id reaches the copy that the id last named, which may be the other file's |
| `worklog.unlinked` | warning | `meetings`, `first` | Meetings whose `:MEETING:` links no transcript found, read or not, once a run: how many, and the first one: by the file that its link names, from the work log's folder, when the link is in brackets or a path after `file:` or `./` and that file was not found, such as one in a folder other than `transcripts/` and `meetings/`; else by its id, for a path alone too, since any text reads as one. A link to a file found but not read is not counted: that file's `worklog.problem` names it. Never the link as written, which may be a meeting room's URL with its passcode. Each such meeting is written without the link, and the row neither fails nor holds a removal back |
| `worklog.nothing_removed` | warning | `problems` | A run with problems removes no work-log file but the old one of a document written again under another title's path, nor writes one that draws on a file not read, so that each last good copy stays: how many problems, each `worklog.problem` saying what it held back |
| `worklog.pandoc_failed` | error | `reason` | Pandoc gave no version, so that no revision can be named, or went from PATH once the run began: the work log's row fails |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `sync.step` | internal | `kb_mcp.step`, `kb_mcp.source`, `kb_mcp.outcome` | A row, `fetch` (once for each source fetched), `prepare` (once for each source prepared) or `index`, its source, none for the index, and how it ended; its role's own spans within. The row that Ctrl-C stops has no outcome, and the rows after it no span |
| `worklog.read` | internal | | The work log's folder listed, its files read and split into documents |
| `worklog.convert` | internal | | Each document's file built, through pandoc when no file holds its revision |
| `worklog.write` | internal | | The work log's files that changed written, those of documents gone removed |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.mirror.documents` | counter | `{document}` | `kb_mcp.outcome`, `kb_mcp.kind` | The mirror's documents, as mirror.md says, and the work log's, by `kb_mcp.kind`, `entry`, `day`, `meeting` or `transcript`: `mirrored`, converted, `kept`, its revision held, or `failed` |
| `kb_mcp.mirror.conversion.duration` | histogram | `s` | `kb_mcp.kind` | How long each work-log document took pandoc to convert, by its kind; the mirror's, as mirror.md says |
