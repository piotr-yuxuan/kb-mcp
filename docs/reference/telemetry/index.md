# index

What `index` records, besides what every command does ([README](README.md)). A run is
one trace: its root `index`, a span to read the mirror's files and one to join their people
into persons. It asks no endpoint, whatever `search_mode` says, and leaves the vector store
as it is. Before it reads the files, a build reads the alias file, `aliases.toml` in the
data directory, if there is one; once the files are read, it joins the documents' people
into persons through it. A build with vectors is [`embed`](embed.md)'s.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `index.document` | debug | `path`, `type`, `sections` | A file of the mirror is indexed: its path, its document's type, its sections |
| `index.built` | info | `documents`, `sections`, `skipped`, `pieces`, `embedded`, `people` | The index is complete: what it holds, the files skipped, no piece nor text embedded, the persons that the documents' people make |
| `index.file_skipped` | warning | `path`, `reason` | A file cannot be read, its front matter is refused, or its document is there already: exit 1 |
| `index.lacks_files` | warning | `count` | How many files the index lacks |
| `index.person_ambiguous` | warning | `spelling`, `people` | A name without an account that is the name of several accounts, or a transcript's speaker that begins the names of several participants of its meetings, or whose meetings name another than the one account of its name, once a build, as first spelt: it joins none of the persons it could be, how many said, and is a person by name alone. Or a name that two notes or more in brackets, such as `Kim (not in the header)` and `Kim (late)`, part among persons by name alone, as the first of them is spelt, how many said. An alias settles it; the exit status stays the build's |
| `index.alias_unused` | warning | `alias`, `key`, `reason` | An alias that changes nothing: its name as the file writes it, its key, and why: no name without an account has its key, or its target names nobody, or several people. The exit status stays the build's |
| `index.not_built` | error | `reason` | No mirror, the alias file is refused, by its path and any alias at fault, or cannot be read, or the index cannot be written (a full disk): the index in place stays, exit 1; in `sync`, its row fails |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `index.files` | internal | | The mirror's files read and indexed |
| `index.join` | internal | | The documents' people joined into persons, once the files are read |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.index.files` | counter | `{file}` | `kb_mcp.outcome` | The mirror's files, `indexed` or `skipped` |
