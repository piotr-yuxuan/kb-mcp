# index

What `index` records, besides what every command does ([README](README.md)). A run is
one trace: its root `index`, the connection to the model when the mode searches by
meaning, a span to read the mirror's files and one to embed their pieces, each batch an
embedding by the GenAI conventions over its requests. In the lexical mode, nothing is
sent to the embedding endpoint, and nothing of it is recorded.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `index.document` | debug | `path`, `type`, `sections` | A file of the mirror is indexed: its path, its document's type, its sections |
| `index.built` | info | `documents`, `sections`, `skipped`, `pieces`, `embedded` | The index is complete: what it holds, the files skipped, the pieces by meaning, the texts embedded now |
| `index.file_skipped` | warning | `path`, `reason` | A file cannot be read, its front matter is refused, or its document is there already: exit 1 |
| `index.piece_refused` | warning | `path` | The endpoint refuses a piece of this document, left without a vector: exit 1 |
| `index.lacks_files` | warning | `count` | How many files the index lacks |
| `index.not_built` | error | `reason`, `hint` | No mirror, or the endpoint or the model fails: the index in place stays, exit 1 |
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request for the endpoint's list of models |
| `http.post` | debug | `url`, `status`, `error`, `seconds` | Each request for embeddings |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `index.files` | internal | | The mirror's files read and indexed by words |
| `index.embed` | internal | | The pieces by meaning: their vectors read from the vector store, or embedded |
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
