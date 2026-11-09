# index

What `index` records, besides what every command does ([README](README.md)). A run is
one trace: its root `index`, a span to read the mirror's files that changed and one to
join their people into persons. It asks no endpoint, whatever `search_mode` says, and
leaves the vector store as it is. It reads the alias file, `aliases.toml` in the data
directory, if there is one, then digests every file of the mirror and compares them with
what the index holds: with nothing changed, nothing is written. Else it builds the new
index beside the old one, copying the documents whose file did not change with their
pieces, reading those added or changed, leaving out those gone, and joining every
document's people into persons through the alias file; or it rebuilds the index whole.
It holds the index's lock, beside it, from its check that the index is still the one it
read until the new one is in place. A build with vectors is [`embed`](embed.md)'s.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `index.document` | debug | `path`, `type`, `sections` | A file of the mirror, added or changed, is read: its path, its document's type, its sections |
| `index.whole` | info | `reason` | The index is rebuilt whole, nothing kept of the one in place: `unavailable`, none that this version reads; `another version`, one written by another version of `WORDS`, or before plan 035; `damaged`, one of whose tables cannot be read; `--rebuild`, asked |
| `index.lock_wait` | info | `lock` | Another `index` or `embed` holds the index's lock: the run waits for it, at most 60 s, past which the index is not written |
| `index.restarted` | info | | Another run wrote the index between this run's read and its write: the update starts again, once |
| `index.built` | info | `documents`, `sections`, `skipped`, `people`, `copied`, `added`, `replaced`, `removed` | The index is written: what it holds, the files skipped, the persons that the documents' people make; of the documents of the index before, those copied, replaced by their file changed, and removed; those added |
| `index.unchanged` | info | `documents`, `sections`, `skipped` | No file of the mirror changed, nor the alias file, since the index: nothing is written; what it holds |
| `index.file_skipped` | warning | `path`, `reason` | A file cannot be read, its front matter is refused, or an earlier file by path has its document's source and id: exit 1, at each run, written or not |
| `index.lacks_files` | warning | `count` | How many files the index lacks |
| `index.person_ambiguous` | warning | `spelling`, `people` | A name without an account that is the name of several accounts, or a transcript's speaker that begins the names of several participants of its meetings, or whose meetings name another than the one account of its name, once a build, as first spelt: it joins none of the persons it could be, how many said, and is a person by name alone. Or a name that two notes or more in brackets, such as `Kim (not in the header)` and `Kim (late)`, part among persons by name alone, as the first of them is spelt, how many said. An alias settles it; the exit status stays the build's |
| `index.alias_unused` | warning | `alias`, `key`, `reason` | An alias that changes nothing, once a build: its name as the file writes it, its key, and why: no name without an account has its key, or its value names nobody, or several people. The exit status stays the build's |
| `index.not_built` | error | `reason` | No mirror, the alias file is refused, by its path and any alias at fault, or cannot be read, the index cannot be written (a full disk), its lock is held past 60 s, or another run wrote it twice during this one: the index in place stays, exit 1 |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `index.files` | internal | | The mirror's files added or changed read, every one for a whole rebuild |
| `index.join` | internal | | Every document's people joined into persons, at each write |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.index.files` | counter | `{file}` | `kb_mcp.outcome` | At each write, the documents `copied`, `added`, `replaced` or `removed`, and the files `skipped` |
