# prepare

What `prepare` records, besides what every command does ([README](README.md)). A run is
one trace: its root `prepare`, then a span of each source taken, `prepare.source`, in the
registry's order. Confluence's and Jira's hold a span to read the store, one to build the
source's files and one to write them, within which each reads the whole store and places
every document, so that a link or an image of either reaches its file. The work log's
holds its own three, and the task `work-log documents` reports each of its documents, by
its title, as the README says of tasks. So a run gives each Atlassian event below once per
source, `prepare.document` once per document, `prepare.not_mirrored` once per problem and
per source that meets it, and `prepare.cache_replaced` once at most. A document is counted
and timed, never a span of its own: a span each would make a run's trace too large.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `prepare.start` | info | `sources`, `dry_run` | The sources that the run takes, in their order, and whether it only counts |
| `prepare.source` | info | `source`, `outcome` | A source's row ended: `done`, `failed` or, in a dry run of a source that cannot count, `not run` |
| `prepare.end` | info | `status`, `sources` | The run's exit status, and how each row ended |
| `prepare.refused` | error | `reason` | What the run cannot go on with, before its first row: a preparer that does not load, naming the source and the path, or what a preparer's preflight refuses, after its source and its stage (`source 'worklog': prepare: ...`), such as a work log that is not a folder, or types that are not all the kinds of one source: exit 2 |
| `prepare.interrupted` | warning | `source` | Ctrl-C stopped the row of this source, none once every row ended: later rows do not run, exit 130 |
| `prepare.placed` | info | `source`, `documents`, `assets`, `problems` | The store is read and every document placed, so that links reach the other source's: the source's documents placed in the mirror, the files they attach, its problems so far |
| `prepare.document` | debug | `path`, `id`, `title`, `seconds` | A document's file is built, or fails to be: its path in the mirror, its id or key, its title |
| `prepare.written` | info | `source`, `written`, `unchanged`, `removed`, `converted`, `reused`, `pruned` | The source's files are written: how many changed, were already so, were removed; the conversions pandoc ran, those the cache gave, and those deleted from the source's rows, which this run did not use, none when the source has problems |
| `prepare.not_mirrored` | warning | `source`, `where`, `reason` | Something is not written into the mirror, by the source that it belongs to, its place in the raw store and why, never its content. It fails that source's row, and the run exits 1. Each source reads the whole store: one that cannot be read of the other source's is said by both when both are prepared, and by this one alone otherwise, a prepare of one source going on, its row done, though its files may then link the document's address on the site and no longer its file |
| `prepare.nothing_removed` | warning | `source`, `problems` | A source with problems removes none of its files but those of documents gone or moved, nor an attached file, so that each last good copy stays. An attached file also stays, without this warning, while reading the store finds a problem of the other source's, such as a snapshot or listing that cannot be read, and while a document's file links it, such as the last good copy of a document that another prepare could not build, or of the source that a run leaves out |
| `prepare.cache_replaced` | warning | `reason` | The cache of conversions was damaged, no database, of a format that SQLite cannot read or may not write, or with a schema that names other columns, as a file of plan 039's, without `source`, has: deleted and started empty, so that the run converts everything; `reason`, SQLite's error name, `integrity_check`, or `UnicodeDecodeError` when SQLite's report quotes a name of the schema that is no longer UTF-8, never content |
| `prepare.pandoc_missing` | error | `reason` | Pandoc went from PATH once the run began: each of Confluence's and Jira's rows fails, writing nothing, the run exiting as its rows rank |
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
| `prepare.source` | internal | `kb_mcp.source`, `kb_mcp.outcome` | A source's row: its source and how it ended, no outcome on one that Ctrl-C stopped |
| `prepare.read` | internal | | The raw store read: spaces, users, listings, the newest snapshot of each document |
| `prepare.build` | internal | | Each of the source's documents' files built, through pandoc or the cache, then, for Confluence, each space's tree |
| `prepare.write` | internal | | The source's files that changed written, those no longer wanted removed, then the source's conversions this run did not use deleted |
| `worklog.read` | internal | | The work log's folder listed, its files read and split into documents |
| `worklog.convert` | internal | | Each document's file built, through pandoc when no file holds its revision |
| `worklog.write` | internal | | The work log's files that changed written, those of documents gone removed |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.prepare.documents` | counter | `{document}` | `kb_mcp.outcome`, `kb_mcp.kind` | The documents whose file was built, `mirrored`, or not, `failed`; the work log's, by `kb_mcp.kind`, `entry`, `day`, `meeting` or `transcript`, `mirrored`, converted, or `kept`, its revision held |
| `kb_mcp.prepare.conversion.duration` | histogram | `s` | `kb_mcp.kind` | How long each document's file took to build, pandoc's conversion included; a conversion reused costs the lookup alone; the work log's, by its kind |
