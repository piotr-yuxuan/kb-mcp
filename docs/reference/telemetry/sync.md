# sync

What `sync` records, besides what every command does ([README](README.md)). A run is one
trace: its root `sync`, then a span per row, `sync.step`, in which the row's step records
what its own command does: the download what [download.md](download.md) lists, the
mirror what [mirror.md](mirror.md) lists, the work log what this page lists, and the
index what [index.md](index.md) lists. The
task `work-log documents` reports each work-log document, by its title, as the README
says of tasks.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `sync.start` | info | `steps`, `dry_run` | The rows begin: each row planned, in order (`download`, `mirror`, `worklog`, `index`), and whether it is a dry run |
| `sync.step` | info | `step`, `outcome` | A row ends: `done`, `failed`, `sign in` or `not run` |
| `sync.interrupted` | warning | `step` | Ctrl-C stopped the run in this row, none if every row had ended; no later row runs: exit 130 |
| `sync.end` | info | `status`, `steps` | The rows end: the exit status, and each row as `<row>: <outcome>` |
| `sync.refused` | error | `reason` | What the run cannot go on with, found before the rows: an option of the period that does not read, a target with nowhere to start, a damaged record of what is covered, a work log that is not a folder: exit 2. An embedding endpoint that `index` would refuse is refused before, as `run.refused`, except in a dry run |
| `sync.pandoc_missing` | error | `reason` | Pandoc went from PATH once the run began: exit 1 |
| `worklog.read` | info | `entries`, `transcripts`, `html`, `problems` | The work log is read: its entries, its transcripts, the HTML transcripts left out, the files not read |
| `worklog.document` | debug | `path`, `id`, `title`, `kind`, `outcome` | A document's file is built: its path in the mirror, its id, its title, `entry` or `transcript`, and `mirrored`, converted, or `kept`, its revision held |
| `worklog.end` | info | `documents`, `written`, `unchanged`, `removed`, `to_convert`, `to_remove`, `problems` | The work log's files are written, or in a dry run, counted: those that a run would convert and remove |
| `worklog.problem` | warning | `where`, `reason` | A file not read, or a document not converted, by its path, never its content: the row fails |
| `worklog.same_id` | warning | `reason` | Two transcripts of one id: the second in path order is named by its whole path, both paths said |
| `worklog.nothing_removed` | warning | `problems` | A run with problems removes no work-log file, so that each last good copy stays |
| `worklog.pandoc_failed` | error | `reason` | Pandoc gave no version, so that no revision can be named: the work log's row fails |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `sync.step` | internal | `aom.step`, `aom.outcome` | A row, `download`, `mirror`, `worklog` or `index`, and how it ended; its step's own spans within. The row that Ctrl-C stops has no outcome, and the rows after it no span |
| `worklog.read` | internal | | The work log's folder listed, its files read and split into documents |
| `worklog.convert` | internal | | Each document's file built, through pandoc when no file holds its revision |
| `worklog.write` | internal | | The work log's files that changed written, those of documents gone removed |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `aom.mirror.documents` | counter | `{document}` | `aom.outcome`, `aom.kind` | The mirror's documents, as mirror.md says, and the work log's, by `aom.kind`, `entry` or `transcript`: `mirrored`, converted, `kept`, its revision held, or `failed` |
| `aom.mirror.conversion.duration` | histogram | `s` | `aom.kind` | How long each work-log document took pandoc to convert, by its kind; the mirror's, as mirror.md says |
