# embed

What `embed` records, besides what every command does ([README](README.md)). A run is
one trace: its root `embed`, the connection to the model, then a span to give the chunks
to add their vectors, each batch an embedding by the GenAI conventions over its
requests. It reads the index, never the mirror's files but for their digests, which it
compares with what the index holds, and never the alias file: it warns when the mirror
changed since the index, and goes on. It cuts the index's documents into the chunks
that the run's chunking and model want, takes their vectors from the vector cache, else
from the model, holding the store's lock shared while a prune holds it not, and writes
the chunks added and removed into a copy of the index, under the index's lock, from its
check that the index is still the one it read until the copy is in place. Then the prune
of the vector cache is a span of its own, `index.prune`: the vectors that neither the
index, as `embed` wrote it, nor an evaluation's index reads are deleted, and their pages
given back.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `embed.mirror_changed` | warning | `changed`, `added`, `removed`, `hint` | Files of the mirror differ from what the index holds: those changed, added and removed since `index`, which the hint names; the run fills the index as it is, and its exit status stays |
| `index.lock_wait` | info | `lock` | Another `index` or `embed` holds the index's lock: the run waits for it, at most 60 s, past which nothing is filled |
| `index.restarted` | info | | Another run wrote the index between this run's read and its write: the fill starts again, once, the vectors now in the store |
| `embed.filled` | info | `added`, `removed`, `embedded`, `found`, `refused`, `chunks` | The index is written: the chunks added and removed, the texts embedded now and those found in the vector cache, the documents with a chunk refused, the chunks it holds |
| `embed.unchanged` | info | `chunks` | No chunk to add or remove, nor another model: nothing is written; the chunks it holds |
| `index.chunk_refused` | warning | `path` | The endpoint refuses a chunk of this document, left without a vector and asked again by the next run: exit 1 |
| `vectors.lock_wait` | info | `lock` | A prune holds the vector cache's lock: the run waits for it, at most 60 s, past which nothing is filled |
| `index.pruned` | info | `kept`, `kept_for_evaluation`, `deleted`, `bytes_before`, `bytes_after`, `seconds`, `shrinks`, `converted`, `reclaimed`, `reason` | The vector cache is pruned: the vectors kept, those that the evaluation's indexes alone read, those deleted; its size before and after, in bytes; whether it gives freed pages back, whether this prune converted a store made by an earlier version to do so, and whether these went back, else why not |
| `index.prune_deferred` | info | `reason` | A build, or another prune, holds the vector cache's lock: nothing is deleted, and the next `embed` prunes |
| `index.prune_skipped` | warning | `outcome`, `reason`, `file` | Nothing is deleted: `held back` when the index lacks a file of the mirror (exit 1) or holds no document, an index cannot say which vectors it reads, by words alone, built before plan 023, at another schema (an evaluation's built before plan 054) or damaged (the file), or a folder of the evaluation's cannot be listed, or an entry below it is a link (the folder or the link); `failed` when the store could not delete. The exit status stays the run's |
| `index.not_built` | error | `reason` | No index, or one that another version or no record of its files wrote, which `kb-mcp index` writes; one damaged, which `kb-mcp index --rebuild` rebuilds; the endpoint or the model fails; the index cannot be written (a full disk), its lock is held past 60 s, or another run wrote it twice during this one: the index in place stays, exit 1 |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for the endpoint's list of models |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for embeddings |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `index.embed` | internal | | The chunks to add: their vectors read from the vector cache, or embedded |
| `index.prune` | internal | `kb_mcp.outcome`, `kb_mcp.deleted` | The prune of the vector cache, once the index is in place: `pruned`, `deferred`, `held back` or `failed`, and the vectors deleted |
| `embeddings <model>` | client | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type`, `gen_ai.usage.input_tokens` | An embedding by the GenAI conventions, its attempts included, and the tokens that the endpoint counted, if it did; the provider `openai`, the API spoken |
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | The endpoint's list of models, by the HTTP conventions |
| `POST` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each attempt at an embedding, by the HTTP conventions |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |
| `gen_ai.client.operation.duration` | histogram | `s` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `error.type` | Each embedding, its attempts and waits included, by the GenAI conventions |
| `gen_ai.client.token.usage` | histogram | `{token}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `server.address`, `server.port`, `gen_ai.token.type` | The tokens that each embedding's answer counted, `input` by type, when the endpoint counts them, by the GenAI conventions |
| `kb_mcp.index.chunks` | counter | `{chunk}` | `kb_mcp.outcome` | At each write, the chunks `added` with a vector, `removed`, or `refused` one |
| `kb_mcp.vectors` | counter | `{vector}` | `kb_mcp.outcome` | The vector cache's vectors at a prune, `kept` or `pruned` |
| `kb_mcp.vectors.bytes` | gauge | `By` | | The vector cache's size after a prune, its WAL aside |
