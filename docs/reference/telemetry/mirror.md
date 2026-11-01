# mirror

What `mirror` records, besides what every command does ([README](README.md)). A run is
one trace: its root `mirror`, then, for Confluence, then for Jira, a span to read the
raw store, one to build the source's files, pandoc converting what the source's rows of
the cache of conversions, `<data>/conversions.sqlite`, do not hold yet, and one to write
them. So a run gives each event below once per source, `mirror.document` once per
document, `mirror.not_mirrored` once per problem and per source that meets it, and
`mirror.cache_replaced` once at most. A document is counted and timed, never a span of
its own: a run of thousands would make its trace too large.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `mirror.placed` | info | `source`, `documents`, `assets`, `problems` | The store is read and every document placed, so that links reach the other source's: the source's documents placed in the mirror, the files they attach, its problems so far |
| `mirror.document` | debug | `path`, `id`, `title`, `seconds` | A document's file is built, or fails to be: its path in the mirror, its id or key, its title |
| `mirror.written` | info | `source`, `written`, `unchanged`, `removed`, `converted`, `reused`, `pruned` | The source's files are written: how many changed, were already so, were removed; the conversions pandoc ran, those the cache gave, and those deleted from the source's rows, which this run did not use, none when the source has problems |
| `mirror.not_mirrored` | warning | `source`, `where`, `reason` | Something is not mirrored, by the source that it belongs to, its place in the raw store and why, never its content. It fails that source's row, and the run exits 1. Each source reads the whole store: one that cannot be read of the other source's is said by both when both are prepared, and by this one alone otherwise, a prepare of one source going on, its row done, though its files may then link the document's address on the site and no longer its file |
| `mirror.nothing_removed` | warning | `source`, `problems` | A source with problems removes none of its files, nor an attached file, so that each last good copy stays. An attached file also stays, without this warning, while reading the store finds a problem of the other source's, such as a snapshot or listing that cannot be read, and while a document's file links it, such as the last good copy of a document that another prepare could not build, or of the source that a run leaves out |
| `mirror.cache_replaced` | warning | `reason` | The cache of conversions was damaged, no database, of a format that SQLite cannot read or may not write, or with a schema that names other columns, as a file of plan 039's, without `source`, has: deleted and started empty, so that the run converts everything; `reason`, SQLite's error name, `integrity_check`, or `UnicodeDecodeError` when SQLite's report quotes a name of the schema that is no longer UTF-8, never content |
| `mirror.pandoc_missing` | error | `reason` | Pandoc went from PATH once the run began: exit 1; in `sync`, each of Confluence's and Jira's rows fails, the run exiting as its rows rank |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `mirror.read` | internal | | The raw store read: spaces, users, listings, the newest snapshot of each document |
| `mirror.build` | internal | | Each of the source's documents' files built, through pandoc or the cache, then, for Confluence, each space's tree |
| `mirror.write` | internal | | The source's files that changed written, those no longer wanted removed, then the source's conversions this run did not use deleted |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.mirror.documents` | counter | `{document}` | `kb_mcp.outcome` | The documents whose file was built, `mirrored`, or not, `failed` |
| `kb_mcp.mirror.conversion.duration` | histogram | `s` | | How long each document's file took to build, pandoc's conversion included; a conversion reused costs the lookup alone |
