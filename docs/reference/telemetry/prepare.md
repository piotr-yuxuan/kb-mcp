# prepare

What `prepare` records, besides what every command does ([README](README.md)). A run is
one trace: its root `prepare`, then a span of each source taken, `prepare.source`, in the
registry's order. Confluence's and Jira's hold a span to read the raw store, one to build the
source's files and one to write them, within which each reads the whole store and places
every document, so that a link or an image of either reaches its file. The work log's
holds its own two, to build its files from its copy store and to write them, and the task
`work-log documents` reports each of its documents, by its title, as the README says of
tasks. So a run gives each Atlassian event below once per
source, `prepare.document` once per document, `prepare.not_mirrored` once per problem and
per source that meets it, and `prepare.cache_adopted` and `prepare.cache_replaced` once at
most, by the first unit that opens the cache, the work log's among them. A document is counted
and timed, never a span of its own: a span each would make a run's trace too large.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `prepare.start` | info | `sources`, `dry_run` | The stage begins: the sources whose units it runs, in their order, and whether it only counts; in a resume, those not done |
| `prepare.source` | info | `source`, `ending` | A source's unit ended: `done`, `failed` or `not run`, in a dry run or after its source's fetch did not end done in a refresh |
| `prepare.end` | info | `status`, `sources` | The stage ends: the exit status that its units' endings fold, and how each ended |
| `prepare.refused` | error | `source`, `reason` | What a preparer's preflight refuses as its source's unit begins, such as two sources of the pages of one site, or scope types that are not a space's or a project's, a problem by the source: that unit fails alone, and the next units go on. Without `source`, a preparer that does not load, naming the source and the path: the run stops before its first unit, exit 2 |
| `prepare.interrupted` | warning | `source` | Ctrl-C stopped the unit of this source, none once every unit ended: later units do not run, exit 130 |
| `prepare.placed` | info | `source`, `documents`, `assets`, `problems` | The raw store is read and every document placed, so that links reach the other source's: the source's documents placed in the mirror, the files they attach, its problems so far |
| `prepare.document` | debug | `path`, `id`, `title`, `seconds` | A document's file is built, or fails to be: its path in the mirror, its id or key, its title |
| `prepare.written` | info | `source`, `written`, `unchanged`, `removed`, `converted`, `reused`, `pruned` | The source's files are written: how many changed, were already so, were removed; the conversions pandoc ran, those the cache gave, and those deleted from the source's rows, which this run did not use, none when the source has problems |
| `prepare.not_mirrored` | warning | `source`, `where`, `reason` | Something is not written into the mirror, by the source whose prepare found it, its place in the raw store and why, never its content. A problem of that source's own fails its unit, and the run exits 1. Each source reads the whole store: one that cannot be read of the other source's is a warning of this unit, its reason naming that source, said by both when both are prepared, and by this one alone otherwise, a prepare of one source going on, its unit done, though its files may then link the document's address on the site and no longer its file |
| `prepare.nothing_removed` | warning | `source`, `problems` | A source with problems removes none of its files but those of documents gone or moved, nor an attached file, so that each last good copy stays. An attached file also stays, without this warning, while reading the raw store finds a problem of the other source's, such as a snapshot or listing that cannot be read, and while a document's file links it, such as the last good copy of a document that another prepare could not build, or of the source that a run leaves out |
| `prepare.cache_adopted` | info | `sources`, `rows` | The cache of conversions was of the layout without `source`, as the tag `pre-kb-mcp` wrote it: each of its `rows` became a row of each of the `sources`, so that the run converts nothing that it holds |
| `prepare.cache_replaced` | warning | `reason` | The cache of conversions was damaged, no database, of a format that SQLite cannot read or may not write, or with a schema that names other columns: deleted and started empty, so that the run converts everything; `reason`, SQLite's error name, `integrity_check`, or `UnicodeDecodeError` when SQLite's report quotes a name of the schema that is no longer UTF-8, never content |
| `prepare.pandoc_missing` | error | `reason` | Pandoc went from PATH once the run began: each of Confluence's and Jira's units fails, writing nothing, the run exiting as its units rank |
| `worklog.store_unread` | error | `source`, `reason` | The work log's copy store cannot be read: none yet, which `kb-mcp fetch` and the source write, or a file that does not read, by its path and field: the unit fails, writing nothing, and the others go on |
| `worklog.document` | debug | `path`, `id`, `title`, `type` | A document's file is built from its copy: its path in the mirror, its id, its title, `entry`, `day`, `meeting` or `transcript` |
| `worklog.end` | info | `documents`, `written`, `unchanged`, `removed`, `converted`, `reused`, `pruned`, `problems`; in a dry run, `documents` and `to_remove` | The work log's files are written: how many changed, were already so, were removed; the conversions pandoc ran, those the cache gave, and those deleted from the source's rows, which this run did not use, none when it has problems. Or, in a dry run, counted: the documents to write, the files to remove |
| `worklog.problem` | warning | `where`, `reason`, `held_back` | A document not converted, by its org file and id, never its content, and what keeps its last copy for it, its id, once a run until it is fixed. Every other document is written, but the unit fails |
| `worklog.nothing_removed` | warning | `problems` | A run with problems removes no work-log file but the old file of a document written again under another path, whose name no document not written could take, so that each last good copy stays: how many problems, each `worklog.problem` saying what it held back |
| `worklog.pandoc_failed` | error | `reason` | Pandoc gave no version, so that no conversion can be keyed, or went from PATH once the run began: the work log's unit fails, writing nothing |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `prepare.source` | internal | `kb_mcp.source`, `kb_mcp.ending` | A source's unit: its source and how it ended, no ending on one that Ctrl-C stopped |
| `prepare.read` | internal | | The raw store read: spaces, users, listings, the newest snapshot of each document |
| `prepare.build` | internal | | Each of the source's documents' files built, through pandoc or the cache, then, for Confluence, each space's tree; its folders' files, with no body and without pandoc, just before this span |
| `prepare.write` | internal | | The source's files that changed written, those no longer wanted removed, then the source's conversions this run did not use deleted |
| `worklog.convert` | internal | | Each document's file built from its copy, through pandoc or the cache |
| `worklog.write` | internal | | The work log's files that changed written, those of documents gone removed, then the source's conversions this run did not use deleted |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.prepare.documents` | counter | `{document}` | `kb_mcp.outcome`, `kb_mcp.type` | The documents whose file was built, `mirrored`, or not, `failed`; the work log's by `kb_mcp.type` too, `entry`, `day`, `meeting` or `transcript` |
| `kb_mcp.prepare.conversion.duration` | histogram | `s` | `kb_mcp.type` | How long each document's file took to build, pandoc's conversion included; a conversion reused costs the lookup alone; the work log's, by its type |
