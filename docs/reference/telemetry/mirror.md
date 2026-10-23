# mirror

What `mirror` records, besides what every command does ([README](README.md)). A run is
one trace: its root `mirror`, then a span to read the raw store, one to build the files,
pandoc converting each document, and one to write them. A document is counted and
timed, never a span of its own: a run of thousands would make its trace too large.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `mirror.placed` | info | `documents`, `assets`, `problems` | The store is read: the documents placed in the mirror, their files attached, the problems so far |
| `mirror.document` | debug | `path`, `id`, `title`, `seconds` | A document's file is built, or fails to be: its path in the mirror, its id or key, its title |
| `mirror.written` | info | `written`, `unchanged`, `removed` | The mirror's files are written: how many changed, were already so, were removed |
| `mirror.not_mirrored` | warning | `where`, `reason` | Something is not mirrored, by its place in the raw store, never its content: the run exits 1 |
| `mirror.nothing_removed` | warning | `problems` | A run with problems removes no file, so that each last good copy stays |
| `mirror.pandoc_missing` | error | `reason` | Pandoc went from PATH once the run began: exit 1 |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `mirror.read` | internal | | The raw store read: spaces, users, listings, the newest snapshot of each document |
| `mirror.build` | internal | | Each document's file built, through pandoc, then each space's tree |
| `mirror.write` | internal | | The files that changed written, those no longer wanted removed |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `aom.mirror.documents` | counter | `{document}` | `aom.outcome` | The documents whose file was built, `mirrored`, or not, `failed` |
| `aom.mirror.conversion.duration` | histogram | `s` | | How long each document's file took to build, pandoc's conversion included |
