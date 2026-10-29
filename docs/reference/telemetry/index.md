# index

What `index` records, besides what every command does ([README](README.md)). A run is
one trace: its root `index`, the connection to the model when the mode searches by
meaning, a span to read the mirror's files and one to embed their pieces, each batch an
embedding by the GenAI conventions over its requests. In the lexical mode, nothing is
sent to the embedding endpoint, and nothing of it is recorded. A build by meaning holds
the vector store's lock shared, and waits while a prune holds it. Once its index is in
place, the prune of the vector store is a span of its own, `index.prune`: the vectors
that neither the index nor an evaluation's index reads are deleted, and their pages
given back. Before any request to the endpoint, a build reads the alias file,
`aliases.toml` in the data directory, if there is one; once the files are read, it joins
the documents' people into persons through it.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `index.document` | debug | `path`, `type`, `sections` | A file of the mirror is indexed: its path, its document's type, its sections |
| `index.built` | info | `documents`, `sections`, `skipped`, `pieces`, `embedded`, `people` | The index is complete: what it holds, the files skipped, the pieces by meaning, the texts embedded now, the persons that the documents' people make |
| `index.file_skipped` | warning | `path`, `reason` | A file cannot be read, its front matter is refused, or its document is there already: exit 1 |
| `index.piece_refused` | warning | `path` | The endpoint refuses a piece of this document, left without a vector: exit 1 |
| `index.lacks_files` | warning | `count` | How many files the index lacks |
| `index.person_ambiguous` | warning | `spelling`, `people` | A name without an account that is the name of several accounts, or a transcript's speaker that begins the names of several participants of its meetings, once a build, as first spelt: it joins none of the persons it could be, how many said, and is a person by name alone. An alias settles it; the exit status stays the build's |
| `index.alias_unused` | warning | `alias`, `key`, `reason` | An alias that changes nothing: its name as the file writes it, its key, and why: no name without an account has its key, or its target names nobody, or several people. The exit status stays the build's |
| `vectors.lock_wait` | info | `lock` | A prune holds the vector store's lock: the build waits for it, at most 60 s, past which the index is not built |
| `index.pruned` | info | `kept`, `kept_for_evaluation`, `deleted`, `bytes_before`, `bytes_after`, `seconds`, `shrinks`, `converted`, `reclaimed`, `reason` | The vector store is pruned: the vectors kept, those that the evaluation's indexes alone read, those deleted; its size before and after, in bytes; whether it gives freed pages back, whether this prune converted a store made by an earlier version to do so, and whether these went back, else why not |
| `index.prune_deferred` | info | `reason` | A build, or another prune, holds the vector store's lock: nothing is deleted, and the next `index` prunes |
| `index.prune_skipped` | warning | `outcome`, `reason`, `file` | Nothing is deleted: `held back` when the build skipped a file or indexed no document, an index cannot say which vectors it reads, by words alone, built before plan 023, at another schema (an evaluation's built before plan 041) or damaged (the file), or a folder of the evaluation's cannot be listed, or an entry below it is a link (the folder or the link); `failed` when the store could not delete. The exit status stays the build's |
| `index.not_built` | error | `reason`, `hint` | No mirror, the alias file is refused, by its path and any alias at fault, or cannot be read, the endpoint or the model fails, or the index cannot be written (a full disk): the index in place stays, exit 1; in `sync`, its row fails |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for the endpoint's list of models |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for embeddings |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `index.files` | internal | | The mirror's files read and indexed by words |
| `index.embed` | internal | | The pieces by meaning: their vectors read from the vector store, or embedded |
| `index.prune` | internal | `aom.outcome`, `aom.deleted` | The prune of the vector store, once the index is in place: `pruned`, `deferred`, `held back` or `failed`, and the vectors deleted |
| `embeddings <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens` | An embedding by the GenAI conventions, its attempts included, and the tokens that the endpoint counted, if it did; the provider `openai`, the API spoken |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | The endpoint's list of models, by the HTTP conventions |
| `POST` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each attempt at an embedding, by the HTTP conventions |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
| `gen_ai.client.operation.duration` | histogram | `s` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type` | Each embedding, its attempts and waits included, by the GenAI conventions |
| `gen_ai.client.token.usage` | histogram | `{token}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `gen_ai.token.type` | The tokens that each embedding's answer counted, `input` by type, when the endpoint counts them, by the GenAI conventions |
| `aom.index.files` | counter | `{file}` | `aom.outcome` | The mirror's files, `indexed` or `skipped` |
| `aom.index.pieces` | counter | `{piece}` | `aom.outcome` | The pieces by meaning, `indexed` with a vector or `refused` one |
| `aom.vectors` | counter | `{vector}` | `aom.outcome` | The vector store's vectors at a prune, `kept` or `pruned` |
| `aom.vectors.bytes` | gauge | `By` | | The vector store's size after a prune, its WAL aside |
